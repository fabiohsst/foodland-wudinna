"""
dash/common.py — Shared data loaders, helpers and design tokens
for the Foodland Wudinna Store Dashboard.
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent
WASTE_LOG    = ROOT / "05_waste/FruitVeg_Waste_Log_v2.xlsx"
STOCKOUT_LOG = ROOT / "05_waste/Stockout_Log.csv"
FORECAST_LOG = ROOT / "03_model/forecast_log.csv"
CALENDAR     = ROOT / "07_powerbi/data/dim_calendar.csv"

# db.py lives in the project root (parent of dash/)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Design tokens ──────────────────────────────────────────────────────────────
C = {
    "primary":   "#1A5276",
    "success":   "#1E8449",
    "warning":   "#E67E22",
    "danger":    "#C0392B",
    "neutral":   "#7F8C8D",
    "light":     "#F2F3F4",
}

SUBDEPT_COLORS = {
    "Fruit":       "#E74C3C",
    "Vegetables":  "#27AE60",
    "Potatoes":    "#E67E22",
    "Salads":      "#2980B9",
    "Other":       "#95A5A6",
}

DOW_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def delta_color(val: float) -> str:
    """Return 'normal' (green up), 'inverse' (red up), or 'off'."""
    return "normal" if val >= 0 else "inverse"


def fmt_currency(val: float) -> str:
    return f"${val:,.0f}"


def fmt_pct(val: float) -> str:
    return f"{val:.1f}%"


def gp_pct(rev: float, gp: float) -> float:
    return round(gp / rev * 100, 1) if rev > 0 else 0.0


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_sales() -> pd.DataFrame:
    """Load and normalise all available sales history from SQLite."""
    from db import load_sales as _db_load_sales
    return _db_load_sales()


@st.cache_data(show_spinner=False)
def load_calendar() -> pd.DataFrame:
    cal = pd.read_csv(CALENDAR)
    cal["date"] = pd.to_datetime(cal["date_key"].astype(str), format="%Y%m%d")
    return cal


@st.cache_data(show_spinner=False)
def load_waste() -> pd.DataFrame:
    if not WASTE_LOG.exists():
        return pd.DataFrame()
    xl = pd.read_excel(WASTE_LOG, sheet_name="Weekly Entry", header=1)
    xl.columns = ["Date", "Day", "Item Name", "Qty", "Unit",
                  "Price", "Action", "New Price", "Reason", "Waste Cost", "Notes"]
    xl = xl.dropna(subset=["Date", "Item Name"])
    xl = xl[xl["Date"] != "Date"]
    xl["Date"]       = pd.to_datetime(xl["Date"], errors="coerce")
    xl["Qty"]        = pd.to_numeric(xl["Qty"],        errors="coerce")
    xl["Waste Cost"] = pd.to_numeric(xl["Waste Cost"], errors="coerce")
    xl = xl.dropna(subset=["Date", "Qty", "Waste Cost"])
    xl["Item Name"]  = xl["Item Name"].apply(norm)
    xl["Week"]       = xl["Date"].dt.to_period("W").apply(lambda p: p.start_time)
    return xl


@st.cache_data(show_spinner=False)
def load_stockout() -> pd.DataFrame:
    if not STOCKOUT_LOG.exists():
        return pd.DataFrame()
    df = pd.read_csv(STOCKOUT_LOG, parse_dates=["report_date", "last_sold"])
    df["lost_revenue"] = pd.to_numeric(df["lost_revenue"], errors="coerce").fillna(0)
    df["lost_days"]    = pd.to_numeric(df["lost_days"],    errors="coerce").fillna(0)
    return df
