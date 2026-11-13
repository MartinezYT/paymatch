from datetime import date

import pytest

from app.matcher import Ledger, match_one, reconcile
from app.models import Customer, Invoice, Method, Status, Transaction


def inv(number, customer, naira, due="2026-10-31"):
    return Invoice(number=number, customer_id=customer, amount=naira * 100, issue_date=date(2026, 10, 1),
                   due_date=date.fromisoformat(due))


def txn(narration, naira, tid="T1"):
    return Transaction(id=tid, date=date(2026, 11, 1), amount=naira * 100, narration=narration)


@pytest.fixture
def ledger():
    customers = [Customer(id="chinedu", name="Chinedu Stores Ltd", aliases=["Chinedu Okafor"]),
                 Customer(id="joy", name="Joy Bakery & Cafe", aliases=["Joy Nwosu"]),
                 Customer(id="ikoyi", name="Ikoyi Corner Shop")]
    invoices = [inv("1001", "chinedu", 450_000, "2026-10-01"), inv("1002", "chinedu", 182_250, "2026-10-15"),
                inv("2001", "joy", 72_500, "2026-10-05"), inv("2002", "joy", 49_250, "2026-10-20"),
                inv("3001", "ikoyi", 150_000), inv("3002", "joy", 150_000, "2026-11-30")]
    return Ledger({c.id: c for c in customers}, {i.number: i for i in invoices})


def test_reference_and_exact_amount_is_auto(ledger):
    m = match_one(txn("NIP TRF FRM CHINEDU STORES/INV-1002", 182_250), ledger)
    assert (m.status, m.method, m.invoice_numbers) == (Status.auto, Method.reference, ["1002"])


def test_reference_with_wrong_amount_is_only_suggested(ledger):
    m = match_one(txn("PAYMENT INV-1001", 400_000), ledger)
    assert m.status is Status.suggested and "less than" in m.reason


def test_alias_name_and_amount_is_auto(ledger):
    m = match_one(txn("TRANSFER FROM CHINEDU OKAFOR/GTB", 450_000), ledger)
    assert m.status is Status.auto and m.invoice_numbers == ["1001"]


def test_one_transfer_two_invoices(ledger):
    m = match_one(txn("MB TRF JOY NWOSU/KUDA", 121_750), ledger)
    assert m.method is Method.multi_invoice and sorted(m.invoice_numbers) == ["2001", "2002"]
    assert m.status is Status.suggested


def test_part_payment_goes_to_oldest_invoice(ledger):
    m = match_one(txn("NIP TRF FRM CHINEDU STORES LTD", 100_000), ledger)
    assert m.method is Method.partial and m.invoice_numbers == ["1001"] and m.allocations[0].amount == 10_000_000


def test_overpayment_keeps_unapplied_credit(ledger):
    m = match_one(txn("NIP TRF FRM CHINEDU STORES LTD", 700_000), ledger)
    assert m.method is Method.overpayment and m.unapplied == (700_000 - 632_250) * 100


def test_ambiguous_amount_without_name_is_never_guessed(ledger):
    m = match_one(txn("TRANSFER", 150_000), ledger)  # 3001 (Ikoyi) and 3002 (Joy) both fit
    assert m.status is Status.unmatched and m.invoice_numbers == []


def test_unique_amount_without_name_is_only_a_suggestion(ledger):
    m = match_one(txn("TRF FRM AMARACHI OKORO", 182_250), ledger)
    assert (m.status, m.method) == (Status.suggested, Method.amount_only)


def test_auto_requires_a_clear_winner_between_customers():
    customers = [Customer(id="a", name="Adebayo Foods"), Customer(id="b", name="Adebayo Stores")]
    invoices = [inv("1", "a", 1000), inv("2", "b", 1000)]
    led = Ledger({c.id: c for c in customers}, {i.number: i for i in invoices})
    m = match_one(txn("TRF FRM ADEBAYO", 1000), led)
    assert m.status is not Status.auto  # two Adebayos: a person must decide


def test_reconcile_never_double_books_an_invoice(ledger):
    a = txn("NIP TRF FRM CHINEDU STORES LTD", 450_000, "T1")
    b = txn("TRANSFER FROM CHINEDU OKAFOR", 450_000, "T2")
    results = reconcile([a, b], ledger)
    booked = [n for m in results for n in m.invoice_numbers]
    assert booked.count("1001") == 1


def test_certain_matches_are_applied_before_guesses(ledger):
    guess = txn("TRF FRM AMARACHI OKORO", 182_250, "T1")         # amount-only suggestion for 1002...
    sure = txn("CHINEDU STORES INV 1002", 182_250, "T2")         # ...but this one quotes 1002
    results = {m.transaction_id: m for m in reconcile([guess, sure], ledger)}
    assert results["T2"].status is Status.auto and results["T2"].invoice_numbers == ["1002"]
    assert "1002" not in results["T1"].invoice_numbers


class FakeAI:
    name = "fake"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.seen = answer, error, None

    def choose(self, t, candidates):
        self.seen = [i.number for i, _ in candidates]
        if self.error:
            raise self.error
        return self.answer


def test_ai_is_asked_only_when_rules_fail_and_never_auto(ledger):
    ai = FakeAI((["3001"], 0.95, "Ikoyi shop owner"))
    m = match_one(txn("TRF FRM MR BADMUS FOR SHOP", 150_000), ledger, ai=ai)
    assert ai.seen and m.method is Method.ai and m.status is Status.suggested and m.confidence <= 0.8


def test_ai_invented_invoice_numbers_are_ignored(ledger):
    m = match_one(txn("TRF FRM MR BADMUS", 150_000), ledger, ai=FakeAI((["9999"], 0.9, "made up")))
    assert m.status is Status.unmatched


def test_ai_mixing_customers_is_refused(ledger):
    m = match_one(txn("TRF FRM MR BADMUS", 150_000), ledger, ai=FakeAI((["3001", "1001"], 0.9, "both")))
    assert m.status is Status.unmatched and "different customers" in m.reason


def test_ai_failure_leaves_payment_unmatched(ledger):
    m = match_one(txn("TRF FRM MR BADMUS", 150_000), ledger, ai=FakeAI(error=RuntimeError("down")))
    assert m.status is Status.unmatched and "unavailable" in m.reason


def test_pending_suggestion_does_not_make_an_ambiguous_amount_unique(ledger):
    # 3001 and 3002 are both 150,000. A suggestion reserving 3001 must not turn "TRANSFER 150,000" into 3002.
    from app.models import Allocation, Match
    ledger.reserve(Match(transaction_id="X", allocations=[Allocation(invoice_number="3001", amount=15_000_000)],
                         status=Status.suggested))
    m = match_one(txn("TRANSFER", 150_000), ledger)
    assert m.status is Status.unmatched
