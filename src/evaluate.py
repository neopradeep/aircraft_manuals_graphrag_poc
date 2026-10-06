"""Run eval/questions.json through each retriever, LLM-judge vs expected answers, report accuracy + source recall.

  python -m src.evaluate                      # all questions, all retrievers
  python -m src.evaluate --limit 10 --retrievers vector hybrid
  python -m src.evaluate --category interchangeability
"""
import argparse, json, time
from collections import defaultdict
from . import common as C
from .retrieve import answer

JUDGE = """You grade an answer to an aircraft-parts question against the expected answer.
Return JSON {"correct": true|false, "reason": "<short>"}.
Correct only if the answer reaches the same conclusion as the expected answer INCLUDING direction of interchangeability, conditions (service bulletins), variant limits,
and conflict/revision flags where the expected answer contains them. Extra detail is fine; contradicting or omitting a key condition is incorrect."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrievers", nargs="+", default=["vector", "graph", "hybrid"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    a = ap.parse_args()
    qs = json.loads((C.ROOT / "eval/questions.json").read_text())
    if a.category:
        qs = [q for q in qs if q["category"] == a.category]
    if a.limit:
        qs = qs[:a.limit]
    drv = C.get_driver()
    results = []
    for q in qs:
        for mode in a.retrievers:
            t0 = time.time()
            r = answer(drv, q["question"], mode)
            lat = time.time() - t0
            j = C.chat_json(JUDGE, f"QUESTION: {q['question']}\nEXPECTED: {q['expected_answer']}\nANSWER: {r['answer']}", cache=False)
            cited = set(r.get("sources") or [])
            exp = set(q["expected_sources"])
            results.append({"id": q["id"], "category": q["category"], "retriever": mode, "correct": bool(j["correct"]),
                            "reason": j.get("reason"), "source_recall": len(exp & cited) / len(exp) if exp else 1.0,
                            "latency_s": round(lat, 2), "answer": r["answer"], "expected": q["expected_answer"],
                            "cited": sorted(cited)})
            print(f"{q['id']} {q['category']:<22} {mode:<7} {'OK ' if j['correct'] else 'BAD'} recall={results[-1]['source_recall']:.2f}")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (C.ROOT / "results" / f"run-{stamp}.json").write_text(json.dumps(results, indent=2))
    agg = defaultdict(lambda: defaultdict(list))
    for r in results:
        agg[r["category"]][r["retriever"]].append(r)
        agg["ALL"][r["retriever"]].append(r)
    lines = ["| category | retriever | n | accuracy | source recall | avg latency (s) |", "|---|---|---|---|---|---|"]
    for cat in sorted(agg, key=lambda c: (c == "ALL", c)):
        for mode in a.retrievers:
            rs = agg[cat][mode]
            if rs:
                lines.append(f"| {cat} | {mode} | {len(rs)} | {sum(x['correct'] for x in rs) / len(rs):.0%} | "
                             f"{sum(x['source_recall'] for x in rs) / len(rs):.0%} | {sum(x['latency_s'] for x in rs) / len(rs):.1f} |")
    md = "\n".join(lines)
    (C.ROOT / "results" / f"summary-{stamp}.md").write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
