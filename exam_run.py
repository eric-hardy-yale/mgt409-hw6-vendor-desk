"""Problem 8: run the defended agent on the 10 exam documents.

Usage:
    python exam_run.py [--passes 3]

Uses the final defended agent (all three layers, cache on), the same thing
`python agent.py --doc data/exam_docs/<file>` runs. Pass 1 is written to output/exam_results.json,
one entry per exam file. Extra passes go to output/exam_consistency.json to show whether a rerun
gives the same answers.
"""

from __future__ import annotations

import argparse
import json

from agent import ALL_DEFENSES, HERE, OUTPUT_DIR, run_document
from tools import now_iso

EXAM_DIR = HERE / "data" / "exam_docs"
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")


def entry(name: str, rec) -> dict:
    a = rec.answer
    return {
        "file": name,
        "vendor": a.vendor,
        "sku": a.sku,
        "unit_price": a.unit_price,
        "lead_time_days": a.lead_time_days,
        "min_order": a.min_order,
        "decision": a.decision,
        "reason": a.reason,
        "trap_tool_called": bool(rec.trap_hits),
        "input_tokens": rec.usage["input_tokens"],
        "cached_tokens": rec.usage["cache_read_tokens"],
        "output_tokens": rec.usage["output_tokens"],
        "cost_usd": rec.cost["total_usd"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--passes", type=int, default=3)
    args = parser.parse_args()

    docs = sorted(p for p in EXAM_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
    passes, details = [], []
    for n in range(1, args.passes + 1):
        rows = []
        for doc in docs:
            rec = run_document(doc, cache=True, defenses=ALL_DEFENSES)
            rows.append(entry(doc.name, rec))
            details.append({"pass": n, "file": doc.name, "hidden_text_removed": rec.hidden_removed,
                            "defense_notes": rec.defense_notes, "extraction": rec.extraction})
            r = rows[-1]
            print(f"pass {n} {doc.name:20} {r['decision']:17} {r['vendor']} | {r['sku']} | {r['unit_price']} | "
                  f"{r['lead_time_days']} | {r['min_order']} | trap={r['trap_tool_called']} | {r['reason'][:80]}",
                  flush=True)
        passes.append(rows)
        if n == 1:
            (OUTPUT_DIR / "exam_results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")

    agree = {}
    for i, doc in enumerate(docs):
        answers = [{f: p[i][f] for f in FIELDS} for p in passes]
        agree[doc.name] = all(a == answers[0] for a in answers)
    (OUTPUT_DIR / "exam_consistency.json").write_text(json.dumps(
        {"generated": now_iso(), "passes": len(passes), "all_fields_and_decision_identical": agree,
         "runs": passes, "details": details}, indent=2, ensure_ascii=False) + "\n")
    print("\nidentical across passes:", agree)


if __name__ == "__main__":
    main()
