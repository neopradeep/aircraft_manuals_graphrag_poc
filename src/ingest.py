"""Parse HTML manuals -> lexical graph (Document/Section/Chunk+embeddings) + domain graph (Part/Assembly/Variant/Procedure).
Interchangeability statements are extracted by an LLM into typed CAN_REPLACE / CANNOT_REPLACE edges.

  python -m src.ingest --dry-run      # parse only, no DB/LLM
  python -m src.ingest --reset        # wipe graph, rebuild
"""
import argparse, re
from pathlib import Path
from bs4 import BeautifulSoup
from . import common as C

HTML_DIR = C.ROOT / "corpus/html"

EXTRACT_SYSTEM = """You convert one aircraft-parts interchangeability statement into structured JSON.
You are given THIS part number (the part whose entry/manual contains the statement), the OTHER part number(s) mentioned, and the statement text.
Return JSON with exactly these keys:
 "other_pn": the single other part number the statement is about (string) or null if none,
 "this_can_replace_other": "yes" | "no" | "conditional",
 "other_can_replace_this": "yes" | "no" | "conditional",
 "condition": the service bulletin / condition text if replacement is conditional, else null,
 "only_variants": list of aircraft variant names if the statement limits interchangeability to specific aircraft, else null,
 "supersedes": "this" if THIS part supersedes/replaces the other, "other" if the OTHER supersedes/replaces THIS (e.g. "SUPERSEDED BY x"), else "none".
Rules: "interchangeable"/"alternate for" with no restriction => both "yes". One-way supersession: the new part can replace the old, the old CANNOT replace the new.
"after incorporation of SB"/"when SB is embodied" => both "conditional" with the SB in "condition". Be literal; do not invent restrictions."""


def parse_doc(path: Path):
    soup = BeautifulSoup(path.read_text(), "html.parser")
    body = soup.body
    meta = body.find("p").get_text(" ")
    g = lambda k: (re.search(k + r":\s*([^|]+)", meta) or [None, None])[1]
    doc = {"file": path.name, "type": g("Document type").strip(), "revision": int(g("Revision") or 15),
           "fleet": (g("Fleet") or "").strip() or None, "title": soup.title.get_text()}
    chunks, rows, stmts, tasks = [], [], [], []
    if doc["type"] == "IPC":
        legend = {}
        for tr in soup.find("h2", string="Effectivity Legend").find_next("table").find_all("tr")[1:]:
            c = [td.get_text() for td in tr.find_all("td")]
            legend[c[0]] = c[1]
        for sec in soup.select("section[data-ata]"):
            ata = sec["data-ata"]
            aname = sec.find("h2").get_text().split(" ", 1)[1]
            fig = sec.find("figcaption").get_text()
            group = None
            def flush():
                if group:
                    cid = f"{doc['file']}#{ata}#{group['item']}"
                    text = (f"[IPC {doc['fleet']} Rev {doc['revision']} | ATA {ata} {aname} | {fig}]\n" +
                            "\n".join(group["lines"]))
                    chunks.append({"id": cid, "text": text, "ata": ata, "kind": "ipc_item", "section": f"{doc['file']}#{ata}",
                                   "section_title": f"{ata} {aname}", "parts": sorted(set(C.PN_RE.findall(text)))})
                    for s in group["stmts"]:
                        s["chunk_id"] = cid
                        stmts.append(s)
            last_pn = None
            for tr in sec.find("table").find_all("tr")[1:]:
                tds = [td.get_text() for td in tr.find_all("td")]
                if "note" in (tr.get("class") or []):
                    note = tds[-1]
                    group["lines"].append(f"  NOTE: {note}")
                    group["stmts"].append({"this_pn": last_pn, "text": note, "doc": doc["file"], "revision": doc["revision"],
                                           "doc_type": "IPC", "variants": list(legend.values())})
                    continue
                item, pn, name, eff, qty = tds
                if not item.endswith("A"):
                    flush()
                    group = {"item": item, "lines": [], "stmts": []}
                codes = list(legend) if eff.strip() == "ALL" else eff.split()
                names = [legend[c] for c in codes]
                group["lines"].append(f"ITEM {item}: PN {pn} | {name} | EFFECTIVE ON: {', '.join(names)} | UPA {qty}")
                rows.append({"pn": pn, "name": name, "item": item, "qty": int(qty), "variants": names, "fleet": doc["fleet"],
                             "ata": ata, "assembly": aname, "figure": fig.replace("FIGURE ", ""), "doc": doc["file"]})
                last_pn = pn
            flush()
    elif doc["type"] == "AMM":
        for sec in soup.select("section[data-ata]"):
            ata = sec["data-ata"]
            h2 = sec.find("h2").get_text()
            tid = re.search(r"TASK [\d-]+", h2).group(0)
            title = h2.split(" - ", 1)[1]
            pns = []
            for h3 in sec.find_all("h3"):
                texts, el = [h3.get_text()], h3.find_next_sibling()
                while el is not None and el.name != "h3":
                    texts.append(el.get_text(" ", strip=True))
                    el = el.find_next_sibling()
                text = f"[AMM {doc['fleet']} | {tid} | {title}]\n" + "\n".join(texts)
                found = sorted(set(C.PN_RE.findall(text)))
                pns += found
                chunks.append({"id": f"{doc['file']}#{tid}#{h3.get_text()[:3]}", "text": text, "ata": ata, "kind": "amm_step",
                               "section": f"{doc['file']}#{tid}", "section_title": h2, "parts": found})
            tasks.append({"task_id": tid, "title": title, "ata": ata, "fleet": doc["fleet"], "doc": doc["file"], "parts": sorted(set(pns))})
    elif doc["type"] == "CMM":
        this_pn = g("Part").strip()
        for sec in soup.find_all("section"):
            h2 = sec.find("h2").get_text()
            text = f"[CMM {doc['title']} | {h2}]\n" + sec.get_text(" ", strip=True)
            cid = f"{doc['file']}#{h2.split('.')[0]}"
            chunks.append({"id": cid, "text": text, "ata": None, "kind": "cmm_section", "section": cid, "section_title": h2,
                           "parts": sorted(set(C.PN_RE.findall(text)))})
            if sec.get("data-section") == "interchangeability":
                stmts.append({"this_pn": this_pn, "text": sec.get_text(" ", strip=True), "doc": doc["file"], "revision": doc["revision"],
                              "doc_type": "CMM", "chunk_id": cid,
                              "variants": [n for v in C.VARIANTS.values() for n in v.values()]})
    return doc, chunks, rows, stmts, tasks


def extract_statements(stmts, workers=8):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def one(s):
        others = [p for p in C.PN_RE.findall(s["text"]) if p != s["this_pn"]]
        user = (f"THIS part: {s['this_pn']}\nOTHER part number(s) mentioned: {', '.join(others) or 'none'}\n"
                f"Known aircraft variant names: {', '.join(s['variants'])}\nStatement: {s['text']}")
        try:
            r = C.chat_json(EXTRACT_SYSTEM, user)
        except Exception as e:
            print(f"  ! failed ({str(e)[:120]})")
            return None
        if isinstance(r, dict) and r.get("other_pn") and C.PN_RE.fullmatch(str(r["other_pn"])):
            return {**s, **r}
        return None
    out, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, s) for s in stmts]
        for f in as_completed(futs):
            done += 1
            if f.result():
                out.append(f.result())
            if done % 10 == 0 or done == len(stmts):
                print(f"  {done}/{len(stmts)} statements processed, {len(out)} structured", flush=True)
    return out


SCHEMA = [
    "CREATE CONSTRAINT part_pn IF NOT EXISTS FOR (n:Part) REQUIRE n.pn IS UNIQUE",
    "CREATE CONSTRAINT doc_file IF NOT EXISTS FOR (n:Document) REQUIRE n.file IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (n:Section) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT asm_id IF NOT EXISTS FOR (n:Assembly) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT var_id IF NOT EXISTS FOR (n:Variant) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT proc_id IF NOT EXISTS FOR (n:Procedure) REQUIRE n.id IS UNIQUE",
    f"CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
    f"OPTIONS {{indexConfig: {{`vector.dimensions`: {C.EMBED_DIM}, `vector.similarity_function`: 'cosine'}}}}",
    "CREATE FULLTEXT INDEX asm_ft IF NOT EXISTS FOR (n:Assembly) ON EACH [n.name]",
    "CREATE FULLTEXT INDEX proc_ft IF NOT EXISTS FOR (n:Procedure) ON EACH [n.title]",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    docs, chunks, rows, stmts, tasks = [], [], [], [], []
    for p in sorted(HTML_DIR.glob("*.html")):
        d, c, r, s, t = parse_doc(p)
        docs.append(d); chunks += c; rows += r; stmts += s; tasks += t
    print(f"parsed: docs={len(docs)} chunks={len(chunks)} part_rows={len(rows)} statements={len(stmts)} tasks={len(tasks)}")
    if args.dry_run:
        return

    print("extracting interchangeability statements with LLM (cached)...")
    rels = extract_statements(stmts)
    print(f"  structured relations: {len(rels)}")
    print("embedding chunks...")
    embs = C.embed([c["text"] for c in chunks])
    for c, e in zip(chunks, embs):
        c["embedding"] = e

    drv = C.get_driver()
    db = C.NEO4J_DATABASE
    with drv.session(database=db) as s:
        if args.reset:
            s.run("MATCH (n) DETACH DELETE n")
            s.run("DROP INDEX chunk_embedding IF EXISTS")  # dimension may differ from a previous run's embedding model
        for q in SCHEMA:
            s.run(q)
        s.run("UNWIND $d AS d MERGE (n:Document {file:d.file}) SET n.type=d.type, n.revision=d.revision, n.fleet=d.fleet, n.title=d.title", d=docs)
        vs = [{"id": f"{f}:{c}", "name": n, "fleet": f} for f, m in C.VARIANTS.items() for c, n in m.items()]
        s.run("UNWIND $v AS v MERGE (n:Variant {id:v.id}) SET n.name=v.name, n.fleet=v.fleet", v=vs)
        s.run("""UNWIND $r AS r
            MERGE (a:Assembly {id: r.fleet+'-'+r.ata}) SET a.name=r.assembly, a.ata=r.ata, a.figure=r.figure, a.fleet=r.fleet
            MERGE (p:Part {pn:r.pn}) SET p.name=r.name, p.fleet=r.fleet
            MERGE (p)-[c:COMPONENT_OF]->(a) SET c.item=r.item, c.qty=r.qty
            WITH p, r UNWIND r.variants AS vn
            MATCH (v:Variant {fleet:r.fleet, name:vn}) MERGE (p)-[:EFFECTIVE_ON]->(v)""", r=rows)
        s.run("""UNWIND $c AS c MATCH (d:Document {file: split(c.section,'#')[0]})
            MERGE (sec:Section {id:c.section}) SET sec.title=c.section_title, sec.ata=c.ata MERGE (sec)-[:IN_DOCUMENT]->(d)
            MERGE (ch:Chunk {id:c.id}) SET ch.text=c.text, ch.kind=c.kind, ch.doc=d.file, ch.embedding=c.embedding
            MERGE (ch)-[:IN_SECTION]->(sec)""", c=chunks)
        s.run("""UNWIND $c AS c MATCH (ch:Chunk {id:c.id}) UNWIND c.parts AS pn
            MATCH (p:Part {pn:pn}) MERGE (ch)-[:MENTIONS]->(p)""", c=[{"id": c["id"], "parts": c["parts"]} for c in chunks])
        s.run("""UNWIND $t AS t MERGE (pr:Procedure {id:t.doc+'#'+t.task_id}) SET pr.task_id=t.task_id, pr.title=t.title, pr.doc=t.doc, pr.ata=t.ata
            WITH pr, t MATCH (a:Assembly {id:t.fleet+'-'+t.ata}) MERGE (pr)-[:COVERS]->(a)
            WITH pr, t UNWIND t.parts AS pn MATCH (p:Part {pn:pn}) MERGE (pr)-[:REQUIRES_PART]->(p)""", t=tasks)
        edges = []
        for r in rels:
            props = {"doc": r["doc"], "revision": r["revision"], "source_type": r["doc_type"], "condition": r.get("condition"),
                     "only_variants": r.get("only_variants") or [], "chunk_id": r["chunk_id"], "statement": r["text"]}
            for a, b, verdict in ((r["this_pn"], r["other_pn"], r["this_can_replace_other"]),
                                  (r["other_pn"], r["this_pn"], r["other_can_replace_this"])):
                if verdict in ("yes", "conditional", "no"):
                    edges.append({"a": a, "b": b, "rel": "CAN_REPLACE" if verdict != "no" else "CANNOT_REPLACE",
                                  "props": {**props, "conditional": verdict == "conditional"}})
            if r.get("supersedes") in ("this", "other"):
                new, old = (r["this_pn"], r["other_pn"]) if r["supersedes"] == "this" else (r["other_pn"], r["this_pn"])
                edges.append({"a": new, "b": old, "rel": "SUPERSEDES", "props": props})
        for rel in ("CAN_REPLACE", "CANNOT_REPLACE", "SUPERSEDES"):
            s.run(f"""UNWIND $e AS e WITH e WHERE e.rel='{rel}' MATCH (a:Part {{pn:e.a}}), (b:Part {{pn:e.b}})
                MERGE (a)-[r:{rel} {{doc:e.props.doc}}]->(b) SET r += e.props""", e=edges)
        print(s.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC").data())
        print(s.run("MATCH ()-[r:CAN_REPLACE|CANNOT_REPLACE|SUPERSEDES]->() RETURN type(r) AS rel, count(*) AS n").data())
    drv.close()
    print("done.")


if __name__ == "__main__":
    main()
