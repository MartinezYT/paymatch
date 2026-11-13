"""The reconciliation engine: decide which invoice(s) each incoming payment settles.

Rules run first, from most certain to least. Only a match the rules are sure about is
applied automatically; everything else becomes a *suggestion* for a person to confirm.
The AI is asked only about payments the rules can't place, and even then it may only pick
invoices from a shortlist. The code, not the AI, works out how much goes to each invoice.

Guiding principle: a wrong automatic match is far worse than a missed one, because it
marks an unpaid invoice as paid and nobody chases it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Protocol

from .models import Allocation, Customer, Invoice, Match, Method, Status, Transaction
from .money import naira
from .normalize import invoice_refs, name_similarity, payer_tokens

STRONG_NAME = 0.85      # name score needed for an automatic match
WEAK_NAME = 0.6         # name score needed to consider a customer at all
MARGIN = 0.15           # the best customer must beat the runner-up by this much
MAX_COMBO = 4           # largest group of invoices one transfer may settle


class AIMatcher(Protocol):
    name: str

    def choose(self, txn: Transaction, candidates: list[tuple[Invoice, Customer]]) -> tuple[list[str], float, str]:
        """Return (invoice numbers from the candidates, confidence, reason)."""


@dataclass
class Ledger:
    """Open balances while a statement is being matched.

    Suggested matches reserve their invoices too, so two payments aren't both suggested
    for the same invoice.
    """

    customers: dict[str, Customer]
    invoices: dict[str, Invoice]
    reserved: dict[str, int] = field(default_factory=dict)

    def remaining(self, number: str) -> int:
        inv = self.invoices[number]
        return inv.remaining - self.reserved.get(number, 0)

    def open_for(self, customer_id: str) -> list[Invoice]:
        """A customer's unpaid invoices, oldest due date first."""
        mine = (i for i in self.invoices.values() if i.customer_id == customer_id and self.remaining(i.number) > 0)
        return sorted(mine, key=lambda i: (i.due_date, i.number))

    def all_open(self) -> list[Invoice]:
        return [i for i in self.invoices.values() if self.remaining(i.number) > 0]

    def reserve(self, match: Match) -> None:
        for a in match.allocations:
            self.reserved[a.invoice_number] = self.reserved.get(a.invoice_number, 0) + a.amount


def allocate(amount: int, invoices: list[Invoice], ledger: Ledger) -> tuple[list[Allocation], int]:
    """Spread a payment over invoices oldest-first (standard accounting practice). Returns leftover."""
    allocations = []
    left = amount
    for inv in invoices:
        if left <= 0:
            break
        take = min(left, ledger.remaining(inv.number))
        if take > 0:
            allocations.append(Allocation(invoice_number=inv.number, amount=take))
            left -= take
    return allocations, left


def rank_customers(txn: Transaction, ledger: Ledger) -> list[tuple[float, Customer]]:
    tokens = payer_tokens(txn.narration)
    scored = []
    for c in ledger.customers.values():
        score = max([name_similarity(tokens, c.name)] + [name_similarity(tokens, a) for a in c.aliases])
        if score >= WEAK_NAME:
            scored.append((score, c))
    return sorted(scored, key=lambda s: -s[0])


def _match(txn, customer, allocations, method, status, confidence, reason, unapplied=0) -> Match:
    return Match(transaction_id=txn.id, customer_id=customer.id if customer else None, allocations=allocations,
                 method=method, status=status, confidence=round(confidence, 2), reason=reason, unapplied=unapplied)


def match_one(txn: Transaction, ledger: Ledger, ai: AIMatcher | None = None) -> Match:
    amount = txn.amount

    # 1. Invoice number in the narration. The strongest evidence there is.
    refs = [r for r in invoice_refs(f"{txn.narration} {txn.reference}", set(ledger.invoices)) if r in ledger.invoices]
    open_refs = [ledger.invoices[r] for r in refs if ledger.remaining(r) > 0]
    if open_refs:
        customer = ledger.customers.get(open_refs[0].customer_id)
        allocations, left = allocate(amount, sorted(open_refs, key=lambda i: i.due_date), ledger)
        owed = sum(ledger.remaining(i.number) for i in open_refs)
        if amount == owed:
            return _match(txn, customer, allocations, Method.reference, Status.auto, 0.98,
                          f"Narration quotes invoice {', '.join(refs)} and the amount matches exactly.")
        kind = "less" if amount < owed else "more"
        return _match(txn, customer, allocations, Method.reference, Status.suggested, 0.85,
                      f"Narration quotes invoice {', '.join(refs)}, but {naira(amount)} is {kind} than the "
                      f"{naira(owed)} owed.", unapplied=left)

    ranked = rank_customers(txn, ledger)
    best_score, best = ranked[0] if ranked else (0.0, None)
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    clear_winner = best is not None and best_score >= STRONG_NAME and best_score - runner_up >= MARGIN

    if best is not None and best_score - runner_up >= MARGIN:
        open_invoices = ledger.open_for(best.id)
        # 2. Payer name + an invoice for exactly this amount.
        exact = [i for i in open_invoices if ledger.remaining(i.number) == amount]
        if exact:
            inv = exact[0]  # oldest first if several share the amount
            allocations = [Allocation(invoice_number=inv.number, amount=amount)]
            if clear_winner and len(exact) == 1:
                return _match(txn, best, allocations, Method.name_amount, Status.auto, 0.93,
                              f"Payer looks like {best.name} (name match {best_score:.0%}) and invoice "
                              f"{inv.number} is for exactly {naira(amount)}.")
            why = (f"{len(exact)} invoices from {best.name} are for {naira(amount)}; picked the oldest"
                   if len(exact) > 1 else f"Payer might be {best.name} (name match {best_score:.0%})")
            return _match(txn, best, allocations, Method.name_amount, Status.suggested, 0.8, why + ".")

        # 3. One transfer settling several invoices.
        combo = _combination(amount, open_invoices[:10], ledger)
        if combo:
            allocations = [Allocation(invoice_number=i.number, amount=ledger.remaining(i.number)) for i in combo]
            return _match(txn, best, allocations, Method.multi_invoice, Status.suggested, 0.85,
                          f"{naira(amount)} equals invoices {', '.join(i.number for i in combo)} from {best.name} "
                          "added together.")

        if open_invoices:
            total = sum(ledger.remaining(i.number) for i in open_invoices)
            allocations, left = allocate(amount, open_invoices, ledger)
            # 4. Overpayment: more than everything they owe.
            if amount > total:
                return _match(txn, best, allocations, Method.overpayment, Status.suggested, 0.75,
                              f"{best.name} paid {naira(amount)} but only owes {naira(total)}; "
                              f"{naira(left)} is unapplied credit.", unapplied=left)
            # 5. Part payment against the oldest invoices.
            if best_score >= STRONG_NAME:
                return _match(txn, best, allocations, Method.partial, Status.suggested, 0.75,
                              f"Looks like a part payment from {best.name}: {naira(amount)} applied to the oldest "
                              f"open invoice(s) ({', '.join(a.invoice_number for a in allocations)}).")

    # 6. Nobody recognised, but exactly one open invoice anywhere has this amount.
    if not ranked:
        # Uniqueness is judged on real balances, ignoring tentative suggestions: a pending guess
        # elsewhere must not make this payment look certain.
        same_amount = [i for i in ledger.invoices.values() if i.remaining == amount]
        if len(same_amount) == 1 and ledger.remaining(same_amount[0].number) == amount:
            inv = same_amount[0]
            customer = ledger.customers.get(inv.customer_id)
            return _match(txn, customer, [Allocation(invoice_number=inv.number, amount=amount)], Method.amount_only,
                          Status.suggested, 0.55, f"Payer name not recognised, but invoice {inv.number} "
                          f"({customer.name if customer else '?'}) is the only open invoice for {naira(amount)}.")

    # 7. Ask the AI, with a shortlist it must choose from.
    if ai is not None:
        ai_match = _ask_ai(txn, ledger, ai, ranked)
        if ai_match:
            return ai_match

    reason = "No customer name, invoice number or amount matched."
    if ranked:
        reason = (f"Payer could be {' or '.join(c.name for _, c in ranked[:2])}, but no invoice amounts fit. "
                  "Needs a person.")
    return Match(transaction_id=txn.id, status=Status.unmatched, reason=reason, unapplied=amount)


def _combination(amount: int, invoices: list[Invoice], ledger: Ledger) -> list[Invoice] | None:
    for size in range(2, min(MAX_COMBO, len(invoices)) + 1):
        for combo in combinations(invoices, size):
            if sum(ledger.remaining(i.number) for i in combo) == amount:
                return list(combo)
    return None


def shortlist(txn: Transaction, ledger: Ledger, ranked, limit: int = 8) -> list[tuple[Invoice, Customer]]:
    """Invoices worth showing the AI: the likely customers' invoices, then the closest amounts."""
    picked: dict[str, Invoice] = {}
    for _, c in ranked[:3]:
        for inv in ledger.open_for(c.id)[:4]:
            picked[inv.number] = inv
    by_amount = sorted(ledger.all_open(), key=lambda i: abs(ledger.remaining(i.number) - txn.amount))
    for inv in by_amount:
        if len(picked) >= limit:
            break
        picked.setdefault(inv.number, inv)
    return [(inv, ledger.customers[inv.customer_id]) for inv in picked.values()]


def _ask_ai(txn: Transaction, ledger: Ledger, ai: AIMatcher, ranked) -> Match | None:
    candidates = shortlist(txn, ledger, ranked)
    if not candidates:
        return None
    try:
        numbers, confidence, reason = ai.choose(txn, candidates)
    except Exception as exc:  # noqa: BLE001 - the AI is optional; never break matching
        return Match(transaction_id=txn.id, status=Status.unmatched, unapplied=txn.amount,
                     reason=f"No rule matched and the AI was unavailable ({str(exc)[:80]}).")
    allowed = {inv.number for inv, _ in candidates}
    chosen = [ledger.invoices[n] for n in dict.fromkeys(numbers) if n in allowed]  # ignore anything invented
    if not chosen:
        return Match(transaction_id=txn.id, status=Status.unmatched, unapplied=txn.amount,
                     reason=f"AI found no plausible invoice: {reason}")
    customer_ids = {i.customer_id for i in chosen}
    if len(customer_ids) > 1:
        return Match(transaction_id=txn.id, status=Status.unmatched, unapplied=txn.amount,
                     reason="AI picked invoices from different customers; left for a person.")
    allocations, left = allocate(txn.amount, sorted(chosen, key=lambda i: i.due_date), ledger)
    customer = ledger.customers[chosen[0].customer_id]
    return _match(txn, customer, allocations, Method.ai, Status.suggested, min(confidence, 0.8),
                  f"AI ({ai.name}): {reason}", unapplied=left)


def reconcile(transactions: list[Transaction], ledger: Ledger, ai: AIMatcher | None = None) -> list[Match]:
    """Match a statement in two passes: certain matches first, so they can't be stolen by guesses."""
    results: dict[str, Match] = {}
    ordered = sorted(transactions, key=lambda t: (t.date, t.id))
    deferred = []
    for txn in ordered:
        m = match_one(txn, ledger, ai=None)
        if m.status is Status.auto:
            results[txn.id] = m
            ledger.reserve(m)
        else:
            deferred.append(txn)
    for txn in deferred:
        m = match_one(txn, ledger, ai=ai)
        results[txn.id] = m
        ledger.reserve(m)
    return [results[t.id] for t in ordered]
