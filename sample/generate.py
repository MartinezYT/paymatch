"""Generate the demo data set: Kola Foods Distribution Ltd, Lagos, as of 13 Nov 2026.

Writes sample/invoices.csv, sample/bank_statement.csv and evals/labels.json (the correct
answer for every credit on the statement). Each payment is built to exercise one real-world
situation: exact references, typos, owners paying from personal accounts, one transfer for
several invoices, part payments, overpayments, unknown payers and look-alike amounts.

    python sample/generate.py
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = date(2026, 11, 13)

CUSTOMERS = {
    "Chinedu Stores Ltd": ("Chinedu Okafor", "accounts@chinedustores.ng"),
    "Mama Nkechi Provisions": ("Nkechi Eze", "nkechi.provisions@gmail.com"),
    "Adebayo & Sons Enterprises": ("Oluwaseun Adebayo", "adebayoandsons@yahoo.com"),
    "Blessed Hands Supermarket": ("Grace Ibe", "blessedhands.smkt@gmail.com"),
    "Zara Pharmacy Ltd": ("Zainab Musa", "zarapharmacy@outlook.com"),
    "Emeka Okeke Ventures": ("", "emekaokekeventures@gmail.com"),
    "Fresh Basket Mart": ("Tunde Bakare", "freshbasket@gmail.com"),
    "Golden Gate Hotels Ltd": ("", "procurement@goldengatehotels.ng"),
    "Hope Medical Store": ("Femi Adeyemi", "hopemedical@yahoo.com"),
    "Ikoyi Corner Shop": ("Bisi Lawal", "ikoyicorner@gmail.com"),
    "Joy Bakery & Cafe": ("Joy Nwosu", "joybakery@gmail.com"),
    "Kano Traders Co": ("Ibrahim Sani", "kanotraders@gmail.com"),
}

# number: (customer, amount in naira, issued N days before D, payment terms in days)
INVOICES = {
    1001: ("Chinedu Stores Ltd", 450_000, 40, 30), 1002: ("Chinedu Stores Ltd", 182_250, 35, 30),
    1003: ("Chinedu Stores Ltd", 287_500, 20, 30), 1004: ("Mama Nkechi Provisions", 96_800, 33, 14),
    1005: ("Mama Nkechi Provisions", 64_000, 12, 14), 1006: ("Adebayo & Sons Enterprises", 1_250_000, 45, 30),
    1007: ("Adebayo & Sons Enterprises", 340_000, 8, 30), 1008: ("Blessed Hands Supermarket", 215_000, 38, 30),
    1009: ("Blessed Hands Supermarket", 128_400, 31, 30), 1010: ("Blessed Hands Supermarket", 77_000, 5, 30),
    1011: ("Zara Pharmacy Ltd", 520_000, 50, 30), 1012: ("Zara Pharmacy Ltd", 88_750, 22, 30),
    1013: ("Emeka Okeke Ventures", 615_300, 36, 30), 1014: ("Emeka Okeke Ventures", 142_000, 18, 30),
    1015: ("Fresh Basket Mart", 233_600, 29, 21), 1016: ("Fresh Basket Mart", 150_000, 15, 21),
    1017: ("Golden Gate Hotels Ltd", 980_000, 42, 30), 1018: ("Golden Gate Hotels Ltd", 410_500, 41, 30),
    1019: ("Golden Gate Hotels Ltd", 1_120_000, 95, 30), 1020: ("Hope Medical Store", 175_000, 34, 30),
    1021: ("Hope Medical Store", 175_000, 27, 30), 1022: ("Ikoyi Corner Shop", 58_900, 26, 14),
    1023: ("Ikoyi Corner Shop", 150_000, 10, 14), 1024: ("Joy Bakery & Cafe", 72_500, 30, 14),
    1025: ("Joy Bakery & Cafe", 49_250, 24, 14), 1026: ("Kano Traders Co", 300_000, 37, 30),
    1027: ("Kano Traders Co", 455_000, 70, 30), 1028: ("Mama Nkechi Provisions", 112_300, 110, 14),
    1029: ("Zara Pharmacy Ltd", 246_000, 75, 30), 1030: ("Ikoyi Corner Shop", 39_000, 65, 14),
    1031: ("Fresh Basket Mart", 318_000, 52, 21), 1032: ("Joy Bakery & Cafe", 95_000, 6, 14),
    1033: ("Emeka Okeke Ventures", 207_800, 3, 30), 1034: ("Chinedu Stores Ltd", 512_000, 2, 30),
    1035: ("Hope Medical Store", 66_400, 58, 30), 1036: ("Kano Traders Co", 128_000, 9, 30),
}

# (days before D, narration, credit naira, debit naira, expected invoices, situation)
CREDITS = [
    (30, "NIP TRF FRM CHINEDU STORES LTD/INV-1001/GTB/0123456789", 450_000, ["1001"], "invoice number quoted"),
    (29, "MOBILE TRF FROM MAMA NKECHI PROV", 96_800, ["1004"], "abbreviated name, exact amount"),
    (28, "TRANSFER FROM OLUWASEUN ADEBAYO/FBN", 1_250_000, ["1006"], "owner pays from personal account"),
    (27, "USSD/ZEN/BLESSED HANDS SUPERMKT", 343_400, ["1008", "1009"], "one transfer, two invoices"),
    (26, "NIP TRF FRM ZARA PHARMACY LTD PART PAYMT", 300_000, ["1029", "1011"],
     "part payment: oldest debt first"),
    (25, "TRF FRM CHINEDU STORE LTD INV 1002", 182_250, ["1002"], "typo in name + invoice number"),
    (24, "FT/ACCESS/EMEKA OKEKE VENT/0098812231", 615_300, ["1013"], "abbreviated company name"),
    (23, "NIP/OPAY/TUNDE BAKARE", 233_600, ["1015"], "owner name via fintech app"),
    (22, "GOLDEN GATE HOTELS LTD PYMT 1017 1018", 1_390_500, ["1017", "1018"], "bare invoice numbers, two invoices"),
    (21, "POS SETTLEMENT/WEB/2231998", 23_456.78, [], "card settlement, not a customer"),
    (20, "INTEREST CREDIT OCT 2026", 1_204.55, [], "bank interest"),
    (19, "NIP TRF FRM HOPE MEDICAL STORE", 175_000, ["1020"], "two invoices share the amount: oldest first"),
    (18, "TRANSFER FROM BISI LAWAL/UBA", 58_900, ["1022"], "owner name"),
    (17, "MB TRF JOY NWOSU/KUDA", 121_750, ["1024", "1025"], "owner pays two invoices at once"),
    (16, "NIP TRF FRM IBRAHIM SANI/JAIZ", 1_000_000, ["1036", "1026", "1027"], "overpayment"),
    (15, "TRF FRM AMARACHI OKORO", 287_500, ["1003"], "unknown payer, unique amount"),
    (14, "TRANSFER", 150_000, [], "no name, amount fits two customers: must not guess"),
    (13, "NIP TRF FRM ZAINAB MUSA", 88_750, ["1012"], "owner name"),
    (12, "NIP TRF FRM EMEKA OKEKE", 142_000, ["1014"], "company name without suffix"),
    (11, "NIP TRF FRM KOLA FOODS DISTRIBUTION LTD/OWN ACCT", 2_000_000, [], "transfer between own accounts"),
    (10, "REVERSAL/NIP/FAILED TRF 88123", 15_000, [], "reversal of a failed payment"),
    (9, "TRF FRM DR FEMI A./HOPE MED", 175_000, ["1021"], "messy name + duplicate amount"),
    (8, "PAYMENT FOR 20 CTNS INDOMIE - SUNNY GROCERS", 184_000, [], "not a customer on file"),
    (7, "NIP TRF FRM FRESH BASKET/1031", 318_000, ["1031"], "short name + bare invoice number"),
    (6, "NIP TRF FRM GOLDEN GATE HOTELS", 500_000, ["1019"], "part payment of an old debt"),
    (5, "MOBILE TRF IKOYI CORNER SHOP", 189_000, ["1030", "1023"], "two invoices, oldest is 65 days old"),
]
DEBITS = [
    (31, "SALARY NOV BATCH 1", 1_850_000), (25, "NIP TRF TO DANGOTE FLOUR MILLS", 3_400_000),
    (18, "SMS ALERT CHARGES", 1_200), (12, "DIESEL PURCHASE/POS", 420_000), (6, "LAGOS STATE LEVY", 75_000),
    (3, "COMMISSION ON TURNOVER", 9_845.30),
]


def main() -> None:
    with open(ROOT / "sample" / "invoices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["invoice_number", "customer", "amount", "issue_date", "due_date", "aliases", "email"])
        for num, (cust, amount, ago, terms) in INVOICES.items():
            issued = D - timedelta(days=ago)
            alias, email = CUSTOMERS[cust]
            w.writerow([f"INV-{num}", cust, f"{amount:,.2f}", issued.isoformat(),
                        (issued + timedelta(days=terms)).isoformat(), alias, email])

    rows = [(D - timedelta(days=d), n, c, None) for d, n, c, _, _ in CREDITS]
    rows += [(D - timedelta(days=d), n, None, a) for d, n, a in DEBITS]
    rows.sort(key=lambda r: r[0])
    balance = 4_210_000.00
    with open(ROOT / "sample" / "bank_statement.csv", "w", newline="") as f:
        f.write("Account Name: KOLA FOODS DISTRIBUTION LTD\nAccount Number: 0123456789\n"
                "Period: 07-Oct-2026 to 13-Nov-2026\n\n")
        w = csv.writer(f)
        w.writerow(["Trans Date", "Value Date", "Reference", "Narration", "Debit", "Credit", "Balance"])
        for i, (when, narration, credit, debit) in enumerate(rows, start=1):
            balance += (credit or 0) - (debit or 0)
            w.writerow([when.strftime("%d-%b-%Y"), when.strftime("%d-%b-%Y"), f"S{9_000_000 + i * 137}", narration,
                        f"{debit:,.2f}" if debit else "", f"{credit:,.2f}" if credit else "", f"{balance:,.2f}"])

    labels = [{"narration": n, "amount": c, "expected": exp, "situation": s} for _, n, c, exp, s in CREDITS]
    (ROOT / "evals" / "labels.json").write_text(json.dumps(labels, indent=1) + "\n")
    print(f"{len(INVOICES)} invoices, {len(CREDITS)} credits, {len(DEBITS)} debits")


if __name__ == "__main__":
    main()
