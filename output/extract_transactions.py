# -*- coding: utf-8 -*-
"""Parse every SP-*.pdf stock card in pdf_1/ and dump all transaction rows to transactions.csv"""
import pdfplumber
import glob
import os
import re
import csv

SRC_DIR = r"C:\Users\user\Desktop\pdf_1"
OUT_CSV = os.path.join(SRC_DIR, "output", "transactions.csv")

date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")

def parse_number(s):
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None

def extract_code_from_header(text):
    m = re.search(r"\u0e23\u0eb0\u0e2b\u0e31\u0e2a\s*:\s*(\S+)", text)
    if m:
        return m.group(1)
    return None

def extract_safety_max(text):
    safety = None
    maximum = None
    m = re.search(r"Safety Stock\s*:\s*(\d+(?:\.\d+)?)", text)
    if m:
        safety = float(m.group(1))
    m = re.search(r"Maximum Stock\s*:\s*(\d+(?:\.\d+)?)", text)
    if m:
        maximum = float(m.group(1))
    return safety, maximum

rows_out = []
errors = []

files = sorted(glob.glob(os.path.join(SRC_DIR, "*.pdf")))
print(f"Found {len(files)} pdf files")

for fpath in files:
    fname = os.path.basename(fpath)
    code_guess = os.path.splitext(fname)[0]
    try:
        with pdfplumber.open(fpath) as pdf:
            full_text = "\n".join([(p.extract_text() or "") for p in pdf.pages])
            code = extract_code_from_header(full_text) or code_guess
            safety, maximum = extract_safety_max(full_text)

            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 5:
                            continue
                        cell0 = (row[0] or "").strip()
                        if not date_re.match(cell0):
                            continue  # skip header / non-data rows
                        doc_no = (row[1] or "").strip()
                        rec_qty = parse_number(row[2])
                        iss_qty = parse_number(row[3])
                        balance = parse_number(row[4])
                        rows_out.append({
                            "item_code": code,
                            "source_file": fname,
                            "date": cell0,
                            "doc_no": doc_no,
                            "rec_qty": rec_qty,
                            "iss_qty": iss_qty,
                            "balance": balance,
                            "pdf_safety_stock": safety,
                            "pdf_maximum_stock": maximum,
                        })
    except Exception as e:
        errors.append((fname, str(e)))

print(f"Extracted {len(rows_out)} transaction rows")
print(f"Errors: {len(errors)}")
for f, e in errors:
    print("ERROR", f, e)

os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "item_code", "source_file", "date", "doc_no", "rec_qty", "iss_qty",
        "balance", "pdf_safety_stock", "pdf_maximum_stock"
    ])
    writer.writeheader()
    writer.writerows(rows_out)

print("Wrote", OUT_CSV)
