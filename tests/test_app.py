import json
import time
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai import LLM, draft_reminder
from app.main import Settings, create_app
from app.models import Status
from app.service import PayMatch, ReviewError
from app.store import Store

AS_OF = date(2026, 11, 13)


@pytest.fixture
def svc():
    s = PayMatch(Store(":memory:"), as_of=AS_OF)
    s.load_sample()
    return s


def find(svc, text):
    return next(t for t in svc.transactions_view() if text in t["narration"])


def test_sample_loads_and_summarises(svc):
    s = svc.summary()
    assert s["credits"] == 26 and s["counts"]["auto"] == 11 and s["counts"]["unmatched"] == 6


def test_paid_amount_comes_only_from_auto_and_confirmed(svc):
    assert svc.store.invoices()["1001"].remaining == 0         # auto-matched
    assert svc.store.invoices()["1008"].remaining > 0          # only suggested so far
    svc.confirm(find(svc, "BLESSED HANDS")["id"])
    assert svc.store.invoices()["1008"].remaining == 0


def test_reject_frees_the_invoices(svc):
    t = find(svc, "BLESSED HANDS")
    svc.reject(t["id"])
    assert svc.store.matches()[t["id"]].status is Status.unmatched
    assert "1008" not in svc.pending()


def test_assign_manually(svc):
    t = find(svc, "SUNNY GROCERS")
    m = svc.assign(t["id"], ["1005"])
    assert m.status is Status.confirmed and m.invoice_numbers == ["1005"]
    with pytest.raises(ReviewError):
        svc.assign(t["id"], ["1005"])  # already confirmed


def test_assign_rejects_mixed_customers(svc):
    with pytest.raises(ReviewError):
        svc.assign(find(svc, "SUNNY GROCERS")["id"], ["1005", "1001"])


def test_reimporting_the_same_statement_adds_nothing(svc):
    from app.service import SAMPLE
    result = svc.import_statement((SAMPLE / "bank_statement.csv").read_text())
    assert result["new"] == 0 and result["duplicates_skipped"] == 26


def test_new_invoices_rematch_unmatched_payments(svc):
    before = svc.summary()["counts"]["unmatched"]
    svc.import_invoices("invoice_number,customer,amount,issue_date,due_date\n"
                        "INV-2001,Sunny Grocers,\"184,000.00\",2026-10-01,2026-10-31\n")
    assert svc.summary()["counts"]["unmatched"] == before - 1


def test_aging_buckets_add_up(svc):
    a = svc.aging()
    assert sum(b["amount"] for b in a["buckets"]) == sum(c["total"] for c in a["customers"])


def test_customers_with_a_pending_payment_are_not_chased(svc):
    row = next(r for r in svc.overdue() if r["invoice"] == "1024")
    assert row["covered_by_pending"]
    with pytest.raises(ReviewError, match="waiting for review"):
        svc.reminder("1024")


def test_reminder_tone_and_template_fallback(svc):
    rem, engine, email = svc.reminder("1028")
    assert engine == "template" and "96 days overdue" in rem.body and email


def fake_llm(arguments, status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status, json={"error": "x"})
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"type": "function", "function": {"name": json.loads(request.content)["tools"][0]["function"]["name"],
                                              "arguments": json.dumps(arguments)}}]}}]})
    return LLM("k", client=httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler)))


def test_ai_reminder_and_its_fallback(svc):
    inv, cust = svc.store.invoices()["1028"], svc.store.customers()["mama-nkechi-provisions"]
    rem, engine = draft_reminder(fake_llm({"subject": "Overdue", "body": "Dear Nkechi..."}), inv, cust, AS_OF, "Kola")
    assert engine.startswith("groq") and rem.subject == "Overdue"
    rem, engine = draft_reminder(fake_llm({}, status=500), inv, cust, AS_OF, "Kola")
    assert engine == "template-fallback" and "INV-1028" in rem.body


# ------------------------------------------------------------------- HTTP API

def client(**overrides) -> TestClient:
    settings = Settings(database_path=":memory:", as_of=AS_OF, **overrides)
    return TestClient(create_app(settings))


def wait_for_sample(c: TestClient):
    for _ in range(100):
        if c.get("/api/summary").json()["credits"] == 26:
            return
        time.sleep(0.02)
    raise AssertionError("sample data did not load")


def test_demo_mode_loads_sample_and_blocks_uploads():
    c = client(demo_mode=True)
    wait_for_sample(c)
    r = c.post("/api/import/statement", files={"file": ("s.csv", b"Date,Narration,Credit\n")})
    assert r.status_code == 403 and "public demo" in r.json()["detail"]
    assert c.post("/api/demo/reset").status_code == 200


def test_private_mode_requires_api_key():
    c = client(api_key="secret")
    assert c.get("/api/summary").status_code == 401
    h = {"X-API-Key": "secret"}
    invoices = open("sample/invoices.csv", "rb").read()
    statement = open("sample/bank_statement.csv", "rb").read()
    assert c.post("/api/import/invoices", files={"file": ("i.csv", invoices)}, headers=h).status_code == 200
    r = c.post("/api/import/statement", files={"file": ("s.csv", statement)}, headers=h)
    assert r.status_code == 200 and r.json()["results"]["auto"] == 11


def test_review_endpoints_and_errors():
    c = client(demo_mode=True)
    wait_for_sample(c)
    sug = c.get("/api/transactions?status=suggested").json()[0]
    assert c.post(f"/api/transactions/{sug['id']}/confirm").status_code == 200
    assert c.post(f"/api/transactions/{sug['id']}/confirm").status_code == 409   # can't confirm twice
    assert c.post("/api/transactions/nope/reject").status_code == 409
    assert c.post("/api/invoices/9999/reminder").status_code == 409


def test_bad_csv_is_a_422_not_a_crash():
    c = client(api_key="k")
    r = c.post("/api/import/statement", files={"file": ("x.csv", b"foo,bar\n1,2\n")}, headers={"X-API-Key": "k"})
    assert r.status_code == 422
