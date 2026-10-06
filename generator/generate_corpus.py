#!/usr/bin/env python3
"""
Synthetic aircraft-maintenance manual corpus generator.
ALL DATA IS FICTIONAL - for learning/experimentation only, not for any real maintenance use.

Produces (deterministic for a given --seed):
  corpus/html/    IPC (parts catalog), AMM (procedures), CMM (vendor component) manuals
  corpus/figures/ SVG exploded-view figures referenced by the IPC
  ground_truth/   parts, assemblies, interchange records, tasks, conflicts (JSON)
  eval/questions.json  question + expected answer + expected sources
"""
import argparse, json, random
from pathlib import Path
from html import escape

FLEETS = {
    "B737": {"label": "737 family", "style": "boeing",
             "variants": {"A": "737-700", "B": "737-800", "C": "737-MAX8"}},
    "A320": {"label": "A320 family", "style": "airbus",
             "variants": {"A": "A320ceo", "B": "A320neo", "C": "A321neo"}},
}
CHAPTERS = {
    "B737": {
        "21": ("AIR CONDITIONING", ["AIR CONDITIONING PACK", "PACK TEMPERATURE CONTROL", "RECIRCULATION FAN", "CABIN PRESSURE OUTFLOW VALVE"]),
        "24": ("ELECTRICAL POWER", ["GENERATOR DRIVE", "GENERATOR CONTROL UNIT", "MAIN BATTERY INSTALLATION", "EXTERNAL POWER RECEPTACLE"]),
        "27": ("FLIGHT CONTROLS", ["AILERON POWER CONTROL UNIT", "ELEVATOR FEEL COMPUTER", "FLAP DRIVE UNIT", "SPOILER ACTUATOR"]),
        "29": ("HYDRAULIC POWER", ["ENGINE DRIVEN HYDRAULIC PUMP", "HYDRAULIC RESERVOIR", "ELECTRIC MOTOR DRIVEN PUMP", "HYDRAULIC FILTER MODULE"]),
        "32": ("LANDING GEAR", ["MAIN GEAR SHOCK STRUT", "NOSE GEAR STEERING ACTUATOR", "BRAKE ASSEMBLY", "WHEEL AND TIRE ASSEMBLY"]),
        "36": ("PNEUMATIC", ["BLEED AIR PRESSURE REGULATOR", "PRECOOLER", "BLEED DUCT COUPLING", "ISOLATION VALVE"]),
        "49": ("AUXILIARY POWER UNIT", ["APU FUEL CONTROL UNIT", "APU STARTER", "APU INLET DOOR ACTUATOR", "APU OIL COOLER"]),
        "73": ("ENGINE FUEL AND CONTROL", ["FUEL PUMP AND FILTER", "HYDROMECHANICAL UNIT", "FUEL NOZZLE", "ENGINE FUEL HEATER"]),
        "78": ("EXHAUST", ["THRUST REVERSER ACTUATOR", "THRUST REVERSER SLEEVE", "EXHAUST NOZZLE", "REVERSER HYDRAULIC CONTROL"]),
        "80": ("STARTING", ["ENGINE STARTER", "STARTER AIR VALVE", "START CONTROL RELAY", "STARTER DUCT"]),
    },
    "A320": {
        "21": ("AIR CONDITIONING", ["PACK FLOW CONTROL VALVE", "AVIONICS VENTILATION FAN", "TRIM AIR PRESSURE REGULATOR"]),
        "24": ("ELECTRICAL POWER", ["IDG ASSEMBLY", "BUS TIE CONTACTOR", "TRANSFORMER RECTIFIER UNIT"]),
        "27": ("FLIGHT CONTROLS", ["SLAT DRIVE UNIT", "ELEVATOR SERVO ACTUATOR", "SPOILER SERVO ACTUATOR"]),
        "29": ("HYDRAULIC POWER", ["GREEN SYSTEM ENGINE PUMP", "YELLOW SYSTEM ELECTRIC PUMP", "HYDRAULIC FIREWALL SHUTOFF VALVE"]),
        "32": ("LANDING GEAR", ["MAIN GEAR RETRACTION ACTUATOR", "NOSE WHEEL STEERING SERVO", "AUTOBRAKE VALVE ASSEMBLY"]),
        "36": ("PNEUMATIC", ["ENGINE BLEED VALVE", "BLEED MONITORING COMPUTER", "HP BLEED VALVE"]),
        "73": ("ENGINE FUEL AND CONTROL", ["FUEL METERING UNIT", "FUEL FILTER HOUSING", "FUEL INJECTOR MANIFOLD"]),
    },
}
KINDS = ["VALVE - CHECK", "VALVE - SHUTOFF", "SENSOR - TEMPERATURE", "SENSOR - PRESSURE", "FILTER ELEMENT",
         "SEAL - O-RING", "SEAL - FLANGE", "CLAMP - V-BAND", "BRACKET - MOUNTING", "DUCT - FLEXIBLE", "ACTUATOR - LINEAR",
         "PUMP - TRANSFER", "SWITCH - PRESSURE", "CONNECTOR - ELECTRICAL", "BOLT", "NUT - SELF-LOCKING", "WASHER - LOCK",
         "GASKET", "HOSE ASSEMBLY", "FITTING - ELBOW", "SOLENOID", "COUPLING - QUICK DISCONNECT"]
VENDOR_KINDS = ("VALVE", "PUMP", "ACTUATOR", "SENSOR", "SWITCH", "SOLENOID")
MFRS = ["Halvorsen Aerospace", "Kestrel Dynamics", "Brightwater Controls", "Norden Fluid Systems", "Pelican Aero Components", "Tamarack Precision"]
SBS = ["SB {ch}-1042", "SB {ch}-2217", "SB {ch}-0388", "SB {ch}-3109"]
PHRASE = {
    "two_way": ["ALTERNATE FOR {a}. PARTS ARE INTERCHANGEABLE.", "INTERCHANGEABLE WITH {a} (TWO-WAY)."],
    "supersede": ["SUPERSEDES {a}. {a} IS NOT INTERCHANGEABLE WITH THIS PART (ONE-WAY).",
                  "REPLACES {a}. THIS PART MAY REPLACE {a}; {a} MAY NOT BE USED TO REPLACE THIS PART."],
    "conditional": ["ALTERNATE FOR {a} AFTER INCORPORATION OF {sb}.", "INTERCHANGEABLE WITH {a} WHEN {sb} IS EMBODIED."],
    "variant_limited": ["ALTERNATE FOR {a} ON {vars} ONLY.", "INTERCHANGEABLE WITH {a} - {vars} ONLY."],
}
CSS = """body{font-family:Arial,sans-serif;max-width:980px;margin:24px auto;color:#222}
.banner{background:#fff3cd;border:1px solid #e0c36a;padding:6px 10px;font-size:12px}
table{border-collapse:collapse;width:100%;margin:10px 0}th,td{border:1px solid #999;padding:4px 6px;font-size:13px;text-align:left}
th{background:#eee}tr.note td{font-style:italic;background:#fafafa}.warning{border-left:4px solid #c00;background:#fdecec;padding:6px 10px}
.caution{border-left:4px solid #e90;background:#fff6e6;padding:6px 10px}figure{margin:12px 0}figcaption{font-size:12px;color:#555}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = Path(args.out)
    for d in ("corpus/html", "corpus/figures", "ground_truth", "eval"):
        (out / d).mkdir(parents=True, exist_ok=True)

    used_pn = set()

    def mk_pn(style):
        while True:
            if style == "boeing":
                pn = f"{rng.choice([60, 65, 69, 162, 285])}-{rng.randint(10000, 99999)}-{rng.randint(1, 29):02d}"
            else:
                pn = f"D{rng.randint(2000000, 2999999)}{rng.randint(0, 99):02d}00"
            if pn not in used_pn:
                used_pn.add(pn)
                return pn

    parts, assemblies, records = {}, {}, []
    for fleet, fl in FLEETS.items():
        codes = list(fl["variants"])
        for ch, (chname, assys) in CHAPTERS[fleet].items():
            for i, aname in enumerate(assys):
                ata = f"{ch}-{11 + i * 10}-00"
                aid = f"{fleet}-{ata}"
                assemblies[aid] = {"id": aid, "fleet": fleet, "chapter": ch, "chapter_name": chname, "ata": ata,
                                   "name": aname, "figure": f"{ata} FIG 1", "parts": []}
                kinds = rng.sample(KINDS, rng.randint(7, 9))
                for j, kind in enumerate(kinds, 1):
                    r = rng.random()
                    eff = codes if r < .6 else ["C"] if r < .75 else ["A", "B"] if r < .85 else ["B", "C"] if r < .95 else ["A"]
                    pn = mk_pn(fl["style"])
                    parts[pn] = {"pn": pn, "name": f"{kind}, {aname}", "kind": kind, "fleet": fleet, "assembly_id": aid,
                                 "ata": ata, "item": str(j), "qty": rng.choice([1, 1, 1, 2, 4]), "eff": eff,
                                 "mfr": rng.choice(MFRS), "status": "ACTIVE", "superseded_by": None}
                    assemblies[aid]["parts"].append(pn)
                # interchange counterparts
                for pn in list(assemblies[aid]["parts"]):
                    if rng.random() > .3:
                        continue
                    a = parts[pn]
                    typ = rng.choices(["two_way", "supersede", "conditional", "variant_limited"], [3, 3, 2, 2])[0]
                    if typ == "variant_limited":
                        if set(a["eff"]) == set(codes):
                            ceff = rng.choice([["C"], ["A"], ["B", "C"]])
                        elif a["eff"] == ["A", "B"]:
                            ceff = ["B", "C"]
                        elif a["eff"] == ["B", "C"]:
                            ceff = ["A", "B"]
                        else:
                            typ, ceff = "two_way", a["eff"]
                    else:
                        ceff = a["eff"]
                    bpn = mk_pn(fl["style"])
                    parts[bpn] = {"pn": bpn, "name": a["name"], "kind": a["kind"], "fleet": fleet, "assembly_id": aid,
                                  "ata": ata, "item": a["item"] + "A", "qty": a["qty"], "eff": ceff,
                                  "mfr": rng.choice(MFRS), "status": "ACTIVE", "superseded_by": None}
                    assemblies[aid]["parts"].append(bpn)
                    sb = rng.choice(SBS).format(ch=ch) if typ == "conditional" else None
                    overlap = sorted(set(a["eff"]) & set(ceff))
                    if typ == "supersede":
                        a["status"], a["superseded_by"] = "SUPERSEDED", bpn
                    records.append({"id": f"IC-{len(records) + 1:03d}", "fleet": fleet, "a": pn, "b": bpn, "type": typ,
                                    "sb": sb, "valid_variants": overlap, "ata": ata, "assembly_id": aid,
                                    "phrase_idx": rng.randrange(2)})

    mentions = {pn: set() for pn in parts}
    veff = lambda fleet, codes: ", ".join(FLEETS[fleet]["variants"][c] for c in codes)

    def note_text(rec, rev14=False):
        fleet = rec["fleet"]
        typ = "two_way" if rev14 else rec["type"]
        t = PHRASE[typ][rec["phrase_idx"] % len(PHRASE[typ])]
        return t.format(a=rec["a"], b=rec["b"], sb=rec["sb"], vars=veff(fleet, rec["valid_variants"]).upper())

    # ---------------- figures ----------------
    for aid, asy in assemblies.items():
        items = [parts[p]["item"] for p in asy["parts"]]
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="560" height="260" viewBox="0 0 560 260">',
               '<rect width="560" height="260" fill="#fff" stroke="#999"/>',
               f'<text x="12" y="22" font-size="14" font-family="Arial">{escape(asy["name"])} - {asy["figure"]} (SYNTHETIC)</text>',
               '<rect x="200" y="90" width="160" height="90" fill="#ddd" stroke="#555"/>']
        for k, it in enumerate(items):
            x, y = 40 + (k % 8) * 62, 50 + (k // 8) * 160 + (k % 2) * 40
            svg.append(f'<line x1="{x}" y1="{y}" x2="280" y2="135" stroke="#aaa"/><circle cx="{x}" cy="{y}" r="14" fill="#fff" stroke="#333"/>'
                       f'<text x="{x}" y="{y + 4}" font-size="11" text-anchor="middle" font-family="Arial">{it}</text>')
        svg.append("</svg>")
        (out / "corpus/figures" / f"{aid}.svg").write_text("\n".join(svg))

    def page(title, doc_id, body, meta):
        return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title><style>{CSS}</style></head>'
                f'<body data-doc-id="{doc_id}"><div class="banner">SYNTHETIC TRAINING DATA - FICTIONAL - NOT FOR AIRCRAFT MAINTENANCE USE</div>'
                f'<h1>{escape(title)}</h1><p>{meta}</p>{body}</body></html>')

    docs = {}
    rec_by_aid = {}
    for r in records:
        rec_by_aid.setdefault(r["assembly_id"], []).append(r)
    rev14_chapters = {("B737", "29"), ("B737", "32")}
    rev14_recs = set()
    for (fleet, ch) in rev14_chapters:
        cands = [r for r in records if r["fleet"] == fleet and r["ata"].startswith(ch) and r["type"] != "two_way"]
        for r in rng.sample(cands, min(2, len(cands))):
            rev14_recs.add(r["id"])

    def render_ipc(fleet, ch, rev):
        chname, assys = CHAPTERS[fleet][ch]
        legend = "".join(f"<tr><td>{c}</td><td>{n}</td></tr>" for c, n in FLEETS[fleet]["variants"].items())
        body = f'<h2>Effectivity Legend</h2><table><tr><th>CODE</th><th>AIRCRAFT</th></tr>{legend}</table>'
        fname = f"IPC_{fleet}_ATA{ch}_REV{rev}.html"
        for i, aname in enumerate(assys):
            aid = f"{fleet}-{ch}-{11 + i * 10}-00"
            asy = assemblies[aid]
            body += f'<section data-ata="{asy["ata"]}"><h2>{asy["ata"]} {escape(aname)}</h2>'
            body += (f'<figure><img src="../figures/{aid}.svg" alt="{escape(aname)}"><figcaption>FIGURE {asy["figure"]} - {escape(aname)}</figcaption></figure>')
            body += "<table><tr><th>FIG ITEM</th><th>PART NUMBER</th><th>NOMENCLATURE</th><th>EFFECT</th><th>UPA</th></tr>"
            base_items = [p for p in asy["parts"] if not parts[p]["item"].endswith("A")]
            for pn in base_items:
                p = parts[pn]
                eff = "ALL" if set(p["eff"]) == set(FLEETS[fleet]["variants"]) else " ".join(p["eff"])
                body += f'<tr><td>{p["item"]}</td><td>{pn}</td><td>{escape(p["name"])}</td><td>{eff}</td><td>{p["qty"]}</td></tr>'
                mentions[pn].add(fname)
                if p["superseded_by"]:
                    body += f'<tr class="note"><td></td><td colspan="4">SUPERSEDED BY {p["superseded_by"]}</td></tr>'
                for rec in [r for r in rec_by_aid.get(aid, []) if r["a"] == pn]:
                    q = parts[rec["b"]]
                    qeff = "ALL" if set(q["eff"]) == set(FLEETS[fleet]["variants"]) else " ".join(q["eff"])
                    body += f'<tr><td>{q["item"]}</td><td>{rec["b"]}</td><td>{escape(q["name"])}</td><td>{qeff}</td><td>{q["qty"]}</td></tr>'
                    body += f'<tr class="note"><td></td><td colspan="4">{note_text(rec, rev14=(rev == 14 and rec["id"] in rev14_recs))}</td></tr>'
                    mentions[rec["b"]].add(fname)
            body += "</table></section>"
        docs[fname] = page(f"ILLUSTRATED PARTS CATALOG - {FLEETS[fleet]['label'].upper()} - ATA {ch} {chname}", fname, body,
                           f"Document type: IPC | Revision: {rev} | Fleet: {fleet}")
        return fname

    ipc_files = {}
    for fleet in FLEETS:
        for ch in CHAPTERS[fleet]:
            ipc_files[(fleet, ch)] = render_ipc(fleet, ch, 15)
    for (fleet, ch) in rev14_chapters:
        render_ipc(fleet, ch, 14)

    # ---------------- AMM tasks ----------------
    tasks = []
    for aid, asy in assemblies.items():
        if rng.random() > .55:
            continue
        fleet = asy["fleet"]
        base = [p for p in asy["parts"] if not parts[p]["item"].endswith("A")]
        main_p = next((p for p in base if parts[p]["kind"].startswith(VENDOR_KINDS)), base[0])
        cons = rng.sample([p for p in base if p != main_p], 3)
        tid = f"TASK {asy['ata']}-400-801"
        fname = f"AMM_{fleet}_ATA{asy['chapter']}_{asy['ata']}.html"
        rows = "".join(f'<tr><td>{p}</td><td>{escape(parts[p]["name"])}</td><td>{parts[p]["qty"]}</td><td>{asy["figure"]}</td></tr>' for p in [main_p] + cons)
        steps = "".join(f"<li>{s}</li>" for s in [
            "Make sure the aircraft is safe for maintenance and the applicable circuit breakers are open and tagged.",
            f"Release system pressure and disconnect the lines from the {escape(asy['name'].lower())}.",
            f"Remove the attaching hardware and remove the {escape(parts[main_p]['name'])}.",
            "Install new seals. Lubricate seals with the approved fluid before assembly.",
            f"Install the replacement {escape(parts[main_p]['name'])} and torque the attaching hardware.",
            "Do the operational test. Examine the connections for leaks."])
        body = (f'<section data-ata="{asy["ata"]}"><h2>{tid} - {escape(asy["name"])} - Removal/Installation</h2>'
                f'<h3>1. Reason for the Job</h3><p>Replacement of the {escape(asy["name"].lower())} as a result of a fault isolation finding.</p>'
                f'<h3>2. Job Set-up Information</h3><p>Parts required (see IPC {asy["figure"]} for effectivity and approved alternates):</p>'
                f'<table><tr><th>PART NUMBER</th><th>NOMENCLATURE</th><th>QTY</th><th>IPC REF</th></tr>{rows}</table>'
                f'<div class="warning"><b>WARNING:</b> Do not work on pressurized lines. Injury to persons can occur.</div>'
                f'<div class="caution"><b>CAUTION:</b> Install protective caps on open lines to prevent contamination.</div>'
                f'<h3>3. Procedure</h3><ol>{steps}</ol><h3>4. Close-up</h3><p>Remove tools and tags. Close access panels.</p></section>')
        docs[fname] = page(f"AIRCRAFT MAINTENANCE MANUAL - {FLEETS[fleet]['label'].upper()} - {asy['ata']} {asy['name']}", fname, body,
                           f"Document type: AMM | Fleet: {fleet} | Revision: 15")
        tasks.append({"task_id": tid, "doc": fname, "assembly_id": aid, "title": f"{asy['name']} - Removal/Installation",
                      "ata": asy["ata"], "fleet": fleet, "main_part": main_p, "parts": [main_p] + cons})
        for p in [main_p] + cons:
            mentions[p].add(fname)

    # ---------------- CMM ----------------
    vend_recs = [r for r in records if parts[r["a"]]["kind"].startswith(VENDOR_KINDS)]
    rng.shuffle(vend_recs)
    vend_recs = vend_recs[:14]
    nonclean = [r for r in vend_recs if r["type"] != "two_way"]
    conflicts = []
    conflict_ids = {r["id"] for r in nonclean[:3]}
    for n, rec in enumerate(vend_recs, 1):
        a, b = parts[rec["a"]], parts[rec["b"]]
        fname = f"CMM_{a['mfr'].split()[0].upper()}_{n:02d}_{rec['a']}.html"
        if rec["id"] in conflict_ids:
            interch = f"Part number {rec['b']} is fully interchangeable with part number {rec['a']} with no restrictions."
            conflicts.append({"record_id": rec["id"], "a": rec["a"], "b": rec["b"], "ipc_type": rec["type"], "cmm_doc": fname,
                              "ipc_doc": ipc_files[(rec["fleet"], rec["ata"].split("-")[0])],
                              "cmm_statement": interch, "ipc_statement": note_text(rec)})
        else:
            interch = {"two_way": f"Part number {rec['b']} is interchangeable with part number {rec['a']} (two-way).",
                       "supersede": f"Part number {rec['b']} supersedes {rec['a']}. {rec['a']} is not a permitted replacement for {rec['b']}.",
                       "conditional": f"Part number {rec['b']} is interchangeable with {rec['a']} only after {rec['sb']} is embodied.",
                       "variant_limited": f"Part number {rec['b']} is interchangeable with {rec['a']} on {veff(rec['fleet'], rec['valid_variants'])} only."}[rec["type"]]
        body = (f'<section><h2>1. Description</h2><p>This manual covers the {escape(a["name"])}, part number {rec["a"]}, manufactured by {a["mfr"]}.</p></section>'
                f'<section><h2>2. Testing and Fault Isolation</h2><p>Do a bench functional test per the test setup. Pressure drop must not exceed the limit in Table 101.</p>'
                f'<table><tr><th>TEST</th><th>LIMIT</th></tr><tr><td>Proof pressure</td><td>{rng.randint(20, 60) * 100} psi</td></tr><tr><td>Internal leakage</td><td>{rng.randint(2, 9)} cc/min max</td></tr></table></section>'
                f'<section data-section="interchangeability"><h2>3. Interchangeability</h2><p>{interch}</p></section>'
                f'<section><h2>4. Repair</h2><p>Replace seals and filters at each shop visit. Refer to the Illustrated Parts List for ordering information.</p></section>')
        docs[fname] = page(f"COMPONENT MAINTENANCE MANUAL - {a['name']}", fname, body, f"Document type: CMM | Vendor: {a['mfr']} | Part: {rec['a']}")
        mentions[rec["a"]].add(fname)
        mentions[rec["b"]].add(fname)

    for fname, h in docs.items():
        (out / "corpus/html" / fname).write_text(h)

    # ---------------- ground truth ----------------
    manuals = [{"file": f, "type": f.split("_")[0], "revision": (14 if "REV14" in f else 15)} for f in sorted(docs)]
    for name, obj in (("parts", list(parts.values())), ("assemblies", list(assemblies.values())), ("interchange", records),
                      ("tasks", tasks), ("conflicts", conflicts), ("manuals", manuals),
                      ("rev14_discrepancies", [{"record_id": r["id"], "rev14_statement": note_text(r, True), "rev15_statement": note_text(r),
                                                "doc14": f"IPC_{r['fleet']}_ATA{r['ata'].split('-')[0]}_REV14.html",
                                                "doc15": f"IPC_{r['fleet']}_ATA{r['ata'].split('-')[0]}_REV15.html"}
                                               for r in records if r["id"] in rev14_recs])):
        (out / "ground_truth" / f"{name}.json").write_text(json.dumps(obj, indent=2, default=list))

    # ---------------- questions ----------------
    def vname(fleet, c): return FLEETS[fleet]["variants"][c]

    def replace(rec, direction, v):
        """direction 'b_for_a' = b replaces a. returns (verdict, text)"""
        a, b = rec["a"], rec["b"]
        inst, cand = (a, b) if direction == "b_for_a" else (b, a)
        fleet = rec["fleet"]
        if v not in parts[inst]["eff"] or v not in parts[cand]["eff"]:
            return "no", f"No - on the {vname(fleet, v)} both parts must be effective; {cand if v not in parts[cand]['eff'] else inst} is not effective on this variant."
        t = rec["type"]
        if t == "two_way": return "yes", f"Yes - {cand} is interchangeable with {inst} (two-way)."
        if t == "supersede":
            return ("yes", f"Yes - {b} supersedes {a} and may replace it.") if direction == "b_for_a" else ("no", f"No - {a} is superseded by {b}; the old part may not be used to replace the new part.")
        if t == "conditional": return "conditional", f"Yes, but only after {rec['sb']} is embodied."
        return "yes", f"Yes - interchangeable on {veff(fleet, rec['valid_variants'])} only, and this is one of those variants."

    Q = []
    def add(cat, q, ans, srcs, diff="medium", extra=None):
        d = {"id": f"Q{len(Q) + 1:03d}", "category": cat, "difficulty": diff, "question": q, "expected_answer": ans,
             "expected_sources": sorted(set(srcs))}
        if extra: d.update(extra)
        Q.append(d)

    ipc_of = lambda r: ipc_files[(r["fleet"], r["ata"].split("-")[0])]
    sample = lambda seq, n: rng.sample(seq, min(n, len(seq)))
    for rec in sample(records, 14):
        direction = rng.choice(["b_for_a", "a_for_b"])
        v = rng.choice(list(FLEETS[rec["fleet"]]["variants"]))
        inst, cand = (rec["a"], rec["b"]) if direction == "b_for_a" else (rec["b"], rec["a"])
        verdict, txt = replace(rec, direction, v)
        add("interchangeability", f"The {vname(rec['fleet'], v)} needs part {inst} and none is in stock. Can part {cand} be installed instead?",
            txt, [ipc_of(rec)], "medium", {"verdict": verdict, "record_id": rec["id"]})
    for rec in sample([r for r in records if r["type"] == "supersede"], 6):
        v = rng.choice(rec["valid_variants"])
        verdict, txt = replace(rec, "a_for_b", v)
        add("one_way_supersession", f"Part {rec['a']} is on the shelf. Can it be used to replace part {rec['b']} on a {vname(rec['fleet'], v)}?",
            txt, [ipc_of(rec)], "hard", {"verdict": verdict, "record_id": rec["id"]})
    for p in sample(list(parts.values()), 10):
        v = rng.choice(list(FLEETS[p["fleet"]]["variants"]))
        ok = v in p["eff"]
        add("effectivity", f"Is part {p['pn']} effective on the {vname(p['fleet'], v)}?",
            f"{'Yes' if ok else 'No'} - effective on: {veff(p['fleet'], p['eff'])}.", [ipc_files[(p['fleet'], p['ata'].split('-')[0])]], "easy", {"verdict": "yes" if ok else "no"})
    for p in sample(list(parts.values()), 6):
        a = assemblies[p["assembly_id"]]
        add("assembly_ata", f"Which assembly and ATA section is part {p['pn']} listed under?",
            f"{a['name']}, ATA {a['ata']} ({a['figure']}).", [ipc_files[(p['fleet'], p['ata'].split('-')[0])]], "easy")
    for t in sample(tasks, 8):
        add("procedure_lookup", f"What AMM task covers removal/installation of the {assemblies[t['assembly_id']]['name']} on the {FLEETS[t['fleet']]['label']}, and which parts does it require?",
            f"{t['task_id']}; parts: {', '.join(t['parts'])}.", [t["doc"]], "medium", {"expected_parts": t["parts"]})
    pr = {}
    for r in records:
        pr.setdefault(r["a"], []).append(r); pr.setdefault(r["b"], []).append(r)
    for pn in sample([p for p in pr if p in parts], 6):
        p = parts[pn]; v = rng.choice(p["eff"])
        lines = []
        for rec in pr[pn]:
            other = rec["b"] if rec["a"] == pn else rec["a"]
            direction = "b_for_a" if rec["a"] == pn else "a_for_b"
            verdict, txt = replace(rec, direction, v)
            lines.append(f"{other}: {txt}")
        add("alternates_multihop", f"A {vname(p['fleet'], v)} needs part {pn} and none is in stock. List every approved alternate valid for this aircraft and any conditions.",
            " | ".join(lines), [ipc_of(pr[pn][0])] , "hard", {"record_ids": [r["id"] for r in pr[pn]]})
    for c in conflicts:
        add("cross_doc_conflict", f"The CMM for part {c['a']} says {c['b']} is interchangeable with no restrictions. Does the IPC agree?",
            f"Conflict - IPC says: {c['ipc_statement']} Follow the IPC and escalate the discrepancy; do not rely on the CMM statement.",
            [c["cmm_doc"], c["ipc_doc"]], "hard", {"record_id": c["record_id"]})
    for d in [r for r in records if r["id"] in rev14_recs]:
        add("revision_conflict", f"What is the current interchangeability statement for {d['a']} / {d['b']}, and did it change between IPC Rev 14 and Rev 15?",
            f"Rev 15 (current): {note_text(d)} Rev 14 said: {note_text(d, True)}",
            [f"IPC_{d['fleet']}_ATA{d['ata'].split('-')[0]}_REV14.html", ipc_of(d)], "hard", {"record_id": d["id"]})
    for pn in sample([p for p in parts if len(mentions[p]) >= 2], 4):
        add("cross_doc_mentions", f"Which manuals reference part {pn}?", ", ".join(sorted(mentions[pn])), mentions[pn], "medium")
    (out / "eval/questions.json").write_text(json.dumps(Q, indent=2))

    print(f"parts={len(parts)} assemblies={len(assemblies)} interchange_records={len(records)} tasks={len(tasks)} "
          f"docs={len(docs)} conflicts={len(conflicts)} rev14_diffs={len(rev14_recs)} questions={len(Q)}")


if __name__ == "__main__":
    main()
