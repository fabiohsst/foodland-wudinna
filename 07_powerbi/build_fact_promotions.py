"""
build_fact_promotions.py
Produces fact_promotions.csv — one row per item × order cycle where a
special promotion or markdown was detected.

Source: prepacked_labelled.csv (already classified by Executive_EDA_Report.ipynb)

In Power BI this table connects to:
  dim_item     via item_key  (join on name)
  dim_calendar via date_key  (join on cycle_start date)

Output: ../07_powerbi/data/fact_promotions.csv
"""

import pandas as pd
import re
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
ROOT       = SCRIPT_DIR.parent
PREP_CSV   = ROOT / "01_data" / "reference" / "prepacked_labelled.csv"
DIM_ITEM   = SCRIPT_DIR / "data" / "dim_item.csv"
DIM_CAL    = SCRIPT_DIR / "data" / "dim_calendar.csv"
OUTPUT     = SCRIPT_DIR / "data" / "fact_promotions.csv"

def normalise_name(s):
    return re.sub(r"\s+", " ", str(s)).strip()

# ── Load ──────────────────────────────────────────────────────────────────────
prep = pd.read_csv(PREP_CSV, low_memory=False)
prep.columns = prep.columns.str.strip()
prep["Name"] = prep["Name"].apply(normalise_name)

dim_item = pd.read_csv(DIM_ITEM)
dim_cal  = pd.read_csv(DIM_CAL, parse_dates=["date"])

# ── Filter to flagged rows only ───────────────────────────────────────────────
flagged = prep[(prep["is_special"] == 1) | (prep["is_markdown"] == 1)].copy()

# ── Parse dates ───────────────────────────────────────────────────────────────
flagged["date"]        = pd.to_datetime(flagged["Date"], errors="coerce").dt.normalize()
flagged["cycle_start"] = pd.to_datetime(flagged["cycle_start"], errors="coerce").dt.normalize()

# ── Aggregate to item × cycle level ──────────────────────────────────────────
# Each row = one item in one order cycle (Wed–Tue), summarised
agg = (
    flagged.groupby(["Name", "cycle_start", "is_special", "is_markdown"])
    .agg(
        n_transactions = ("Lines",        "count"),
        total_qty      = ("Quantity",     "sum"),
        revenue_ex_gst = ("Sales Ex GST", "sum"),
        gp_dollars     = ("GP $",         "sum"),
        cycle_gp_pct   = ("GP_pct_num",   "median"),
        baseline_gp    = ("baseline_gp",  "first"),
        gp_gap         = ("gp_gap",       "mean"),
    )
    .reset_index()
    .rename(columns={"Name": "name"})
)

agg["gp_loss"]  = (agg["revenue_ex_gst"] * agg["baseline_gp"] / 100) - agg["gp_dollars"]
agg["gp_loss"]  = agg["gp_loss"].clip(lower=0).round(2)
agg["event_type"] = agg.apply(
    lambda r: "Special" if r["is_special"] == 1 else "Markdown", axis=1
)

agg["revenue_ex_gst"] = agg["revenue_ex_gst"].round(2)
agg["gp_dollars"]     = agg["gp_dollars"].round(2)
agg["cycle_gp_pct"]   = agg["cycle_gp_pct"].round(2)
agg["baseline_gp"]    = agg["baseline_gp"].round(2)
agg["gp_gap"]         = agg["gp_gap"].round(2)

# ── Join dim_item ─────────────────────────────────────────────────────────────
agg = agg.merge(dim_item[["item_key", "name", "sub_department", "abc_class"]],
                on="name", how="left")

# ── Join dim_calendar (on cycle_start date) ───────────────────────────────────
agg = agg.merge(
    dim_cal[["date", "date_key", "year", "month", "week_of_year"]].rename(
        columns={"date": "cycle_start", "date_key": "cycle_date_key"}),
    on="cycle_start", how="left"
)

# ── Column order ──────────────────────────────────────────────────────────────
fact = agg[[
    "cycle_date_key", "cycle_start", "item_key", "name",
    "sub_department", "abc_class",
    "year", "month", "week_of_year",
    "event_type", "is_special", "is_markdown",
    "n_transactions", "total_qty", "revenue_ex_gst",
    "gp_dollars", "cycle_gp_pct", "baseline_gp", "gp_gap", "gp_loss",
]].sort_values(["cycle_start", "name"]).reset_index(drop=True)

# ── Save ──────────────────────────────────────────────────────────────────────
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
fact.to_csv(OUTPUT, index=False)

n_specials  = (fact["event_type"] == "Special").sum()
n_markdowns = (fact["event_type"] == "Markdown").sum()
gp_loss_total = fact["gp_loss"].sum()

print(f"fact_promotions saved → {OUTPUT}")
print(f"  Total events   : {len(fact):,}")
print(f"  Specials       : {n_specials:,}")
print(f"  Markdowns      : {n_markdowns:,}")
print(f"  Total GP loss  : ${gp_loss_total:,.2f}")
print(f"  Unmapped items : {fact['item_key'].isna().sum():,}")
print(f"  Date range     : {fact['cycle_start'].min().date()} → {fact['cycle_start'].max().date()}")
