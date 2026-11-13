"""Measure the matcher against the labelled sample statement.

    python -m evals.run_eval                 # rules only
    GROQ_API_KEY=... python -m evals.run_eval --ai

What matters, in order:
  1. Auto precision: of the payments applied with no human check, how many were right?
     This must be 100%. A wrong auto-match marks an unpaid invoice as paid.
  2. Correct: payments matched to exactly the right invoices (auto + suggestions),
     plus non-customer credits correctly left unmatched.
  3. Automation rate: share of all credits handled with no human at all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.ai import LLM, AIMatcher
from app.importers import read_bank_statement, read_invoices
from app.matcher import Ledger, reconcile
from app.models import Status

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", action="store_true", help="use the AI for payments the rules can't place")
    ap.add_argument("--min-auto-precision", type=float, default=1.0)
    args = ap.parse_args()

    customers, invoices = read_invoices((ROOT / "sample" / "invoices.csv").read_text())
    txns = read_bank_statement((ROOT / "sample" / "bank_statement.csv").read_text())
    labels = {row["narration"]: row for row in json.loads((ROOT / "evals" / "labels.json").read_text())}
    ledger = Ledger({c.id: c for c in customers}, {i.number: i for i in invoices})
    ai = None
    if args.ai:
        key = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY")
        if not key:
            sys.exit("Set GROQ_API_KEY to use --ai")
        ai = AIMatcher(LLM(key, os.getenv("LLM_PROVIDER", "groq"), os.getenv("LLM_MODEL", "")), ledger.remaining)

    results = reconcile(txns, ledger, ai=ai)
    by_id = {t.id: t for t in txns}
    auto = auto_ok = correct = 0
    for m in results:
        t = by_id[m.transaction_id]
        label = labels[t.narration]
        expected, got = sorted(label["expected"]), sorted(m.invoice_numbers)
        ok = expected == got
        correct += ok
        if m.status is Status.auto:
            auto += 1
            auto_ok += ok
        mark = "✓" if ok else "✗"
        print(f"{mark} {m.status.value:<10} {(m.method.value if m.method else '-'):<14} got={','.join(got) or '-':<16} "
              f"want={','.join(expected) or '-':<16} {label['situation']}")

    n = len(results)
    auto_precision = auto_ok / auto if auto else 1.0
    print("\n=== Results ===")
    print(f"engine:            {'rules + ' + ai.name if ai else 'rules only'}")
    print(f"correct:           {correct}/{n} = {correct / n:.0%}")
    print(f"auto-applied:      {auto}/{n} = {auto / n:.0%} of payments needed no human")
    print(f"auto precision:    {auto_ok}/{auto} = {auto_precision:.0%} (must be 100%)")
    print(f"sent for review:   {sum(m.status is Status.suggested for m in results)}")
    print(f"left unmatched:    {sum(m.status is Status.unmatched for m in results)}")
    return 1 if auto_precision < args.min_auto_precision else 0


if __name__ == "__main__":
    sys.exit(main())
