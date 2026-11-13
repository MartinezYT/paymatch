"""SQLite storage. An invoice's paid amount is never stored: it's always worked out from the
matches that count (automatic or confirmed), so it can't drift out of sync."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from .models import Customer, Invoice, Match, Status, Transaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT NOT NULL, email TEXT);
CREATE TABLE IF NOT EXISTS invoices (
    number TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
    amount INTEGER NOT NULL, issue_date TEXT NOT NULL, due_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, amount INTEGER NOT NULL, narration TEXT NOT NULL, reference TEXT);
CREATE TABLE IF NOT EXISTS matches (
    transaction_id TEXT PRIMARY KEY REFERENCES transactions(id), status TEXT NOT NULL, data TEXT NOT NULL);
"""

COUNTS = (Status.auto, Status.confirmed)


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def reset(self) -> None:
        with self.lock, self.db:
            for table in ("matches", "transactions", "invoices", "customers"):
                self.db.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names

    # ---------------------------------------------------------------- writes
    def upsert_customers(self, customers: list[Customer]) -> None:
        with self.lock, self.db:
            for c in customers:
                self.db.execute("INSERT INTO customers VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                                "name=excluded.name, aliases=excluded.aliases, email=excluded.email",
                                (c.id, c.name, json.dumps(c.aliases), c.email))

    def upsert_invoices(self, invoices: list[Invoice]) -> None:
        with self.lock, self.db:
            for i in invoices:
                self.db.execute("INSERT INTO invoices VALUES (?,?,?,?,?) ON CONFLICT(number) DO UPDATE SET "
                                "customer_id=excluded.customer_id, amount=excluded.amount, "
                                "issue_date=excluded.issue_date, due_date=excluded.due_date",
                                (i.number, i.customer_id, i.amount, i.issue_date.isoformat(), i.due_date.isoformat()))

    def add_transactions(self, txns: list[Transaction]) -> list[Transaction]:
        """Insert new transactions; returns only the ones not seen before."""
        new = []
        with self.lock, self.db:
            for t in txns:
                cur = self.db.execute("INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?)",
                                      (t.id, t.date.isoformat(), t.amount, t.narration, t.reference))
                if cur.rowcount:
                    new.append(t)
        return new

    def save_matches(self, matches: list[Match]) -> None:
        with self.lock, self.db:
            for m in matches:
                self.db.execute("INSERT INTO matches VALUES (?,?,?) ON CONFLICT(transaction_id) DO UPDATE SET "
                                "status=excluded.status, data=excluded.data",
                                (m.transaction_id, m.status.value, m.model_dump_json()))

    # ---------------------------------------------------------------- reads
    def customers(self) -> dict[str, Customer]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM customers").fetchall()
        return {r["id"]: Customer(id=r["id"], name=r["name"], aliases=json.loads(r["aliases"]), email=r["email"] or "")
                for r in rows}

    def transactions(self) -> dict[str, Transaction]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM transactions ORDER BY date, id").fetchall()
        return {r["id"]: Transaction(id=r["id"], date=date.fromisoformat(r["date"]), amount=r["amount"],
                                     narration=r["narration"], reference=r["reference"] or "") for r in rows}

    def matches(self) -> dict[str, Match]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM matches").fetchall()
        return {m.transaction_id: m for m in (Match.model_validate_json(r["data"]) for r in rows)}

    def invoices(self) -> dict[str, Invoice]:
        """Invoices with `paid` worked out from the matches that count."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM invoices ORDER BY number").fetchall()
        paid: dict[str, int] = {}
        for m in self.matches().values():
            if m.status in COUNTS:
                for a in m.allocations:
                    paid[a.invoice_number] = paid.get(a.invoice_number, 0) + a.amount
        return {r["number"]: Invoice(number=r["number"], customer_id=r["customer_id"], amount=r["amount"],
                                     issue_date=date.fromisoformat(r["issue_date"]),
                                     due_date=date.fromisoformat(r["due_date"]), paid=paid.get(r["number"], 0))
                for r in rows}
