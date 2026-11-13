from datetime import date

import pytest

from app.importers import read_bank_statement, read_invoices
from app.money import naira, to_kobo
from app.normalize import invoice_refs, name_similarity, payer_tokens


@pytest.mark.parametrize("text,kobo", [
    ("₦1,250,000.50", 125_000_050), ("450,000.00", 45_000_000), ("N96800", 9_680_000), ("(5,000)", -500_000),
    ("-1200", -120_000), ("", 0), ("0.1", 10), (450000, 45_000_000),
])
def test_to_kobo(text, kobo):
    assert to_kobo(text) == kobo


def test_to_kobo_rejects_garbage():
    with pytest.raises(ValueError):
        to_kobo("abc")


def test_naira_formatting():
    assert naira(125_000_050) == "₦1,250,000.50" and naira(4_500_000) == "₦45,000" and naira(-100) == "-₦1"


@pytest.mark.parametrize("narration,known,refs", [
    ("NIP TRF FRM CHINEDU STORES LTD/INV-1001/GTB", None, ["1001"]),
    ("PAYMENT INVOICE NO. 0042", None, ["42"]),
    ("GOLDEN GATE PYMT 1017 1018", {"1017", "1018"}, ["1017", "1018"]),
    ("FRESH BASKET/1031", {"1031"}, ["1031"]),
    ("ACCT 0123456789 TRF", {"1234"}, []),          # account numbers are not invoice numbers
    ("PAYMT 5555", {"1001"}, []),                    # unknown bare numbers are ignored
])
def test_invoice_refs(narration, known, refs):
    assert invoice_refs(narration, known) == refs


def test_payer_tokens_drop_channel_and_bank_words():
    assert payer_tokens("NIP TRF FRM ADEBAYO OLUWASEUN/GTB/0123456789") == ["ADEBAYO", "OLUWASEUN"]
    assert payer_tokens("USSD/ZEN/MAMA NKECHI PROV") == ["MAMA", "NKECHI", "PROV"]


@pytest.mark.parametrize("narration,name,low,high", [
    ("TRF FRM CHINEDU STORE LTD", "Chinedu Stores Ltd", 0.9, 1.0),        # typo
    ("MOBILE TRF MAMA NKECHI PROV", "Mama Nkechi Provisions", 0.9, 1.0),   # abbreviation
    ("TRF OKAFOR CHINEDU", "Chinedu Okafor", 0.95, 1.0),                   # word order
    ("NIP TRF FRM ZARA PHARMACY", "Chinedu Stores Ltd", 0.0, 0.1),         # unrelated
    ("TRANSFER", "Chinedu Stores Ltd", 0.0, 0.0),                          # no name at all
])
def test_name_similarity(narration, name, low, high):
    assert low <= name_similarity(payer_tokens(narration), name) <= high


GTB_STYLE = """Account Name: TEST LTD
Account Number: 0123456789

Trans Date,Value Date,Reference,Narration,Debit,Credit,Balance
13-Oct-2026,13-Oct-2026,S1,SALARY,"1,850,000.00",,"2,360,000.00"
14-Oct-2026,14-Oct-2026,S2,NIP TRF FRM CHINEDU STORES LTD,,"450,000.00","2,810,000.00"
"""

SIGNED_AMOUNT = """Date,Description,Amount,Balance
2026/10/14,TRANSFER FROM BISI LAWAL,58900,100000
2026/10/15,POS PURCHASE,-2500,97500
"""


def test_bank_statement_with_preamble_and_credit_column():
    txns = read_bank_statement(GTB_STYLE)
    assert len(txns) == 1  # the debit is skipped
    t = txns[0]
    assert t.amount == 45_000_000 and t.date == date(2026, 10, 14) and t.reference == "S2"


def test_bank_statement_signed_amount_and_other_date_format():
    txns = read_bank_statement(SIGNED_AMOUNT.replace("2026/10/14", "14/10/2026").replace("2026/10/15", "15/10/2026"))
    assert [t.amount for t in txns] == [5_890_000]


def test_import_ids_are_stable_so_reimports_dedupe():
    assert [t.id for t in read_bank_statement(GTB_STYLE)] == [t.id for t in read_bank_statement(GTB_STYLE)]


def test_bank_statement_without_needed_columns_is_rejected():
    with pytest.raises(ValueError, match="columns"):
        read_bank_statement("Foo,Bar\n1,2\n")


def test_read_invoices_builds_customers_with_aliases():
    csv_text = ("invoice_number,customer,amount,issue_date,due_date,aliases,email\n"
                "INV-0042,Chinedu Stores Ltd,\"1,000.00\",2026-10-01,2026-10-31,Chinedu Okafor;C. Okafor,a@b.ng\n"
                "INV-43,Chinedu Stores Ltd,500,2026-10-02,2026-11-01,,a@b.ng\n")
    customers, invoices = read_invoices(csv_text)
    assert len(customers) == 1 and customers[0].aliases == ["Chinedu Okafor", "C. Okafor"]
    assert [i.number for i in invoices] == ["42", "43"] and invoices[0].amount == 100_000
