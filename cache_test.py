"""Problem 4: run all 12 practice documents with and without prompt caching.

Usage:
    python cache_test.py

Writes output/cache_test.json: every model call from both setups (setup, document, every
token count the API reported, dollars from prices.json), plus a per-run summary scored
against data/practice_key.json. Each run is also appended to the usage log and audit trail.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent import HERE, MODEL_NAME, NO_DEFENSES, OUTPUT_DIR, load_prices, run_document
from tools import now_iso

PRACTICE_DIR = HERE / "data" / "practice_docs"
KEY = {row["file"]: row for row in json.loads((HERE / "data" / "practice_key.json").read_text())}
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")
SETUPS = [("without_cache", False), ("with_cache", True)]


def score(file: str, answer: dict) -> dict:
    key = KEY[file]
    wrong = [f for f in FIELDS if answer.get(f) != key[f]]
    return {"decision_correct": answer["decision"] == key["decision"], "fields_wrong": wrong}


def main() -> None:
    docs = sorted(PRACTICE_DIR.iterdir())
    calls, runs = [], []
    for setup, cache in SETUPS:
        for doc in docs:
            rec = run_document(doc, cache=cache, defenses=NO_DEFENSES)
            for call in rec.model_calls:
                calls.append({"setup": setup, "document": doc.name, "time": rec.time, **call})
            s = score(doc.name, rec.answer.model_dump())
            runs.append({
                "setup": setup, "document": doc.name, "time": rec.time,
                "model_calls": rec.usage["requests"], **{k: rec.usage[k] for k in rec.usage if k != "requests"},
                "cost_usd": rec.cost["total_usd"], "decision": rec.answer.decision, **s,
                "trap_calls": len(rec.trap_hits),
            })
            u = rec.usage
            print(f"{setup:14} {doc.name:32} in={u['input_tokens']:>6,} read={u['cache_read_tokens']:>6,} "
                  f"write={u['cache_write_tokens']:>6,} out={u['output_tokens']:>4} ${rec.cost['total_usd']:.6f} "
                  f"{rec.answer.decision:17} {'ok' if s['decision_correct'] else 'WRONG'} {s['fields_wrong'] or ''}",
                  flush=True)

    out = {"generated": now_iso(), "model": MODEL_NAME, "prices_per_1m": load_prices(), "calls": calls, "runs": runs}
    path = OUTPUT_DIR / "cache_test.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {len(calls)} model calls from {len(runs)} runs to {path.relative_to(HERE)}")


if __name__ == "__main__":
    main()
