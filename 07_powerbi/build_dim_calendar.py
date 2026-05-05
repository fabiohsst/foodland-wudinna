"""
build_dim_calendar.py
Generates dim_calendar.csv covering 2025-01-01 to 2027-12-31.

Run from any directory — paths are relative to this script's location.
Output: ../07_powerbi/data/dim_calendar.csv
"""

import pandas as pd
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
ROOT         = SCRIPT_DIR.parent
HOLIDAYS_CSV = ROOT / "01_data" / "reference" / "sa_holidays_prophet.csv"
OUTPUT       = SCRIPT_DIR / "data" / "dim_calendar.csv"

# ── Date range ────────────────────────────────────────────────────────────────
start = "2025-01-01"
end   = "2027-12-31"

dates = pd.date_range(start, end, freq="D")
df = pd.DataFrame({"date": dates})

# ── Load SA public holidays ───────────────────────────────────────────────────
holidays = pd.read_csv(HOLIDAYS_CSV, parse_dates=["ds"])
holiday_map = dict(zip(holidays["ds"].dt.normalize(), holidays["holiday"]))

# ── Calendar attributes ───────────────────────────────────────────────────────
df["date_key"]      = df["date"].dt.strftime("%Y%m%d").astype(int)
df["year"]          = df["date"].dt.year
df["quarter"]       = df["date"].dt.quarter
df["month"]         = df["date"].dt.month
df["month_name"]    = df["date"].dt.strftime("%B")
df["week_of_year"]  = df["date"].dt.isocalendar().week.astype(int)
df["day_of_week"]   = df["date"].dt.dayofweek + 1   # 1=Mon … 7=Sun
df["day_name"]      = df["date"].dt.strftime("%A")
df["is_weekend"]    = df["day_of_week"].isin([6, 7]).astype(int)

# ── Holiday flags ─────────────────────────────────────────────────────────────
df["is_public_holiday"] = df["date"].isin(holiday_map.keys()).astype(int)
df["holiday_name"]      = df["date"].map(holiday_map).fillna("")

# ── Store open flag ───────────────────────────────────────────────────────────
# Open: Mon–Fri (1–5) and Saturday (6), closed Sunday (7) and public holidays
df["is_store_open"] = (
    (df["day_of_week"] <= 6) &          # Mon–Sat
    (df["is_public_holiday"] == 0)
).astype(int)

# ── Order and delivery flags ──────────────────────────────────────────────────
# Wednesday order → Friday delivery
# Friday order    → Tuesday delivery
df["is_order_day"]    = df["day_of_week"].isin([3, 5]).astype(int)   # Wed=3, Fri=5
df["is_delivery_day"] = df["day_of_week"].isin([2, 5]).astype(int)   # Tue=2, Fri=5
df["order_cycle"]     = df["day_of_week"].map({3: "Wed→Fri", 5: "Fri→Tue"}).fillna("")

# ── Column order ──────────────────────────────────────────────────────────────
col_order = [
    "date_key", "date", "year", "quarter", "month", "month_name",
    "week_of_year", "day_of_week", "day_name", "is_weekend",
    "is_public_holiday", "holiday_name",
    "is_store_open", "is_order_day", "is_delivery_day", "order_cycle",
]
df = df[col_order]

# ── Save ──────────────────────────────────────────────────────────────────────
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT, index=False)

print(f"dim_calendar saved → {OUTPUT}")
print(f"  Rows : {len(df):,}")
print(f"  Range: {df['date'].min().date()} → {df['date'].max().date()}")
print(f"  Store open days : {df['is_store_open'].sum():,}")
print(f"  Public holidays : {df['is_public_holiday'].sum():,}")
