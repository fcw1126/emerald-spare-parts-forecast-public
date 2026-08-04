# -*- coding: utf-8 -*-
"""Embed analysis.json into the dashboard HTML template -> dashboard.html"""
import json
import os

BASE = r"C:\Users\user\Desktop\pdf_1"
JSON_PATH = os.path.join(BASE, "output", "analysis.json")
TEMPLATE_PATH = os.path.join(BASE, "output", "dashboard_template.html")
OUT_PATH = os.path.join(BASE, "output", "dashboard.html")

with open(JSON_PATH, encoding="utf-8") as f:
    data_raw = f.read()

with open(TEMPLATE_PATH, encoding="utf-8") as f:
    template = f.read()

out = template.replace("__DATA_JSON__", data_raw)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(out)

print("wrote", OUT_PATH, os.path.getsize(OUT_PATH), "bytes")
