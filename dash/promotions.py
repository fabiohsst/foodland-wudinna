"""
dash/promotions.py — Promotions dashboard page (Phase 2)
Measures the revenue and GP impact of Wednesday Specials.
"""

import pandas as pd
import streamlit as st

from dash.common import C, load_sales

try:
    import plotly.express as px
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False

SPECIALS_LOG = __import__("pathlib").Path(__file__).parent.parent / \
               "01_data/operational/specials_this_week.csv"


def render():
    st.subheader("Promotions — Wednesday Specials Impact")

    sales = load_sales()

    # ── Check if we have enough specials history ──────────────────────────────
    if not SPECIALS_LOG.exists():
        _coming_soon()
        return

    specials_log = _load_specials_log()
    if specials_log.empty or len(specials_log) < 3:
        _coming_soon(
            note="Specials log found but fewer than 3 cycles recorded. "
                 "Keep logging after each Wednesday and this section will activate."
        )
        return

    if sales.empty:
        st.error("No sales data found.")
        return

    # ── Analysis ──────────────────────────────────────────────────────────────
    # Merge specials history with sales to compare special vs normal days
    sales["is_wednesday"] = sales["Date"].dt.dayofweek == 2  # Wed = 2

    special_names = set(specials_log["item_name"].str.upper())
    sales["is_special_item"] = sales["Name"].str.upper().isin(special_names)

    promo_days   = sales[sales["is_wednesday"] & sales["is_special_item"]]
    normal_days  = sales[~sales["is_wednesday"] & sales["is_special_item"]]

    if promo_days.empty or normal_days.empty:
        _coming_soon(note="Not enough matched sales on special days yet.")
        return

    avg_promo  = promo_days.groupby("Name")[["Revenue", "GP", "Qty"]].mean()
    avg_normal = normal_days.groupby("Name")[["Revenue", "GP", "Qty"]].mean()
    comparison = avg_promo.join(avg_normal, lsuffix="_promo", rsuffix="_normal",
                                how="inner")
    comparison["Qty Lift %"]  = (
        (comparison["Qty_promo"] - comparison["Qty_normal"]) /
        comparison["Qty_normal"].replace(0, pd.NA) * 100
    ).round(1)
    comparison["GP Δ ($)"] = (comparison["GP_promo"] - comparison["GP_normal"]).round(2)
    comparison = comparison.reset_index().sort_values("Qty Lift %", ascending=False)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Volume Uplift on Special Days**")
        if USE_PLOTLY:
            fig = px.bar(
                comparison.head(15).sort_values("Qty Lift %"),
                x="Qty Lift %", y="Name", orientation="h",
                color="Qty Lift %",
                color_continuous_scale=[[0, C["danger"]], [0.5, C["warning"]],
                                         [1, C["success"]]],
                labels={"Qty Lift %": "Volume change (%)", "Name": ""},
            )
            fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0),
                               coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("**GP Impact vs Normal Days**")
        disp = comparison[["Name", "Qty Lift %", "GP Δ ($)"]].head(15).copy()
        disp["Qty Lift %"] = disp["Qty Lift %"].map("{:+.1f}%".format)
        disp["GP Δ ($)"]   = disp["GP Δ ($)"].map("${:+.2f}".format)
        st.dataframe(disp, hide_index=True, use_container_width=True)
        st.caption("GP Δ = avg GP on special day − avg GP on normal day (per transaction).")


def _load_specials_log() -> pd.DataFrame:
    try:
        df = pd.read_csv(SPECIALS_LOG)
        if "item_name" not in df.columns and "Name" in df.columns:
            df = df.rename(columns={"Name": "item_name"})
        if "item_name" not in df.columns:
            return pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


def _coming_soon(note: str = ""):
    st.info(
        "**Phase 2 — Coming soon.**  \n\n"
        "This section will measure whether Wednesday Specials drive genuine volume uplift "
        "or just cannibalise margin. Once enough cycles are logged in "
        "`01_data/operational/specials_this_week.csv`, the analysis activates automatically.  \n\n"
        "**What you'll see:**  \n"
        "— Volume lift on special days vs the same item on normal days  \n"
        "— GP impact per special (did the margin hold?)  \n"
        "— A ranked 'worth running' list to guide future specials selection"
        + (f"  \n\n_{note}_" if note else "")
    )
