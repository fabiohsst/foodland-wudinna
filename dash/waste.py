"""
dash/waste.py — Waste & Operations dashboard page
Waste cost trends, top offenders, waste rate, stockout summary.
"""

import numpy as np
import pandas as pd
import streamlit as st

from dash.common import (
    C, fmt_currency, fmt_pct,
    load_sales, load_waste, load_stockout,
)

try:
    import plotly.express as px
    import plotly.graph_objects as go
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False


def render():
    waste   = load_waste()
    sales   = load_sales()
    stockout = load_stockout()

    if waste.empty:
        st.error(
            "Waste log not found at `05_waste/FruitVeg_Waste_Log_v2.xlsx`. "
            "Add entries to the log to activate this section."
        )
        return

    # ── Sidebar filters ───────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Filters")
        min_d = waste["Date"].min().date()
        max_d = waste["Date"].max().date()
        date_from, date_to = st.date_input(
            "Date range",
            value=(min_d, max_d),
            min_value=min_d, max_value=max_d,
        )
        actions = sorted(waste["Action"].dropna().unique())
        action_filter = st.multiselect("Action", actions, default=actions)
        st.divider()
        st.caption(
            f"Waste log: **{len(waste)}** entries  \n"
            f"{min_d.strftime('%d %b %Y')} → {max_d.strftime('%d %b %Y')}"
        )

    w = waste[
        (waste["Date"] >= pd.Timestamp(date_from)) &
        (waste["Date"] <= pd.Timestamp(date_to)) &
        (waste["Action"].isin(action_filter))
    ].copy()

    s = sales[
        (sales["Date"] >= pd.Timestamp(date_from)) &
        (sales["Date"] <= pd.Timestamp(date_to))
    ] if not sales.empty else pd.DataFrame()

    if w.empty:
        st.info("No waste entries for the selected filters.")
        return

    # ── KPI cards ─────────────────────────────────────────────────────────────
    st.subheader("Waste Summary")

    total_cost   = w["Waste Cost"].sum()
    binned_cost  = w.loc[w["Action"] == "Binned",  "Waste Cost"].sum()
    reduced_cost = w.loc[w["Action"] == "Reduced", "Waste Cost"].sum()
    n_days       = max((pd.Timestamp(date_to) - pd.Timestamp(date_from)).days + 1, 1)
    daily_avg    = total_cost / n_days

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Waste Cost", fmt_currency(total_cost))
    k2.metric("Binned",           fmt_currency(binned_cost),
              help="Full cost-price loss — items thrown away")
    k3.metric("Reduced / MD",     fmt_currency(reduced_cost),
              help="Cost loss on markdowns: Qty × max(cost − new price, 0)")
    k4.metric("Daily Average",    fmt_currency(daily_avg))

    if not s.empty:
        rev = s["Revenue"].sum()
        waste_pct = total_cost / rev * 100 if rev > 0 else 0
        colour = C["success"] if waste_pct < 5 else C["warning"] if waste_pct < 8 else C["danger"]
        k5.metric("Waste / Revenue", fmt_pct(waste_pct),
                  help="Target: < 5%")
    else:
        k5.metric("Waste / Revenue", "—")

    st.divider()

    # ── Waste trend + breakdown ───────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    weekly_w = (
        w.groupby(["Week", "Action"])["Waste Cost"]
        .sum().reset_index().sort_values("Week")
    )
    weekly_w["label"] = weekly_w["Week"].dt.strftime("w/c %d %b")

    with col_left:
        st.markdown("**Weekly Waste Cost by Action**")
        if USE_PLOTLY:
            fig = px.bar(
                weekly_w, x="label", y="Waste Cost", color="Action",
                labels={"Waste Cost": "$", "label": ""},
                color_discrete_map={
                    "Binned":   C["danger"],
                    "Reduced":  C["warning"],
                    "Stir Fry": C["success"],
                    "Donated":  "#3498DB",
                },
                barmode="stack",
            )
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               legend=dict(orientation="h", y=1.05))
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            pivot = weekly_w.pivot(
                index="label", columns="Action", values="Waste Cost"
            ).fillna(0)
            st.bar_chart(pivot, height=280)

    reason_summary = (
        w.groupby("Reason")["Waste Cost"]
        .sum().sort_values(ascending=False).reset_index()
    )

    with col_right:
        st.markdown("**Waste Cost by Reason**")
        if USE_PLOTLY:
            fig2 = px.pie(
                reason_summary, values="Waste Cost", names="Reason",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig2.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               legend=dict(orientation="h", y=-0.2))
            fig2.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.dataframe(reason_summary, hide_index=True, use_container_width=True)

    st.divider()

    # ── Top offenders ─────────────────────────────────────────────────────────
    st.subheader("Top Offenders")

    item_waste = (
        w.groupby("Item Name")
        .agg(Waste_Cost=("Waste Cost", "sum"),
             Waste_Qty=("Qty",         "sum"),
             Events=("Date",           "count"))
        .sort_values("Waste_Cost", ascending=False)
        .reset_index()
    )

    if not s.empty:
        item_sales = (
            s.groupby("Name")["Qty"].sum().reset_index()
            .rename(columns={"Name": "Item Name", "Qty": "Sales_Qty"})
        )
        item_waste = item_waste.merge(item_sales, on="Item Name", how="left")
        item_waste["Sales_Qty"] = item_waste["Sales_Qty"].fillna(0)
        total_thru = item_waste["Sales_Qty"] + item_waste["Waste_Qty"]
        item_waste["Waste Rate"] = np.where(
            total_thru > 0,
            (item_waste["Waste_Qty"] / total_thru * 100).round(1),
            np.nan,
        )

    col_chart, col_table = st.columns([1, 1])
    top_n = min(12, len(item_waste))

    with col_chart:
        st.markdown(f"**Top {top_n} — Waste Cost ($)**")
        if USE_PLOTLY:
            fig3 = px.bar(
                item_waste.head(top_n).sort_values("Waste_Cost"),
                x="Waste_Cost", y="Item Name", orientation="h",
                color="Waste_Cost",
                color_continuous_scale="Reds",
                labels={"Waste_Cost": "$", "Item Name": ""},
            )
            fig3.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0),
                               coloraxis_showscale=False)
            st.plotly_chart(fig3, use_container_width=True)

    with col_table:
        st.markdown("**Item Detail**")
        disp_cols = ["Item Name", "Waste_Cost", "Waste_Qty", "Events"]
        col_rename = {
            "Waste_Cost": "Waste Cost ($)",
            "Waste_Qty":  "Qty Wasted",
            "Events":     "Log Entries",
        }
        if "Waste Rate" in item_waste.columns:
            disp_cols.append("Waste Rate")
            col_rename["Waste Rate"] = "Waste Rate (%)"

        disp = item_waste[disp_cols].head(20).copy()
        disp["Waste_Cost"] = disp["Waste_Cost"].round(2)
        disp["Waste_Qty"]  = disp["Waste_Qty"].round(1)
        if "Waste Rate" in disp.columns:
            disp["Waste Rate"] = disp["Waste Rate"].map(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "—"
            )
        st.dataframe(
            disp.rename(columns=col_rename),
            hide_index=True, use_container_width=True, height=420,
        )
        if "Waste Rate" in item_waste.columns:
            st.caption("Waste Rate > 15% warrants an order quantity review. Target: < 10%.")

    st.divider()

    # ── Stockout summary ──────────────────────────────────────────────────────
    st.subheader("Stockout Events")

    if stockout.empty:
        st.info(
            "No stockout data yet. Drag your SOH export onto "
            "**Launch Stockout Detector.bat** after each cycle to populate this section."
        )
    else:
        so = stockout[
            (stockout["report_date"] >= pd.Timestamp(date_from)) &
            (stockout["report_date"] <= pd.Timestamp(date_to))
        ]
        if so.empty:
            st.caption("No stockout events in the selected date range.")
        else:
            s1, s2, s3 = st.columns(3)
            s1.metric("Est. Lost Revenue",  fmt_currency(so["lost_revenue"].sum()))
            s2.metric("Stockout Events",    len(so))
            s3.metric("Avg Days Out",       f"{so['lost_days'].mean():.1f}")

            so_disp = so[["report_date", "item_name", "last_sold",
                           "lost_days", "lost_revenue"]].copy()
            so_disp["report_date"]  = so_disp["report_date"].dt.strftime("%d %b %Y")
            so_disp["last_sold"]    = so_disp["last_sold"].dt.strftime("%d %b %Y")
            so_disp["lost_revenue"] = so_disp["lost_revenue"].map("${:.2f}".format)
            so_disp.columns = ["SOH Date", "Item", "Last Sold",
                                "Days Out", "Est. Loss"]
            st.dataframe(
                so_disp.sort_values("Est. Loss", ascending=False),
                hide_index=True, use_container_width=True,
            )
