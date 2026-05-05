"""
build_fact_sales.py
Processes all POS CSV exports in 01_data/raw/ and writes a clean fact_sales.csv.

Designed to be re-run whenever a new CSV is exported from the POS system.
Each run rebuilds fact_sales.csv in full (idempotent — safe to run repeatedly).

Output: ../07_powerbi/data/fact_sales.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
ROOT       = SCRIPT_DIR.parent
RAW_DIR    = ROOT / "01_data" / "raw"
DIM_CAL    = SCRIPT_DIR / "data" / "dim_calendar.csv"
DIM_ITEM   = SCRIPT_DIR / "data" / "dim_item.csv"
OUTPUT     = SCRIPT_DIR / "data" / "fact_sales.csv"

# ── Load dimension tables ─────────────────────────────────────────────────────
dim_cal  = pd.read_csv(DIM_CAL,  parse_dates=["date"])
dim_item = pd.read_csv(DIM_ITEM)

# ── Column mapping from POS export ────────────────────────────────────────────
# Maps raw column names → standardised names (handles both 2025 and 2026 headers)
COL_MAP = {
    "Date"            : "date_raw",
    "Name"            : "name",
    "APN"             : "apn_raw",
    "Quantity"        : "quantity",
    "Sales Ex GST"    : "sales_ex_gst",
    "Sales Inc GST"   : "sales_inc_gst",
    "Cost Ex GST"     : "cost_ex_gst",
    "GP $"            : "gp_dollars",
    "GP %"            : "gp_pct",
    "Lines"           : "lines",
    "Sub Department Name": "sub_department_raw",   # present in 2026, optional
}

EXCLUDE_NAMES = ["FRUIT AND VEG", "REDUCED FRUIT"]   # catch-all / markdown rows

# ── Read and stack all CSVs ───────────────────────────────────────────────────
raw_files = sorted(RAW_DIR.glob("sales_fruit_*.csv"))
if not raw_files:
    raise FileNotFoundError(f"No sales_fruit_*.csv files found in {RAW_DIR}")

frames = []
for f in raw_files:
    df = pd.read_csv(f, low_memory=False)
    df.columns = df.columns.str.strip()
    df["_source_file"] = f.name
    frames.append(df)
    print(f"  Loaded {f.name}  ({len(df):,} rows)")

raw = pd.concat(frames, ignore_index=True)
print(f"  Combined: {len(raw):,} rows from {len(raw_files)} file(s)\n")

# ── Rename to standard columns ────────────────────────────────────────────────
rename = {k: v for k, v in COL_MAP.items() if k in raw.columns}
raw = raw.rename(columns=rename)

# ── Normalise item names (POS exports embed literal \n inside names) ──────────
# Replace any whitespace run (including \n, \r, \t) with a single space, then strip
raw["name"] = (
    raw["name"]
    .astype(str)
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
)

# ── Parse date ────────────────────────────────────────────────────────────────
raw["date"] = pd.to_datetime(raw["date_raw"], errors="coerce").dt.normalize()

# ── Coerce numeric columns ────────────────────────────────────────────────────
for col in ["quantity", "sales_ex_gst", "sales_inc_gst", "cost_ex_gst", "gp_dollars", "gp_pct", "lines"]:
    if col in raw.columns:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")

# ── Exclusions ────────────────────────────────────────────────────────────────
# 1. Rows without a usable date
# 2. Catch-all / markdown rows
excl_mask = (
    raw["date"].isna() |
    raw["name"].str.upper().str.contains("|".join(EXCLUDE_NAMES), na=False)
)
excluded = excl_mask.sum()
raw = raw[~excl_mask].copy()

# ── Deduplicate ───────────────────────────────────────────────────────────────
# The POS can produce duplicate rows if the same file is exported twice.
# Key uniqueness: date + name + quantity + sales_ex_gst
dup_mask = raw.duplicated(subset=["date", "name", "quantity", "sales_ex_gst"], keep="first")
dupes_removed = dup_mask.sum()
raw = raw[~dup_mask].copy()

# ── Join dim_calendar ─────────────────────────────────────────────────────────
raw = raw.merge(
    dim_cal[["date", "date_key", "day_of_week", "day_name", "week_of_year",
             "month", "year", "is_public_holiday", "is_store_open"]],
    on="date", how="left"
)

# ── Join dim_item ─────────────────────────────────────────────────────────────
raw = raw.merge(
    dim_item[["item_key", "name", "sub_department", "abc_class"]],
    on="name", how="left"
)
unmapped_items = raw["item_key"].isna().sum()

# ── Derive gross margin fields ────────────────────────────────────────────────
raw["gp_pct"] = raw["gp_pct"].clip(-999, 100)   # guard against data anomalies

# ── Select and order output columns ──────────────────────────────────────────
fact = raw[[
    "date_key", "date", "item_key", "name",
    "sub_department", "abc_class",
    "day_of_week", "day_name", "week_of_year", "month", "year",
    "is_public_holiday", "is_store_open",
    "quantity", "sales_ex_gst", "sales_inc_gst",
    "cost_ex_gst", "gp_dollars", "gp_pct", "lines",
    "_source_file",
]].copy()

fact = fact.rename(columns={"_source_file": "source_file"})
fact = fact.sort_values(["date", "name"]).reset_index(drop=True)

# ── Save ──────────────────────────────────────────────────────────────────────
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
fact.to_csv(OUTPUT, index=False)

print(f"fact_sales saved → {OUTPUT}")
print(f"  Final rows        : {len(fact):,}")
print(f"  Date range        : {fact['date'].min().date()} → {fact['date'].max().date()}")
print(f"  Unique items      : {fact['name'].nunique():,}")
print(f"  Unique dates      : {fact['date'].nunique():,}")
print(f"  Excluded rows     : {excluded:,}  (catch-alls, bad dates)")
print(f"  Duplicates removed: {dupes_removed:,}")
print(f"  Unmapped items    : {unmapped_items:,}  (not in dim_item — check item_reference.csv)")
print(f"\n  Revenue 2025: ${fact[fact['year']==2025]['sales_ex_gst'].sum():,.2f}")
print(f"  Revenue 2026: ${fact[fact['year']==2026]['sales_ex_gst'].sum():,.2f}")
