"""
panel.py — Fruit & Veg Performance Panel
Foodland Wudinna

Tracks sales performance and stockout events over time.
Run with:  streamlit run panel.py --server.port 8505
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@st.cache_data(show_spinner=False)
def load_sales() -> pd.DataFrame:
    """Load sales from SQLite via db.py, adding legacy column aliases."""
    from db import load_sales as _db_load
    df = _db_load()
    if df.empty:
        return df
    # Aliases for columns that differ between db.py output and this app's usage
    df["Quantity"]             = df["Qty"]
    df["Sub Department Name"]  = df["SubDept"]
    return df


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="F&V Performance Panel",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Fruit & Veg — Performance Panel")
st.caption("Foodland Wudinna")
st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────
sales = load_sales()
if sales.empty:
    st.warning("No sales data found — revenue and GP metrics will be unavailable.")

# ── Date range filter ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    if not sales.empty:
        min_date = sales["Date"].min().date()
        max_date = sales["Date"].max().date()
        date_from, date_to = st.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        st.divider()
        st.caption(
            f"Sales data: **{len(sales):,}** records  \n"
            f"{sales['Date'].min().strftime('%d %b %Y')} → {sales['Date'].max().strftime('%d %b %Y')}"
        )
    else:
        date_from = date_to = None

# Apply filter
if not sales.empty and date_from and date_to:
    s = sales[
        (sales["Date"] >= pd.Timestamp(date_from)) &
        (sales["Date"] <= pd.Timestamp(date_to))
    ].copy()
else:
    s = sales.copy() if not sales.empty else pd.DataFrame()

# Chart helper
try:
    import plotly.express as px
    import plotly.graph_objects as go
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — SALES & GP PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Sales & Gross Profit")

if s.empty:
    st.info("No sales data available for the selected period.")
else:
    weekly_sales = (
        s.groupby("Week")
        .agg(Revenue=("Revenue", "sum"), Cost=("Cost", "sum"), GP=("GP", "sum"), Qty=("Quantity", "sum"))
        .reset_index()
        .sort_values("Week")
    )
    weekly_sales["GP %"] = (weekly_sales["GP"] / weekly_sales["Revenue"].replace(0, np.nan) * 100).round(1)

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Weekly Revenue**")
        if USE_PLOTLY:
            fig4 = px.bar(
                weekly_sales, x="Week", y="Revenue",
                labels={"Revenue": "$", "Week": ""},
                color_discrete_sequence=["#2E86AB"],
            )
            fig4.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="$",
            )
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.line_chart(weekly_sales.set_index("Week")["Revenue"], height=300)

    with col_r:
        st.markdown("**Weekly Gross Profit %**")
        if USE_PLOTLY:
            fig5 = go.Figure()
            fig5.add_trace(go.Scatter(
                x=weekly_sales["Week"], y=weekly_sales["GP %"],
                mode="lines+markers", name="GP %",
                line=dict(color="#27AE60", width=2),
                marker=dict(size=6),
            ))
            fig5.add_hline(
                y=30, line_dash="dash", line_color="grey",
                annotation_text="30% target", annotation_position="bottom right"
            )
            fig5.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="GP %", yaxis_ticksuffix="%",
            )
            st.plotly_chart(fig5, use_container_width=True)
        else:
            st.line_chart(weekly_sales.set_index("Week")[["GP %"]], height=300)

    # Summary table
    st.markdown("**Weekly Summary**")
    summary_display = weekly_sales[["Week", "Revenue", "GP %", "Qty"]].copy()
    summary_display["Week"]    = summary_display["Week"].dt.strftime("w/c %d %b")
    summary_display["Revenue"] = summary_display["Revenue"].map("${:,.2f}".format)
    summary_display["GP %"]    = summary_display["GP %"].map("{:.1f}%".format)
    summary_display["Qty"]     = summary_display["Qty"].map("{:,.0f}".format)
    summary_display.columns    = ["Week", "Revenue", "GP %", "Units Sold"]
    st.dataframe(summary_display, hide_index=True, use_container_width=True)

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — LOST SALES (STOCKOUT TRACKER)
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Lost Sales — Stockout Events")

STOCKOUT_LOG = ROOT / "05_waste/Stockout_Log.csv"

if not STOCKOUT_LOG.exists():
    st.info(
        "No stockout data yet.  \n"
        "**To populate this section:** drag your SOH export onto **Launch Stockout Detector.bat** "
        "after each order cycle. The script identifies zero-stock active items, counts lost trading "
        "days until the next delivery, and appends estimates to `05_waste/Stockout_Log.csv`."
    )
else:
    @st.cache_data(show_spinner=False)
    def load_stockout_log() -> pd.DataFrame:
        df = pd.read_csv(STOCKOUT_LOG,
                         parse_dates=["report_date", "last_sold", "next_delivery"])
        df["lost_revenue"] = pd.to_numeric(df["lost_revenue"], errors="coerce").fillna(0)
        df["lost_days"]    = pd.to_numeric(df["lost_days"],    errors="coerce").fillna(0)
        df["daily_qty"]    = pd.to_numeric(df["daily_qty"],    errors="coerce").fillna(0)
        df["avg_price"]    = pd.to_numeric(df["avg_price"],    errors="coerce").fillna(0)
        return df

    stkout = load_stockout_log()

    # Apply same date filter
    if date_from and date_to:
        stkout_filtered = stkout[
            (stkout["report_date"] >= pd.Timestamp(date_from)) &
            (stkout["report_date"] <= pd.Timestamp(date_to))
        ]
    else:
        stkout_filtered = stkout

    if stkout_filtered.empty:
        st.caption("No stockout events in the selected date range.")
    else:
        total_lost   = stkout_filtered["lost_revenue"].sum()
        n_events     = len(stkout_filtered)
        n_items      = stkout_filtered["item_name"].nunique()
        avg_days_out = stkout_filtered["lost_days"].mean()
        n_reports    = stkout_filtered["report_date"].nunique()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Est. Lost Revenue", f"${total_lost:,.2f}",
                  help="Avg daily qty × lost trading days × avg sell price")
        k2.metric("Stockout Events",   n_events,
                  help="Each item × SOH report = one event")
        k3.metric("Unique Items",      n_items)
        k4.metric("Avg Days Out",      f"{avg_days_out:.1f}",
                  help="Trading days from last sale to next scheduled delivery")

        st.caption(
            f"Based on {n_reports} SOH report(s). "
            "Lost revenue = avg daily sales (last 8 wks) × lost trading days × avg sell price. "
            "Industry benchmark: stockout rate < 5%."
        )

        col_chart, col_table = st.columns([1, 1])

        item_summary = (
            stkout_filtered.groupby("item_name")
            .agg(
                lost_revenue=("lost_revenue", "sum"),
                lost_days=("lost_days",        "sum"),
                events=("report_date",          "count"),
            )
            .sort_values("lost_revenue", ascending=False)
            .reset_index()
        )

        top_n = min(12, len(item_summary))

        with col_chart:
            st.markdown(f"**Top {top_n} Items — Estimated Lost Revenue ($)**")
            top = item_summary.head(top_n)
            if USE_PLOTLY:
                fig_so = px.bar(
                    top.sort_values("lost_revenue"),
                    x="lost_revenue", y="item_name",
                    orientation="h",
                    labels={"lost_revenue": "Est. Lost ($)", "item_name": ""},
                    color="lost_revenue",
                    color_continuous_scale="Oranges",
                )
                fig_so.update_layout(
                    height=420, margin=dict(l=0, r=0, t=10, b=0),
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig_so, use_container_width=True)
            else:
                st.dataframe(
                    top[["item_name", "lost_revenue"]].sort_values("lost_revenue", ascending=False),
                    hide_index=True, use_container_width=True,
                )

        with col_table:
            st.markdown("**Event Detail**")
            detail = stkout_filtered[[
                "report_date", "item_name", "last_sold",
                "lost_days", "daily_qty", "avg_price", "lost_revenue",
            ]].copy()
            detail["report_date"]  = detail["report_date"].dt.strftime("%d %b %Y")
            detail["last_sold"]    = detail["last_sold"].dt.strftime("%d %b %Y")
            detail["lost_revenue"] = detail["lost_revenue"].map("${:.2f}".format)
            detail["avg_price"]    = detail["avg_price"].map("${:.2f}".format)
            detail["daily_qty"]    = detail["daily_qty"].round(2)
            detail.columns = [
                "SOH Date", "Item", "Last Sold",
                "Days Out", "Daily Qty", "Avg Price", "Est. Loss",
            ]
            st.dataframe(
                detail.sort_values("Est. Loss", ascending=False),
                hide_index=True, use_container_width=True, height=420,
            )

        if n_reports > 1:
            st.markdown("**Lost Revenue by SOH Report Date**")
            trend = (
                stkout_filtered.groupby("report_date")["lost_revenue"]
                .sum().reset_index().sort_values("report_date")
            )
            trend["label"] = trend["report_date"].dt.strftime("%d %b")
            if USE_PLOTLY:
                fig_trend = px.bar(
                    trend, x="label", y="lost_revenue",
                    labels={"lost_revenue": "Est. Lost ($)", "label": ""},
                    color_discrete_sequence=["#E67E22"],
                )
                fig_trend.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.bar_chart(trend.set_index("label")["lost_revenue"])

# ── Benchmarks sidebar ────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("**Industry Benchmarks**")
    st.markdown("""
| Metric | Target |
|---|---|
| GP % (F&V) | > 30% |
| Stockout Rate | < 5% |
""")
    st.caption("Source: AFGC / ECR Europe fresh produce benchmarks")
