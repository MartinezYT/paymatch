"""Make sense of bank narrations.

Nigerian bank statements describe a transfer with text like
    "NIP TRF FRM ADEBAYO OLUWASEUN/GTB/0123456789"
    "MOBILE TRF FROM CHINEDU STORE LTD INV 1042"
    "USSD/ZEN/MAMA NKECHI PROV"
This module pulls out the payer's name and any invoice reference, and scores how well a
payer name matches a customer, allowing for typos, abbreviations and word order.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Words that describe the transfer channel, not the payer.
_CHANNEL_WORDS = {
    "NIP", "TRF", "TRANSFER", "TRANS", "TRSF", "FRM", "FROM", "TO", "FT", "IFO", "BO", "MOBILE", "MB", "MBANKING",
    "USSD", "POS", "WEB", "PMT", "PAYMENT", "PYMT", "REF", "NARR", "INWARD", "OUTWARD", "CREDIT", "CR", "VIA",
    "INSTANT", "NEFT", "RTGS", "APP", "INTERNET", "BANKING", "ONLINE", "FOR", "OF", "THE", "AND", "PAYT", "BEING",
    "PART", "BAL", "BALANCE", "SETTLEMENT", "INV", "INVOICE", "INVOICES", "NO", "NUMBER",
}
# Bank and fintech short names that appear in narrations.
_BANKS = {
    "GTB", "GTBANK", "GTCO", "ACCESS", "ACC", "ZENITH", "ZEN", "UBA", "FBN", "FIRSTBANK", "FIRST", "FCMB", "FIDELITY",
    "FID", "STERLING", "UNION", "WEMA", "ALAT", "ECOBANK", "ECO", "STANBIC", "IBTC", "POLARIS", "KEYSTONE",
    "OPAY", "PALMPAY", "MONIEPOINT", "KUDA", "PROVIDUS", "JAIZ", "HERITAGE", "UNITY", "TITAN", "GLOBUS", "PREMIUM",
}
# Company suffixes: useful when present, but their absence shouldn't hurt a match.
_SUFFIXES = {"LTD", "LIMITED", "PLC", "NIG", "NIGERIA", "ENT", "ENTERPRISES", "ENTERPRISE", "VENTURES", "CO",
             "COMPANY", "INTL", "INTERNATIONAL", "GLOBAL", "SERVICES", "RESOURCES", "AND", "SONS"}

_INVOICE_REF = re.compile(r"\bINV(?:OICE)?\s*[-#/:.]?\s*(?:NO\.?\s*)?0*(\d{3,7})\b", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Z][A-Z&']+")


def invoice_refs(narration: str, known_numbers: set[str] | None = None) -> list[str]:
    """Invoice numbers mentioned in a narration, as their digits ('INV-1042' -> '1042').

    With `known_numbers`, a bare number like '1042' also counts if it's a real invoice number,
    because payers often type only the digits.
    """
    found = [m.group(1) for m in _INVOICE_REF.finditer(narration)]
    if known_numbers:
        for num in re.findall(r"(?<!\d)(\d{4,7})(?!\d)", narration):
            if num.lstrip("0") in known_numbers and num.lstrip("0") not in found:
                found.append(num.lstrip("0"))
    return list(dict.fromkeys(n.lstrip("0") for n in found))


def payer_tokens(narration: str) -> list[str]:
    """Name-like words in a narration with channel words, bank names and numbers removed."""
    text = narration.upper()
    text = _INVOICE_REF.sub(" ", text)
    words = _TOKEN.findall(text.replace("&", " & "))
    return [w for w in words if w not in _CHANNEL_WORDS and w not in _BANKS and len(w) > 1]


def name_tokens(name: str) -> list[str]:
    return [w for w in _TOKEN.findall(name.upper()) if w not in _CHANNEL_WORDS]


def _token_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    # Abbreviations: "PROV" for "PROVISIONS", "SUPERMKT" for "SUPERMARKET".
    if len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def name_similarity(payer: list[str], name: str) -> float:
    """0..1: how well the payer words match a customer name or alias.

    Each meaningful word of the customer name is matched to its best payer word. Company
    suffixes (LTD, ENTERPRISES, SONS...) count for little, so 'CHINEDU STORE' still matches
    'Chinedu Stores Ltd'.
    """
    target = name_tokens(name)
    if not payer or not target:
        return 0.0
    core = [t for t in target if t not in _SUFFIXES] or target
    scores = []
    for word in core:
        best = max(_token_score(word, p) for p in payer)
        scores.append(best if best >= 0.75 else 0.0)
    coverage = sum(scores) / len(core)
    # Penalise long payer strings that only share one word with a long company name.
    extra = max(0, len(payer) - len(target) - 2) * 0.03
    return round(max(0.0, coverage - extra), 3)
