"""HTTP API and dashboard.

    DEMO_MODE=true uvicorn app.main:app --reload     ->  http://localhost:8000
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .ai import LLM
from .dashboard import DASHBOARD_HTML
from .importers import ImportErrorWithRow
from .service import PayMatch, ReviewError
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("paymatch")

MAX_UPLOAD = 2_000_000  # bytes


class Settings(BaseModel):
    database_path: str = "data/paymatch.db"
    api_key: str = ""
    demo_mode: bool = False
    as_of: date | None = None
    business: str = "Kola Foods Distribution Ltd"
    llm_key: str = ""
    llm_provider: str = "groq"
    llm_model: str = ""
    ai_per_minute: int = 6

    @classmethod
    def from_env(cls) -> Settings:
        env = os.getenv
        as_of = env("AS_OF_DATE", "").strip()
        return cls(database_path=env("DATABASE_PATH", "data/paymatch.db"), api_key=env("API_KEY", "").strip(),
                   demo_mode=env("DEMO_MODE", "false").lower() in ("1", "true", "yes"),
                   as_of=date.fromisoformat(as_of) if as_of else None,
                   business=env("BUSINESS_NAME", "Kola Foods Distribution Ltd"),
                   llm_key=(env("GROQ_API_KEY") or env("LLM_API_KEY") or "").strip(),
                   llm_provider=env("LLM_PROVIDER", "groq"), llm_model=env("LLM_MODEL", ""))


class AssignBody(BaseModel):
    invoice_numbers: list[str]


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = time.monotonic(), self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if llm is None and settings.llm_key:
        llm = LLM(settings.llm_key, settings.llm_provider, settings.llm_model)
    service = PayMatch(Store(settings.database_path), llm=llm, as_of=settings.as_of, business=settings.business)
    limiter = RateLimiter(settings.ai_per_minute)
    app = FastAPI(title="PayMatch", version="1.0.0",
                  description="Match bank transfers to invoices, review the unclear ones, chase what's overdue.")
    app.state.service = service

    if settings.demo_mode and service.store.matches() == {} and not service.store.invoices():
        # Background: with an AI key, matching the unclear payments takes a few seconds.
        threading.Thread(target=service.load_sample, daemon=True).start()

    def authorised(key: str | None) -> bool:
        return not settings.api_key or (key is not None and hmac.compare_digest(key, settings.api_key))

    def can_read(x_api_key: str | None = Header(default=None)) -> None:
        if not settings.demo_mode and not authorised(x_api_key):
            raise HTTPException(401, "Invalid or missing X-API-Key")

    def can_upload(x_api_key: str | None = Header(default=None)) -> None:
        # The public demo shares one database: never let visitors upload real statements into it.
        if settings.demo_mode and not (settings.api_key and authorised(x_api_key)):
            raise HTTPException(403, "Uploads are switched off in the public demo. Run PayMatch yourself to "
                                     "reconcile your own statements.")
        if not authorised(x_api_key):
            raise HTTPException(401, "Invalid or missing X-API-Key")

    def ai_budget(request: Request) -> None:
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
        if service.llm and not limiter.allow(ip.strip()):
            raise HTTPException(429, "Too many AI requests; try again in a minute")

    async def read_upload(file: UploadFile) -> str:
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "File too large (2 MB max)")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("latin-1")

    def handle(fn, *args):
        try:
            return fn(*args)
        except ReviewError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ImportErrorWithRow, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    # ---------------------------------------------------------------- routes
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "engine": service.llm.name if service.llm else "rules only",
                "demo_mode": settings.demo_mode, "as_of": service.as_of.isoformat()}

    @app.post("/api/import/invoices", dependencies=[Depends(can_upload)])
    async def import_invoices(file: UploadFile = File(...)) -> dict:
        return handle(service.import_invoices, await read_upload(file))

    @app.post("/api/import/statement", dependencies=[Depends(can_upload)])
    async def import_statement(file: UploadFile = File(...)) -> dict:
        return handle(service.import_statement, await read_upload(file))

    @app.post("/api/demo/reset", dependencies=[Depends(can_read)])
    def reset_demo(request: Request) -> dict:
        if not settings.demo_mode:
            raise HTTPException(404, "Not found")
        ai_budget(request)
        return service.load_sample()

    @app.get("/api/summary", dependencies=[Depends(can_read)])
    def summary() -> dict:
        return service.summary()

    @app.get("/api/transactions", dependencies=[Depends(can_read)])
    def transactions(status: str | None = None) -> list[dict]:
        return service.transactions_view(status)

    @app.post("/api/transactions/{tid}/confirm", dependencies=[Depends(can_read)])
    def confirm(tid: str) -> dict:
        return handle(service.confirm, tid).model_dump(mode="json")

    @app.post("/api/transactions/{tid}/reject", dependencies=[Depends(can_read)])
    def reject(tid: str) -> dict:
        return handle(service.reject, tid).model_dump(mode="json")

    @app.post("/api/transactions/{tid}/assign", dependencies=[Depends(can_read)])
    def assign(tid: str, body: AssignBody) -> dict:
        return handle(service.assign, tid, body.invoice_numbers).model_dump(mode="json")

    @app.get("/api/aging", dependencies=[Depends(can_read)])
    def aging() -> dict:
        return service.aging()

    @app.get("/api/overdue", dependencies=[Depends(can_read)])
    def overdue() -> list[dict]:
        return service.overdue()

    @app.get("/api/invoices/open", dependencies=[Depends(can_read)])
    def open_invoices() -> list[dict]:
        customers = service.store.customers()
        return [{"invoice": i.number, "customer": customers[i.customer_id].name, "remaining": i.remaining}
                for i in service.store.invoices().values() if i.remaining > 0]

    @app.post("/api/invoices/{number}/reminder", dependencies=[Depends(can_read)])
    def reminder(number: str, request: Request) -> dict:
        ai_budget(request)
        rem, engine, email = handle(service.reminder, number)
        return {"to": email, "subject": rem.subject, "body": rem.body, "engine": engine}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        if not settings.demo_mode and settings.api_key:
            return "<h1>PayMatch</h1><p>API running. See <a href='/docs'>/docs</a>.</p>"
        return DASHBOARD_HTML.replace("{{BUSINESS}}", settings.business)

    return app


app = create_app()
