"""Three retrievers over the same Neo4j graph: vector-only (baseline), graph-only, hybrid (graph + vector)."""
from . import common as C

ANSWER_SYSTEM = """You are an aircraft maintenance information assistant. Answer ONLY from the CONTEXT.
- Part effectivity matters: a part may only be used on variants it is effective on.
- Interchangeability can be one-way, conditional (service bulletin), or limited to specific variants. State direction and conditions.
- If statements conflict (different documents or revisions), say so explicitly. Prefer the latest IPC revision over older revisions and over vendor manuals, and recommend escalating the discrepancy.
- If the context is insufficient, say so; never guess.
Return JSON: {"answer": "<concise answer>", "sources": ["<document file names you relied on>"]}"""


def _rows(drv, q, **p):
    with drv.session(database=C.NEO4J_DATABASE) as s:
        return s.run(q, **p).data()


def vector_chunks(drv, question, k=6):
    emb = C.embed([question])[0]
    return _rows(drv, "CALL db.index.vector.queryNodes('chunk_embedding', $k, $e) YIELD node, score "
                      "RETURN node.id AS id, node.doc AS doc, node.text AS text, score", k=k, e=emb)


def chunk_context(chunks):
    return "\n\n".join(f"[SOURCE: {c['doc']}]\n{c['text']}" for c in chunks)


def graph_facts(drv, pns, max_parts=6):
    out = []
    for pn in list(dict.fromkeys(pns))[:max_parts]:
        p = _rows(drv, """MATCH (p:Part {pn:$pn}) OPTIONAL MATCH (p)-[c:COMPONENT_OF]->(a:Assembly)
            OPTIONAL MATCH (p)-[:EFFECTIVE_ON]->(v:Variant)
            RETURN p.name AS name, a.name AS assembly, a.ata AS ata, a.figure AS fig, collect(DISTINCT v.name) AS variants""", pn=pn)
        if not p or p[0]["name"] is None:
            out.append(f"Part {pn}: not found in the graph.")
            continue
        p = p[0]
        out.append(f"PART {pn} | {p['name']} | assembly: {p['assembly']} (ATA {p['ata']}, {p['fig']}) | effective on: {', '.join(sorted(p['variants']))}")
        for r in _rows(drv, """MATCH (x:Part)-[r:CAN_REPLACE|CANNOT_REPLACE|SUPERSEDES]->(y:Part) WHERE $pn IN [x.pn, y.pn]
            OPTIONAL MATCH (x)-[:EFFECTIVE_ON]->(vx:Variant) WITH x,y,r, collect(DISTINCT vx.name) AS vxs
            OPTIONAL MATCH (y)-[:EFFECTIVE_ON]->(vy:Variant)
            RETURN x.pn AS x, y.pn AS y, type(r) AS rel, r.doc AS doc, r.revision AS rev, r.source_type AS st, r.condition AS cond,
                   r.only_variants AS only, vxs, collect(DISTINCT vy.name) AS vys""", pn=pn):
            extra = (f" CONDITION: {r['cond']}." if r["cond"] else "") + (f" ONLY ON: {', '.join(r['only'])}." if r["only"] else "")
            out.append(f"  [{r['doc']} | {r['st']} Rev {r['rev']}] {r['x']} {r['rel']} {r['y']}.{extra} "
                       f"(effective: {r['x']} on {', '.join(sorted(r['vxs']))}; {r['y']} on {', '.join(sorted(r['vys']))})")
        for r in _rows(drv, "MATCH (t:Procedure)-[:REQUIRES_PART]->(:Part {pn:$pn}) RETURN t.task_id AS t, t.title AS title, t.doc AS doc", pn=pn):
            out.append(f"  [{r['doc']}] required by {r['t']} - {r['title']}")
        docs = _rows(drv, "MATCH (c:Chunk)-[:MENTIONS]->(:Part {pn:$pn}) RETURN collect(DISTINCT c.doc) AS d", pn=pn)[0]["d"]
        out.append(f"  mentioned in documents: {', '.join(sorted(docs))}")
    return "\n".join(out)


def procedure_facts(drv, question):
    q = " ".join(w for w in question.replace("/", " ").replace("?", " ").replace(",", " ").split() if len(w) > 3)
    out = []
    try:
        hits = _rows(drv, "CALL db.index.fulltext.queryNodes('proc_ft', $q) YIELD node, score RETURN node.task_id AS t, node.title AS title, node.doc AS doc, node.id AS id LIMIT 2", q=q)
    except Exception:
        hits = []
    for h in hits:
        parts = _rows(drv, "MATCH (:Procedure {id:$id})-[:REQUIRES_PART]->(p:Part) RETURN p.pn AS pn, p.name AS name", id=h["id"])
        out.append(f"[{h['doc']}] {h['t']} - {h['title']}; required parts: " + "; ".join(f"{p['pn']} ({p['name']})" for p in parts))
    return "\n".join(out)


def get_context(drv, question, mode):
    pns = C.PN_RE.findall(question)
    if mode == "vector":
        return chunk_context(vector_chunks(drv, question, 6))
    if mode == "graph":
        ctx = graph_facts(drv, pns) if pns else ""
        return "\n".join(x for x in (ctx, procedure_facts(drv, question)) if x) or "(no graph facts found)"
    # hybrid: graph facts for explicit PNs, plus parts reached from semantically retrieved chunks, plus top chunks
    chunks = vector_chunks(drv, question, 5)
    if not pns:
        ids = [c["id"] for c in chunks[:3]]
        pns = [r["pn"] for r in _rows(drv, "MATCH (c:Chunk)-[:MENTIONS]->(p:Part) WHERE c.id IN $ids RETURN DISTINCT p.pn AS pn LIMIT 4", ids=ids)]
    parts = [graph_facts(drv, pns), procedure_facts(drv, question)]
    return "GRAPH FACTS:\n" + "\n".join(x for x in parts if x) + "\n\nSUPPORTING PASSAGES:\n" + chunk_context(chunks[:4])


def answer(drv, question, mode):
    ctx = get_context(drv, question, mode)
    r = C.chat_json(ANSWER_SYSTEM, f"CONTEXT:\n{ctx}\n\nQUESTION: {question}", cache=False)
    r["context"] = ctx
    return r


if __name__ == "__main__":
    import sys, json
    mode, q = sys.argv[1], " ".join(sys.argv[2:])
    d = C.get_driver()
    res = answer(d, q, mode)
    print(json.dumps({k: v for k, v in res.items() if k != "context"}, indent=2))
