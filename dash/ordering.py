"""
dash/ordering.py — Ordering Accuracy dashboard page (Phase 3)
Tracks forecast accuracy cycle-by-cycle once forecast_log.csv accumulates.
"""

import pandas as pd
import streamlit as st

from dash.common import C, FORECAST_LOG, load_sales

try:
    import plotly.express as px
    import plotly.graph_objects as go
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False

MIN_CYCLES = 4   # minimum cycles before showing analysis


def _wmape(actual: pd.Series, predicted: pd.Series) -> float:
    mask = actual > 0
    if mask.sum() == 0:
        return float("nan")
    return (
        (actual[mask] - predicted[mask]).abs().sum() /
        actual[mask].sum() * 100
    )


def render():
    st.subheader("Ordering & Forecast Accuracy")

    if not FORECAST_LOG.exists():
        _coming_soon("Forecast log not found — generate at least one order sheet first.")
        return

    log = pd.read_csv(FORECAST_LOG, parse_dates=["order_date", "delivery_date"])
    n_cycles = log["order_date"].nunique()

    if n_cycles < MIN_CYCLES:
        _coming_soon(
            f"{n_cycles} cycle(s) logged so far — "
            f"analysis activates after {MIN_CYCLES}."
        )
        return

    sales = load_sales()
    if sales.empty:
        st.error("No sales data found.")
        return

    # ── Build actuals by matching sales to forecast cycles ───────────────────
    # For each forecast cycle, sum actuals between delivery_date and next delivery
    cycles = (
        log.groupby(["order_date", "order_type", "delivery_date"])
        .size().reset_index(name="items")
        .sort_values("delivery_date")
    )
    cycles["next_delivery"] = cycles["delivery_date"].shift(-1)

    results = []
    for _, cy in cycles.dropna(subset=["next_delivery"]).iterrows():
        cy_log = log[
            (log["order_date"] == cy["order_date"]) &
            (log["order_type"] == cy["order_type"])
        ][["item_name", "predicted_qty"]].copy()

        actuals = sales[
            (sales["Date"] >= cy["delivery_date"]) &
            (sales["Date"] <  cy["next_delivery"])
        ].groupby("Name")["Qty"].sum().reset_index()
        actuals.columns = ["item_name", "actual_qty"]

        merged = cy_log.merge(actuals, on="item_name", how="inner")
        if merged.empty:
            continue

        wmape = _wmape(merged["actual_qty"], merged["predicted_qty"])
        bias  = (
            (merged["predicted_qty"].sum() - merged["actual_qty"].sum()) /
            merged["actual_qty"].sum() * 100
            if merged["actual_qty"].sum() > 0 else float("nan")
        )
        results.append({
            "order_date":    cy["order_date"],
            "order_type":    cy["order_type"],
            "delivery_date": cy["delivery_date"],
            "items_matched": len(merged),
            "WMAPE":         round(wmape, 1),
            "Bias %":        round(bias, 1),
        })

    if not results:
        _coming_soon("Cycles logged but actuals not yet available for comparison.")
        return

    perf = pd.DataFrame(results).sort_values("delivery_date")
    perf["label"] = perf["delivery_date"].dt.strftime("%d %b")

    # ── KPI row ───────────────────────────────────────────────────────────────
    avg_wmape = perf["WMAPE"].mean()
    avg_bias  = perf["Bias %"].mean()
    n_shown   = len(perf)
    target_wmape = 35.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Avg WMAPE", f"{avg_wmape:.1f}%",
              help="Lower is better. Target: < 35%")
    k2.metric("vs Target", f"{avg_wmape - target_wmape:+.1f}pp",
              delta_color="inverse" if avg_wmape > target_wmape else "normal")
    k3.metric("Avg Bias",  f"{avg_bias:+.1f}%",
              help="+ve = over-ordering, −ve = under-ordering. Target: ±5%")
    k4.metric("Cycles Analysed", n_shown)

    st.divider()

    # ── WMAPE trend ───────────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**WMAPE per Cycle**")
        if USE_PLOTLY:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=perf["label"], y=perf["WMAPE"],
                marker_color=[
                    C["success"] if v <= target_wmape else C["warning"]
                    for v in perf["WMAPE"]
                ],
                name="WMAPE",
            ))
            fig.add_hline(y=target_wmape, line_dash="dash",
                          line_color=C["neutral"],
                          annotation_text=f"{target_wmape}% target")
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown("**Ordering Bias per Cycle**")
        if USE_PLOTLY:
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=perf["label"], y=perf["Bias %"],
                marker_color=[
                    C["warning"] if v > 5 else C["danger"] if v < -5 else C["success"]
                    for v in perf["Bias %"]
                ],
            ))
            fig2.add_hline(y=0,  line_color=C["neutral"], line_width=1)
            fig2.add_hline(y=5,  line_dash="dot", line_color=C["warning"])
            fig2.add_hline(y=-5, line_dash="dot", line_color=C["warning"])
            fig2.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_ticksuffix="%")
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Per-item accuracy (latest cycle) ─────────────────────────────────────
    st.markdown("**Item-Level Accuracy — Most Recent Cycle**")
    latest_cy = cycles.sort_values("delivery_date").dropna(
        subset=["next_delivery"]).iloc[-1]

    cy_log_latest = log[
        (log["order_date"] == latest_cy["order_date"]) &
        (log["order_type"] == latest_cy["order_type"])
    ][["item_name", "predicted_qty"]].copy()

    actuals_latest = sales[
        (sales["Date"] >= latest_cy["delivery_date"]) &
        (sales["Date"] <  latest_cy["next_delivery"])
    ].groupby("Name")["Qty"].sum().reset_index()
    actuals_latest.columns = ["item_name", "actual_qty"]

    item_acc = cy_log_latest.merge(actuals_latest, on="item_name", how="inner")
    item_acc["Error %"] = (
        (item_acc["predicted_qty"] - item_acc["actual_qty"]) /
        item_acc["actual_qty"].replace(0, pd.NA) * 100
    ).round(1)
    item_acc = item_acc.dropna(subset=["Error %"]).sort_values(
        "Error %", key=abs, ascending=False
    )

    disp = item_acc.head(20).copy()
    disp["predicted_qty"] = disp["predicted_qty"].round(1)
    disp["actual_qty"]    = disp["actual_qty"].round(1)
    disp["Error %"]       = disp["Error %"].map("{:+.1f}%".format)
    disp.columns = ["Item", "Predicted", "Actual", "Error %"]
    st.dataframe(disp, hide_index=True, use_container_width=True)
    st.caption("+ve Error = over-ordered, −ve = under-ordered. Sorted by absolute error.")


def _coming_soon(note: str = ""):
    st.info(
        "**Phase 3 — Coming soon.**  \n\n"
        "This section compares what the model predicted against what actually sold, "
        "cycle by cycle. It will show WMAPE trend, ordering bias, and the items the "
        "model consistently gets wrong.  \n\n"
        "**What activates it:** The Order Sheet Generator already logs every forecast "
        "to `03_model/forecast_log.csv`. Once **4 completed cycles** are recorded "
        "(prediction + actuals from sales CSV), this section activates automatically."
        + (f"  \n\n_{note}_" if note else "")
    )
