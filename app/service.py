"""Business operations: import, match, review, report. The API layer just calls these."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .ai import AIMatcher, Reminder, draft_reminder
from .importers import read_bank_statement, read_invoices
from .matcher import Ledger, allocate, reconcile
from .models import Match, Method, Status
from .money import naira
from .store import Store

SAMPLE = Path(__file__).resolve().parent.parent / "sample"
AGING_BUCKETS = [("Not yet due", None, 0), ("1-30 days", 1, 30), ("31-60 days", 31, 60),
                 ("61-90 days", 61, 90), ("90+ days", 91, None)]


def _bucket(days_overdue: int) -> str:
    for name, lo, hi in AGING_BUCKETS:
        if lo is None and days_overdue <= hi:
            return name
        if lo is not None and days_overdue >= lo and (hi is None or days_overdue <= hi):
            return name
    return AGING_BUCKETS[-1][0]


class ReviewError(ValueError):
    pass


class PayMatch:
    def __init__(self, store: Store, llm=None, as_of: date | None = None,
                 business: str = "Kola Foods Distribution Ltd"):
        self.store = store
        self.llm = llm
        self._as_of = as_of
        self.business = business

    @property
    def as_of(self) -> date:
        return self._as_of or date.today()

    # ------------------------------------------------------------------ import + match
    def _ledger(self) -> Ledger:
        """Open balances, with pending suggestions already reserved."""
        ledger = Ledger(self.store.customers(), self.store.invoices())
        for m in self.store.matches().values():
            if m.status is Status.suggested:
                ledger.reserve(m)
        return ledger

    def import_invoices(self, text: str) -> dict:
        customers, invoices = read_invoices(text)
        self.store.upsert_customers(customers)
        self.store.upsert_invoices(invoices)
        rematched = self.rematch_unmatched()
        return {"customers": len(customers), "invoices": len(invoices), "rematched": rematched}

    def import_statement(self, text: str) -> dict:
        txns = read_bank_statement(text)
        new = self.store.add_transactions(txns)
        ledger = self._ledger()
        ai = AIMatcher(self.llm, ledger.remaining) if self.llm else None
        matches = reconcile(new, ledger, ai=ai)
        self.store.save_matches(matches)
        by_status: dict[str, int] = {}
        for m in matches:
            by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
        return {"credits_read": len(txns), "new": len(new), "duplicates_skipped": len(txns) - len(new),
                "results": by_status}

    def rematch_unmatched(self) -> int:
        """After new invoices arrive, payments that matched nothing may now match something."""
        txns = self.store.transactions()
        waiting = [txns[tid] for tid, m in self.store.matches().items() if m.status is Status.unmatched]
        if not waiting:
            return 0
        ledger = self._ledger()
        ai = AIMatcher(self.llm, ledger.remaining) if self.llm else None
        results = [m for m in reconcile(waiting, ledger, ai=ai) if m.status is not Status.unmatched]
        self.store.save_matches(results)
        return len(results)

    def load_sample(self) -> dict:
        self.store.reset()
        inv = self.import_invoices((SAMPLE / "invoices.csv").read_text())
        stm = self.import_statement((SAMPLE / "bank_statement.csv").read_text())
        return {"invoices": inv, "statement": stm}

    # ------------------------------------------------------------------ review queue
    def _get(self, tid: str) -> Match:
        m = self.store.matches().get(tid)
        if not m:
            raise ReviewError("No such transaction")
        return m

    def confirm(self, tid: str) -> Match:
        m = self._get(tid)
        if m.status is not Status.suggested:
            raise ReviewError(f"Only suggestions can be confirmed (this one is {m.status.value})")
        m.status = Status.confirmed
        self.store.save_matches([m])
        return m

    def reject(self, tid: str) -> Match:
        m = self._get(tid)
        if m.status not in (Status.suggested, Status.auto):
            raise ReviewError(f"Can't reject a {m.status.value} match")
        txn = self.store.transactions()[tid]
        rejected = Match(transaction_id=tid, status=Status.unmatched, unapplied=txn.amount,
                         reason=f"Rejected by reviewer (was: {', '.join(m.invoice_numbers) or 'nothing'}).")
        self.store.save_matches([rejected])
        return rejected

    def assign(self, tid: str, invoice_numbers: list[str]) -> Match:
        """A person says which invoices this payment is for."""
        m = self._get(tid)
        if m.status in (Status.auto, Status.confirmed):
            raise ReviewError("Reject the current match first")
        txn = self.store.transactions()[tid]
        self.store.save_matches([Match(transaction_id=tid, status=Status.unmatched, unapplied=txn.amount)])
        ledger = self._ledger()
        chosen = [ledger.invoices[n] for n in invoice_numbers if n in ledger.invoices]
        if not chosen or len({i.customer_id for i in chosen}) != 1:
            raise ReviewError("Pick one or more invoices from the same customer")
        allocations, left = allocate(txn.amount, sorted(chosen, key=lambda i: i.due_date), ledger)
        if not allocations:
            raise ReviewError("Those invoices are already fully paid")
        manual = Match(transaction_id=tid, customer_id=chosen[0].customer_id, allocations=allocations,
                       method=Method.manual, status=Status.confirmed, confidence=1.0,
                       reason="Assigned by a reviewer.", unapplied=left)
        self.store.save_matches([manual])
        return manual

    # ------------------------------------------------------------------ reports
    def transactions_view(self, status: str | None = None) -> list[dict]:
        txns, matches = self.store.transactions(), self.store.matches()
        customers = self.store.customers()
        rows = []
        for tid, t in txns.items():
            m = matches.get(tid) or Match(transaction_id=tid, unapplied=t.amount)
            if status and m.status.value != status:
                continue
            rows.append({"id": tid, "date": t.date.isoformat(), "amount": t.amount, "amount_display": naira(t.amount),
                         "narration": t.narration, "status": m.status.value,
                         "method": m.method.value if m.method else None, "confidence": m.confidence,
                         "customer": customers[m.customer_id].name if m.customer_id in customers else None,
                         "allocations": [{"invoice": a.invoice_number, "amount_display": naira(a.amount)}
                                         for a in m.allocations],
                         "unapplied_display": naira(m.unapplied) if m.unapplied else None, "reason": m.reason})
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    def summary(self) -> dict:
        txns, matches = self.store.transactions(), self.store.matches()
        invoices = self.store.invoices()
        counts = {s.value: 0 for s in Status}
        amounts = {s.value: 0 for s in Status}
        for tid, t in txns.items():
            s = (matches.get(tid) or Match(transaction_id=tid)).status.value
            counts[s] += 1
            amounts[s] += t.amount
        total = sum(t.amount for t in txns.values()) or 1
        outstanding = sum(max(i.remaining, 0) for i in invoices.values())
        overdue = [i for i in invoices.values() if i.remaining > 0 and i.due_date < self.as_of]
        return {
            "as_of": self.as_of.isoformat(), "engine": self.llm.name if self.llm else "rules only",
            "credits": len(txns), "counts": counts,
            "amount_received": naira(sum(t.amount for t in txns.values())),
            "amount_reconciled": naira(amounts["auto"] + amounts["confirmed"]),
            "auto_rate": round(counts["auto"] / max(len(txns), 1), 2),
            "reconciled_share": round((amounts["auto"] + amounts["confirmed"]) / total, 2),
            "outstanding": naira(outstanding), "overdue_count": len(overdue),
            "overdue_amount": naira(sum(i.remaining for i in overdue)),
        }

    def aging(self) -> dict:
        customers = self.store.customers()
        buckets = {name: 0 for name, _, _ in AGING_BUCKETS}
        per_customer: dict[str, dict] = {}
        for inv in self.store.invoices().values():
            if inv.remaining <= 0:
                continue
            days = (self.as_of - inv.due_date).days
            name = _bucket(days)
            buckets[name] += inv.remaining
            c = per_customer.setdefault(inv.customer_id, {"customer": customers[inv.customer_id].name, "total": 0,
                                                          "oldest_days_overdue": 0, "invoices": 0})
            c["total"] += inv.remaining
            c["invoices"] += 1
            c["oldest_days_overdue"] = max(c["oldest_days_overdue"], days)
        rows = sorted(per_customer.values(), key=lambda c: -c["total"])
        for r in rows:
            r["total_display"] = naira(r["total"])
        return {"as_of": self.as_of.isoformat(),
                "buckets": [{"bucket": k, "amount": v, "display": naira(v)} for k, v in buckets.items()],
                "customers": rows}

    def pending(self) -> dict[str, int]:
        """Kobo per invoice from payments that arrived but await review. Don't chase these customers."""
        out: dict[str, int] = {}
        for m in self.store.matches().values():
            if m.status is Status.suggested:
                for a in m.allocations:
                    out[a.invoice_number] = out.get(a.invoice_number, 0) + a.amount
        return out

    def overdue(self) -> list[dict]:
        customers = self.store.customers()
        pending = self.pending()
        rows = []
        for inv in self.store.invoices().values():
            if inv.remaining > 0 and inv.due_date < self.as_of:
                waiting = pending.get(inv.number, 0)
                rows.append({"invoice": inv.number, "customer": customers[inv.customer_id].name,
                             "outstanding": naira(inv.remaining), "due_date": inv.due_date.isoformat(),
                             "days_overdue": (self.as_of - inv.due_date).days,
                             "part_paid": inv.paid > 0,
                             "payment_pending_review": naira(waiting) if waiting else None,
                             "covered_by_pending": waiting >= inv.remaining})
        return sorted(rows, key=lambda r: -r["days_overdue"])

    def reminder(self, number: str) -> tuple[Reminder, str, str]:
        invoices = self.store.invoices()
        inv = invoices.get(number)
        if not inv:
            raise ReviewError("No such invoice")
        if inv.remaining <= 0:
            raise ReviewError("That invoice is fully paid")
        if self.pending().get(number, 0) >= inv.remaining:
            raise ReviewError("A payment for this invoice is waiting for review. Check it before chasing.")
        cust = self.store.customers()[inv.customer_id]
        reminder, engine = draft_reminder(self.llm, inv, cust, self.as_of, self.business)
        return reminder, engine, cust.email
