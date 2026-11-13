"""Core data shapes. All money is integer kobo."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class Customer(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list, description="Owner/contact names and other spellings.")
    email: str = ""


class Invoice(BaseModel):
    number: str                    # digits only, e.g. "1042"
    customer_id: str
    amount: int                    # kobo
    issue_date: date
    due_date: date
    paid: int = 0                  # kobo applied from confirmed/auto matches

    @property
    def remaining(self) -> int:
        return self.amount - self.paid


class Transaction(BaseModel):
    id: str
    date: date
    amount: int                    # kobo, credits only
    narration: str
    reference: str = ""


class Method(StrEnum):
    reference = "reference"        # invoice number in the narration
    name_amount = "name_amount"    # payer name + exact amount
    multi_invoice = "multi_invoice"  # one transfer pays several invoices
    partial = "partial"            # less than the invoice
    overpayment = "overpayment"    # more than everything owed
    amount_only = "amount_only"    # unique amount, payer name unknown
    ai = "ai"
    manual = "manual"


class Status(StrEnum):
    auto = "auto"                  # applied automatically: high confidence
    suggested = "suggested"        # waiting for a person
    confirmed = "confirmed"
    rejected = "rejected"
    unmatched = "unmatched"


class Allocation(BaseModel):
    invoice_number: str
    amount: int


class Match(BaseModel):
    transaction_id: str
    customer_id: str | None = None
    allocations: list[Allocation] = Field(default_factory=list)
    method: Method | None = None
    status: Status = Status.unmatched
    confidence: float = 0.0
    reason: str = ""
    unapplied: int = 0             # kobo left over (overpayment / no invoice)

    @property
    def invoice_numbers(self) -> list[str]:
        return [a.invoice_number for a in self.allocations]
