"""Money is stored as integer kobo (1 naira = 100 kobo).

Floats can't represent amounts like 0.1 exactly, and reconciliation is all about amounts
being *exactly* equal, so every amount is converted to an int the moment it's read.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CLEAN = re.compile(r"[₦,\s]|NGN|N(?=\d)", re.IGNORECASE)


def to_kobo(value: str | int | float | Decimal | None) -> int:
    """'₦1,250,000.50' -> 125000050. Blank -> 0. Brackets or a minus sign mean negative."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value * 100
    text = str(value).strip()
    if not text or text in ("-", "--"):
        return 0
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-")
    text = _CLEAN.sub("", text.strip("()").lstrip("-"))
    try:
        kobo = int((Decimal(text) * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {value!r}") from exc
    return -kobo if negative else kobo


def naira(kobo: int) -> str:
    """125000050 -> '₦1,250,000.50' (drops .00)."""
    sign = "-" if kobo < 0 else ""
    whole, frac = divmod(abs(kobo), 100)
    return f"{sign}₦{whole:,}" + (f".{frac:02d}" if frac else "")
