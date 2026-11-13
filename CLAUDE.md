# CLAUDE.md

## What this is
PayMatch reconciles bank-statement credits to customer invoices: rules first, AI only for the unclear cases, a human review queue for anything not certain, then aging and reminder drafts.

## Commands
- Run: `DEMO_MODE=true AS_OF_DATE=2026-11-13 uvicorn app.main:app --reload`
- Test: `pytest -q` (offline; the LLM is faked with httpx.MockTransport)
- Lint: `ruff check .`
- Eval: `python -m evals.run_eval` (CI fails if any automatic match is wrong)
- Regenerate sample data: `python sample/generate.py`

## Rules that must not break
- Money is integer kobo everywhere. Never use floats for amounts.
- Only `Status.auto` and `Status.confirmed` matches change invoice balances. Balances are derived, never stored.
- Automatic matching must stay conservative: a wrong auto-match is worse than none. Run the eval after any matcher change.
- The AI may only choose invoices from the shortlist and never sets amounts; its matches are always `suggested`.
- Never chase an invoice with a payment pending review.
- In DEMO_MODE, uploads stay disabled (shared database).
- Dashboard renders data with textContent only.
