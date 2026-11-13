"""Read bank statements and invoice lists from CSV.

Every bank exports a different layout, so columns are found by their header names rather
than position: 'Trans Date' / 'Transaction Date' / 'Date', 'Narration' / 'Description' /
'Remarks', and either separate 'Credit'/'Debit' columns or one signed 'Amount' column.
Only money coming in (credits) is kept, because that's what pays invoices.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime

from .models import Customer, Invoice, Transaction

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%m/%d/%Y", "%d.%m.%Y")

_COLUMNS = {
    "date": ("trans date", "transaction date", "txn date", "date", "posted date", "value date", "tran date"),
    "narration": ("narration", "description", "remarks", "details", "transaction details", "memo"),
    "credit": ("credit", "credits", "deposit", "deposits", "money in", "credit amount", "cr"),
    "debit": ("debit", "debits", "withdrawal", "withdrawals", "money out", "debit amount", "dr"),
    "amount": ("amount", "transaction amount", "amt"),
    "reference": ("reference", "ref", "reference number", "session id", "transaction ref", "ref no"),
}


class ImportErrorWithRow(ValueError):
    pass


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {text!r}")


def _find(headers: list[str], kind: str) -> str | None:
    norm = {re.sub(r"[^a-z ]", "", h.lower()).strip(): h for h in headers}
    for candidate in _COLUMNS[kind]:  # exact names first, in order of preference
        if candidate in norm:
            return norm[candidate]
    for candidate in _COLUMNS[kind]:  # then headers like "Credit NGN" or "Narration Details"
        for key, original in norm.items():
            if len(candidate) > 2 and key.startswith(candidate + " "):
                return original
    return None


def _rows(text: str) -> list[dict[str, str]]:
    # Bank exports often start with a few lines of account info before the real header.
    lines = text.lstrip("﻿").splitlines()
    for i, line in enumerate(lines[:15]):
        low = line.lower()
        if any(w in low for w in ("narration", "description", "remarks", "details")) and "date" in low:
            return list(csv.DictReader(io.StringIO("\n".join(lines[i:]))))
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def read_bank_statement(text: str) -> list[Transaction]:
    from .money import to_kobo

    rows = _rows(text)
    if not rows:
        return []
    headers = list(rows[0].keys())
    col = {k: _find(headers, k) for k in _COLUMNS}
    if not col["date"] or not col["narration"] or not (col["credit"] or col["amount"]):
        raise ValueError(f"couldn't find date/narration/amount columns in: {headers}")

    out: list[Transaction] = []
    for n, row in enumerate(rows, start=2):
        if not (row.get(col["date"]) or "").strip():
            continue
        try:
            amount = to_kobo(row.get(col["credit"])) if col["credit"] else to_kobo(row.get(col["amount"]))
            if amount <= 0:
                continue  # debits and zero lines don't pay invoices
            when = parse_date(row[col["date"]])
        except ValueError as exc:
            raise ImportErrorWithRow(f"row {n}: {exc}") from exc
        narration = " ".join((row.get(col["narration"]) or "").split())
        reference = (row.get(col["reference"]) or "").strip() if col["reference"] else ""
        # Stable id, so importing the same statement twice doesn't create duplicates.
        key = f"{when}|{amount}|{narration}|{reference}|{n if not reference else ''}"
        tid = "T" + hashlib.sha1(key.encode()).hexdigest()[:10]
        out.append(Transaction(id=tid, date=when, amount=amount, narration=narration, reference=reference))
    return out


def read_invoices(text: str) -> tuple[list[Customer], list[Invoice]]:
    """Columns: invoice_number, customer, amount, issue_date, due_date, [aliases], [email].

    `aliases` is a ';'-separated list of other names the customer pays under, e.g. the owner.
    """
    from .money import to_kobo

    customers: dict[str, Customer] = {}
    invoices: list[Invoice] = []
    for n, row in enumerate(csv.DictReader(io.StringIO(text.lstrip("﻿"))), start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            name = row["customer"]
            cid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            aliases = [a.strip() for a in row.get("aliases", "").split(";") if a.strip()]
            c = customers.setdefault(cid, Customer(id=cid, name=name, email=row.get("email", "")))
            c.aliases = list(dict.fromkeys(c.aliases + aliases))
            number = re.sub(r"\D", "", row["invoice_number"]).lstrip("0")
            invoices.append(Invoice(number=number, customer_id=cid, amount=to_kobo(row["amount"]),
                                    issue_date=parse_date(row["issue_date"]), due_date=parse_date(row["due_date"])))
        except (KeyError, ValueError) as exc:
            raise ImportErrorWithRow(f"invoice row {n}: {exc}") from exc
    return list(customers.values()), invoices
