# -*- coding: utf-8 -*-
"""Combine transactions.csv + data.xlsx master list into per-item usage stats
and Min/Max stock recommendations, output analysis.json for the dashboard."""
import pandas as pd
import numpy as np
import json
import os

BASE = r"C:\Users\user\Desktop\pdf_1"
TX_CSV = os.path.join(BASE, "output", "transactions.csv")
MASTER_XLSX = os.path.join(BASE, "data.xlsx")
OUT_JSON = os.path.join(BASE, "output", "analysis.json")

TODAY = pd.Timestamp("2026-08-03")
CROSTON_ALPHA = 0.2  # smoothing constant for Croston/SBA intermittent-demand forecasting (typical range 0.1-0.3)
CROSTON_MIN_OCCURRENCES = 6  # need this many issue events before trusting the smoothed estimate — with
# only a few points the "smoothed" Z/P values are still close to the raw data (little averaging has
# happened yet), so a short gap between two events can extrapolate into a huge annualized rate
CROSTON_MAX_MULTIPLE = 2.0  # sanity cap: never let the smoothed forecast exceed N x the simple lifetime
# average — guards against a cluster of closely-spaced transactions (one busy month/project) dragging
# the smoothed interval down and inflating the rate, with no later data to pull it back afterward

tx = pd.read_csv(TX_CSV)
tx["date"] = pd.to_datetime(tx["date"], format="%d/%m/%Y", errors="coerce")
tx = tx.dropna(subset=["date"])

master = pd.read_excel(MASTER_XLSX, header=0)
master.columns = [c.strip() for c in master.columns]
master = master.rename(columns={
    "รหัส": "code",
    "ชื่อไทย": "name_th",
    "ชื่ออังกฤษ": "name_en",
    "Model": "model",
    "MachineName": "machine_name",
    "VendorName": "vendor_name",
    "MinimumStock": "min_stock",
    "MaximumStock": "max_stock",
    "TechnicianName": "technician",
    "หน่วยนับ": "unit",
    "กลุ่ม": "group",
    "Location": "location",
    "จำนวนคงเหลือล่าสุด (Stock On-Hand)": "stock_on_hand",
    "จำนวนคงเหลือรวมการเบิกที่รอจ่าย": "stock_incl_pending",
    "สถานะเปิดใช้งาน": "status",
})

records = []
for _, m in master.iterrows():
    code = str(m["code"]).strip()
    item_tx = tx[tx["item_code"] == code].sort_values("date")

    n_tx = len(item_tx)
    iss = item_tx[item_tx["iss_qty"].notna()]
    rec = item_tx[item_tx["rec_qty"].notna()]
    n_iss = len(iss)
    n_rec = len(rec)
    total_iss_qty = float(iss["iss_qty"].sum()) if n_iss else 0.0
    total_rec_qty = float(rec["rec_qty"].sum()) if n_rec else 0.0

    if n_tx > 0:
        first_date = item_tx["date"].min()
        last_date = item_tx["date"].max()
        span_days = max((TODAY - first_date).days, 1)
        span_years = span_days / 365.0
    else:
        first_date = None
        last_date = None
        span_days = 0
        span_years = 0

    # usage rate: qty issued per year
    # flat lifetime average (kept for comparison in the UI) treats every year of history equally,
    # which hides a rising/falling trend behind one number
    usage_per_year_flat = (total_iss_qty / span_years) if span_years > 0 else 0.0
    issues_per_year_flat = (n_iss / span_years) if span_years > 0 else 0.0

    # Croston's method (SBA variant): most of these parts are used rarely and irregularly —
    # "intermittent demand" in forecasting terms — which a plain average or a moving-window average
    # handles poorly (long quiet stretches drown out the signal, or a window lands on all-zero years).
    # Croston separates the series into two things and smooths each independently with its own
    # exponential average: how big each issue tends to be (Z), and how many days pass between issues
    # (P). The forecast rate is Z/P, corrected by the Syntetos-Boylan factor (1 - alpha/2) to remove
    # Croston's known upward bias. Smoothed P also becomes the fallback replenishment-cycle estimate.
    iss_dates = iss["date"].sort_values().tolist()
    iss_intervals = [(iss_dates[i+1] - iss_dates[i]).days for i in range(len(iss_dates)-1)]
    usage_per_year = usage_per_year_flat
    issues_per_year = issues_per_year_flat
    smoothed_iss_interval = None
    if n_iss >= CROSTON_MIN_OCCURRENCES:
        iss_sorted = iss.sort_values("date")
        sizes_all = iss_sorted["iss_qty"].tolist()
        sizes = sizes_all[1:]  # first occurrence has no preceding interval yet
        intervals = [max(d, 1) for d in iss_intervals]
        Z = sizes[0]
        P = intervals[0]
        for i in range(1, len(sizes)):
            Z = CROSTON_ALPHA * sizes[i] + (1 - CROSTON_ALPHA) * Z
            P = CROSTON_ALPHA * intervals[i] + (1 - CROSTON_ALPHA) * P
        sba_daily_rate = (1 - CROSTON_ALPHA / 2) * (Z / P)
        usage_per_year = sba_daily_rate * 365.0
        issues_per_year = 365.0 / P
        smoothed_iss_interval = P
        if usage_per_year_flat > 0:
            usage_per_year = min(usage_per_year, usage_per_year_flat * CROSTON_MAX_MULTIPLE)

    # average interval between consecutive REC events (replenishment cycle, days)
    rec_dates = rec["date"].sort_values().tolist()
    rec_intervals = [(rec_dates[i+1] - rec_dates[i]).days for i in range(len(rec_dates)-1)]
    avg_rec_interval = float(np.mean(rec_intervals)) if rec_intervals else None

    avg_iss_interval = float(np.mean(iss_intervals)) if iss_intervals else None

    avg_iss_qty_per_tx = (total_iss_qty / n_iss) if n_iss else 0.0
    avg_rec_qty_per_tx = (total_rec_qty / n_rec) if n_rec else 0.0

    daily_usage = usage_per_year / 365.0

    # --- usage frequency classification ---
    if n_iss == 0:
        freq_class = "從未領用"
    elif issues_per_year >= 4:
        freq_class = "高頻"
    elif issues_per_year >= 1.5:
        freq_class = "中頻"
    elif issues_per_year >= 0.4:
        freq_class = "低頻"
    else:
        freq_class = "極少使用"

    current_min = m["min_stock"] if pd.notna(m["min_stock"]) else None
    current_max = m["max_stock"] if pd.notna(m["max_stock"]) else None

    # --- recommendation logic ---
    # recommended Min (safety stock): cover usage during one replenishment cycle
    # cycle length: prefer observed avg interval between restocks (REC); fallback to Croston's
    # smoothed issue interval (P) which already discounts stale old gaps; last resort plain average
    if avg_rec_interval and avg_rec_interval > 0:
        cycle_days = avg_rec_interval
    elif smoothed_iss_interval and smoothed_iss_interval > 0:
        cycle_days = smoothed_iss_interval
    elif avg_iss_interval and avg_iss_interval > 0:
        cycle_days = avg_iss_interval
    else:
        cycle_days = None

    reco_min = None
    reco_max = None
    insufficient = (n_iss < 2 or span_years < 0.5)

    if insufficient:
        reco_min = current_min
        reco_max = current_max
    else:
        safety_factor = 1.3  # buffer for demand variability, since no lead-time data exists
        est_cycle = cycle_days if cycle_days else 90
        est_cycle = min(max(est_cycle, 14), 365)  # clamp to sane range 2wk~1yr
        raw_min = daily_usage * est_cycle * safety_factor
        reco_min = max(1, int(np.ceil(raw_min)))
        reco_max = reco_min + max(1, int(np.ceil(avg_iss_qty_per_tx if avg_iss_qty_per_tx > 0 else avg_rec_qty_per_tx)))

    # --- status: insufficient data always wins (a matching current==reco is not "confirmed OK",
    # it's "we don't know yet") — then classify on BOTH Min and Max deltas, not Min alone, since a
    # part can have a fine Min but a wildly over/under-sized Max (or vice versa)
    min_delta = None
    max_delta = None
    if insufficient:
        reco_status = "nodata"
    elif current_min is None:
        reco_status = "unset"
    else:
        min_delta = reco_min - current_min
        max_delta = (reco_max - current_max) if current_max is not None else None
        needs_min_up, needs_min_down = min_delta >= 1, min_delta <= -1
        needs_max_up = max_delta is not None and max_delta >= 1
        needs_max_down = max_delta is not None and max_delta <= -1
        any_up, any_down = (needs_min_up or needs_max_up), (needs_min_down or needs_max_down)
        if any_up and any_down:
            reco_status = "mixed"
        elif any_up:
            reco_status = "increase"
        elif any_down:
            reco_status = "decrease"
        else:
            reco_status = "ok"

    if reco_status == "nodata":
        reco_note = "歷史資料不足，維持現行設定" if current_min is not None else "資料不足，且尚未設定安全庫存"
    elif reco_status == "unset":
        reco_note = f"尚未設定安全庫存，建議新增 Min {reco_min} / Max {reco_max}"
    elif reco_status == "ok":
        reco_note = "現行設定合理"
    elif reco_status == "mixed":
        reco_note = f"建議調整範圍：Min {int(current_min)}→{reco_min}、Max {int(current_max)}→{reco_max}"
    elif reco_status == "increase":
        parts = []
        if min_delta >= 1: parts.append(f"Min {int(current_min)}→{reco_min}")
        if max_delta is not None and max_delta >= 1: parts.append(f"Max {int(current_max)}→{reco_max}")
        reco_note = "建議提高：" + "、".join(parts)
    else:  # decrease
        parts = []
        if min_delta <= -1: parts.append(f"Min {int(current_min)}→{reco_min}")
        if max_delta is not None and max_delta <= -1: parts.append(f"Max {int(current_max)}→{reco_max}")
        reco_note = "建議降低：" + "、".join(parts)

    history = []
    for _, r in item_tx.iterrows():
        if pd.notna(r["rec_qty"]):
            ttype, qty = "REC", float(r["rec_qty"])
        else:
            ttype, qty = "ISS", float(r["iss_qty"])
        history.append({
            "date": r["date"].strftime("%Y-%m-%d"),
            "type": ttype,
            "qty": qty,
            "balance": float(r["balance"]) if pd.notna(r["balance"]) else None,
            "doc_no": r["doc_no"] if pd.notna(r["doc_no"]) else None,
        })

    records.append({
        "code": code,
        "pdf_file": f"{code}.pdf",
        "name_th": m.get("name_th"),
        "name_en": m.get("name_en") if pd.notna(m.get("name_en")) else None,
        "model": m.get("model") if pd.notna(m.get("model")) else None,
        "vendor": m.get("vendor_name") if pd.notna(m.get("vendor_name")) else None,
        "group": m.get("group") if pd.notna(m.get("group")) else None,
        "location": m.get("location") if pd.notna(m.get("location")) else None,
        "unit": m.get("unit") if pd.notna(m.get("unit")) else None,
        "status": m.get("status") if pd.notna(m.get("status")) else None,
        "n_transactions": int(n_tx),
        "n_issues": int(n_iss),
        "n_receipts": int(n_rec),
        "total_issued_qty": total_iss_qty,
        "total_received_qty": total_rec_qty,
        "first_date": first_date.strftime("%Y-%m-%d") if first_date is not None else None,
        "last_date": last_date.strftime("%Y-%m-%d") if last_date is not None else None,
        "usage_per_year": round(usage_per_year, 2),
        "usage_per_year_flat": round(usage_per_year_flat, 2),
        "issues_per_year": round(issues_per_year, 2),
        "issues_per_year_flat": round(issues_per_year_flat, 2),
        "avg_rec_interval_days": round(avg_rec_interval, 1) if avg_rec_interval else None,
        "avg_iss_interval_days": round(avg_iss_interval, 1) if avg_iss_interval else None,
        "avg_iss_qty_per_tx": round(avg_iss_qty_per_tx, 2),
        "avg_rec_qty_per_tx": round(avg_rec_qty_per_tx, 2),
        "freq_class": freq_class,
        "current_min": current_min,
        "current_max": current_max,
        "reco_min": reco_min,
        "reco_max": reco_max,
        "reco_note": reco_note,
        "reco_status": reco_status,
        "insufficient": bool(insufficient),
        "min_delta": min_delta,
        "max_delta": max_delta,
        "stock_on_hand": m.get("stock_on_hand") if pd.notna(m.get("stock_on_hand")) else None,
        "history": history,
    })

df_out = pd.DataFrame(records).drop(columns=["history"])

# summary stats for dashboard header — driven by the same reco_status computed above,
# not re-derived from deltas, so it can never disagree with the per-item classification
status_counts = df_out["reco_status"].value_counts()

summary = {
    "total_items": len(df_out),
    "items_increase": int(status_counts.get("increase", 0)),
    "items_decrease": int(status_counts.get("decrease", 0)),
    "items_mixed": int(status_counts.get("mixed", 0)),
    "items_unset": int(status_counts.get("unset", 0)),
    "items_ok": int(status_counts.get("ok", 0)),
    "items_no_data": int(status_counts.get("nodata", 0)),
    "freq_distribution": df_out["freq_class"].value_counts().to_dict(),
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "items": records}, f, ensure_ascii=False, indent=0, default=str)

print("summary:", summary)
print("wrote", OUT_JSON)

# also write an xlsx for the user to inspect directly
xlsx_out = os.path.join(BASE, "output", "analysis_result.xlsx")
df_out.to_excel(xlsx_out, index=False)
print("wrote", xlsx_out)
