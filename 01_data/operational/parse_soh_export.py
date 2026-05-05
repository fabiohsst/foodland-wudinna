"""
parse_soh_export.py
Converts the POS Stock On Hand export (.xlsx) into stock_on_hand_v2.csv.

Writes ALL active items (derived from last 8 weeks of sales):
  - System-tracked items: pre-filled stock from the POS export (if within reliable range)
  - All other active items: Stock = 0, Source = 'manual'
    → Fill these in manually from the physical count before running the order model.

The Source column ('system' / 'manual') is used by:
  - SOH_Order_Analysis.ipynb  → colour-codes the stock count sheet
  - FruitVeg_Demand_Forecast.ipynb → ignores it (reads Name + Stock only)

Usage:
    cd 01_data/operational/
    python parse_soh_export.py                        # auto-detects most recent Stock_*.xlsx
    python parse_soh_export.py Stock_26.03.2026.xlsx  # explicit file
"""

import pandas as pd
import re
import sys
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
STOCK_MIN      =   1     # below this → not reliable (POS can't track loose items)
STOCK_MAX      = 500     # above this → clearly wrong
LOOKBACK_WEEKS =   8     # weeks of sales to define "active items"
MIN_QTY        =   5     # minimum total qty sold in lookback period to count as active

HERE = Path(__file__).parent               # 01_data/operational/
ROOT = HERE.parent.parent                  # foodland_wudinna/
OUTPUT = HERE / "stock_on_hand_v2.csv"

# db.py lives in the project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def norm(s: str) -> str:
    """Collapse embedded newlines and extra whitespace — matches POS export quirks."""
    return re.sub(r"\s+", " ", str(s)).strip()


# ── Find POS export file ───────────────────────────────────────────────────────
if len(sys.argv) > 1:
    input_file = Path(sys.argv[1])
    if not input_file.is_absolute():
        input_file = HERE / input_file
else:
    candidates = sorted(HERE.glob("Stock_*.xlsx"), reverse=True)
    if not candidates:
        raise FileNotFoundError(
            "No Stock_*.xlsx found in this folder. "
            "Pass the filename as an argument: python parse_soh_export.py Stock_DD.MM.YYYY.xlsx"
        )
    input_file = candidates[0]
    print(f"Auto-detected SOH file: {input_file.name}")


# ── Build active items list from recent sales ──────────────────────────────────
print("\nLoading sales from SQLite...")
from db import load_sales as _db_load_sales
sales = _db_load_sales()
sales = sales.rename(columns={"Qty": "Quantity"})

cutoff = sales["Date"].max() - pd.Timedelta(weeks=LOOKBACK_WEEKS)
recent = sales[sales["Date"] >= cutoff]

active_qty = (
    recent.groupby("Name")["Quantity"]
    .sum()
    .rename("total_qty")
)
active_items = sorted(active_qty[active_qty >= MIN_QTY].index.tolist())
print(f"Active items (last {LOOKBACK_WEEKS} weeks, qty ≥ {MIN_QTY}): {len(active_items)}")


# ── Parse POS SOH export ───────────────────────────────────────────────────────
print(f"Parsing POS export: {input_file.name}...")
raw = pd.read_excel(input_file, sheet_name="Page 1", header=5)
raw.columns = [norm(c) for c in raw.columns]

raw = raw.rename(columns={
    "Description"  : "Name",
    "Stock On Hand": "Stock",
})

raw["Name"]  = raw["Name"].apply(norm)
raw["Stock"] = pd.to_numeric(raw["Stock"], errors="coerce")

# Drop blank / summary rows
raw = raw[raw["Name"].str.len() > 2].copy()

# Reliable = stock within 1–500 (barcoded pre-pack items the POS actually tracks)
raw["reliable"] = (raw["Stock"] >= STOCK_MIN) & (raw["Stock"] <= STOCK_MAX)

# Build a lookup: name → stock (only reliable entries)
reliable_map: dict[str, int] = {
    row["Name"]: int(round(row["Stock"]))
    for _, row in raw[raw["reliable"]].iterrows()
}

# Stats on what was in the POS export
pos_total     = len(raw)
pos_reliable  = raw["reliable"].sum()
pos_excluded  = pos_total - pos_reliable


# ── Merge: active items + system stock ────────────────────────────────────────
rows = []
for item in active_items:
    if item in reliable_map:
        rows.append({"Name": item, "Stock": reliable_map[item], "Source": "system"})
    else:
        rows.append({"Name": item, "Stock": 0, "Source": "manual"})

out = pd.DataFrame(rows)
out.to_csv(OUTPUT, index=False)

# Also write snapshot to SQLite so the order app reads the latest SOH
# without needing the CSV file to be in place.
try:
    from db import append_stock_snapshot as _db_snap
    import datetime as _dt
    snap_date = _dt.date.today().isoformat()
    snap_rows = [
        {"name": r["Name"], "stock": r["Stock"], "source": r["Source"]}
        for r in rows
    ]
    inserted = _db_snap(snap_rows, snap_date)
    print(f"SQLite snapshot: {inserted} rows written (date: {snap_date})")
except Exception as e:
    print(f"Warning: SQLite snapshot skipped — {e}")

# ── Summary ───────────────────────────────────────────────────────────────────
system_count = (out["Source"] == "system").sum()
manual_count = (out["Source"] == "manual").sum()

print()
print(f"{'=' * 60}")
print(f"  POS export : {input_file.name}")
print(f"    Total rows in report : {pos_total}")
print(f"    Reliable (1–{STOCK_MAX})    : {pos_reliable}")
print(f"    Excluded             : {pos_excluded}  (loose/weighed or zero)")
print(f"{'─' * 60}")
print(f"  Output : {OUTPUT.name}")
print(f"    Total active items   : {len(out)}")
print(f"    System-tracked       : {system_count}  ← no manual count needed")
print(f"    Needs manual count   : {manual_count}  ← Stock = 0, fill in before ordering")
print(f"{'=' * 60}")
print()

# Show unreliable items that were in the POS export but excluded
unreliable = raw[~raw["reliable"]].copy()
neg_large  = unreliable[unreliable["Stock"] < -50]
neg_small  = unreliable[(unreliable["Stock"] < 0) & (unreliable["Stock"] >= -50)]
zero_stock = unreliable[unreliable["Stock"] == 0]
over_cap   = unreliable[unreliable["Stock"] > STOCK_MAX]

if len(neg_large):
    print(f"  ⚠  Invalid (system error — loose/weighed) : {len(neg_large)} items")
    for _, r in neg_large.iterrows():
        print(f"     {r['Name']:<55}  Stock: {r['Stock']:.0f}")
    print()

if len(neg_small):
    print(f"  ⚠  Slightly negative (minor drift) : {len(neg_small)} items")
    for _, r in neg_small.iterrows():
        print(f"     {r['Name']:<55}  Stock: {r['Stock']:.0f}")
    print()

if len(zero_stock):
    print(f"  ⚠  Stock = 0 in POS : {len(zero_stock)} items")
    for _, r in zero_stock.iterrows():
        print(f"     {r['Name']}")
    print()

if len(over_cap):
    print(f"  ⚠  Over cap (>{STOCK_MAX}) : {len(over_cap)} items — check manually")
    for _, r in over_cap.iterrows():
        print(f"     {r['Name']:<55}  Stock: {r['Stock']:.0f}")
    print()

print("=== System-tracked items written to stock_on_hand_v2.csv ===")
print(out[out["Source"] == "system"][["Name", "Stock"]].to_string(index=False))
print()
print("Next step: open stock_on_hand_v2.csv and fill in the Stock column")
print("for all 'manual' rows before running FruitVeg_Demand_Forecast.ipynb.")
