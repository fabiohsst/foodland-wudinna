"""
dash/pulse.py — Store Pulse dashboard page
Daily/weekly health check: revenue, GP%, YoY comparison, day-of-week pattern.
"""

import pandas as pd
import streamlit as st

from dash.common import (
    C, DOW_ORDER, SUBDEPT_COLORS,
    fmt_currency, fmt_pct, gp_pct,
    load_calendar, load_sales,
)

try:
    import plotly.express as px
    import plotly.graph_objects as go
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False


def render():
    sales = load_sales()
    if sales.empty:
        st.error("No sales data found. Check `01_data/raw/` for sales CSVs.")
        return

    cal = load_calendar()
    today = pd.Timestamp.today().normalize()

    # ── Date range filter (sidebar) ───────────────────────────────────────────
    with st.sidebar:
        st.header("Filters")
        min_d = sales["Date"].min().date()
        max_d = sales["Date"].max().date()
        date_from, date_to = st.date_input(
            "Date range",
            value=(max_d - pd.Timedelta(weeks=12), max_d),
            min_value=min_d, max_value=max_d,
        )
        subdepts = sorted(sales["SubDept"].dropna().unique())
        subdept_filter = st.multiselect("Sub-department", subdepts, default=subdepts)
        st.divider()
        st.caption(
            f"Data covers **{min_d.strftime('%d %b %Y')}** → "
            f"**{max_d.strftime('%d %b %Y')}**"
        )

    s = sales[
        (sales["Date"] >= pd.Timestamp(date_from)) &
        (sales["Date"] <= pd.Timestamp(date_to)) &
        (sales["SubDept"].isin(subdept_filter))
    ].copy()

    if s.empty:
        st.info("No data for the selected filters.")
        return

    # ── Determine "current week" and "prior week" from filtered window ────────
    latest_week  = s["Week"].max()
    prev_week    = latest_week - pd.Timedelta(weeks=1)
    same_wk_ly   = latest_week - pd.Timedelta(weeks=52)

    cur  = s[s["Week"] == latest_week]
    prev = s[s["Week"] == prev_week]
    ly   = s[s["Week"] == same_wk_ly]

    cur_rev  = cur["Revenue"].sum()
    prev_rev = prev["Revenue"].sum()
    ly_rev   = ly["Revenue"].sum()
    cur_gp   = gp_pct(cur_rev, cur["GP"].sum())
    cur_units = int(cur["Qty"].sum())
    cur_days  = cur["Date"].nunique()

    wow_rev = ((cur_rev - prev_rev) / prev_rev * 100) if prev_rev > 0 else 0
    yoy_rev = ((cur_rev - ly_rev)   / ly_rev   * 100) if ly_rev   > 0 else 0

    # ── KPI cards ─────────────────────────────────────────────────────────────
    st.subheader(
        f"Week of {latest_week.strftime('%d %b %Y')}  "
        f"({cur_days} trading day{'s' if cur_days != 1 else ''})"
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Revenue (this week)", fmt_currency(cur_rev),
              f"{wow_rev:+.1f}% vs prev week",
              delta_color="normal" if wow_rev >= 0 else "inverse")
    k2.metric("GP %", fmt_pct(cur_gp),
              help="Gross profit as % of revenue ex GST")
    k3.metric("Units Sold", f"{cur_units:,}",
              help="Total items sold this week")
    k4.metric("Daily Average", fmt_currency(cur_rev / max(cur_days, 1)),
              help="Revenue per trading day this week")
    k5.metric("YoY Revenue", fmt_pct(yoy_rev),
              f"{fmt_currency(ly_rev)} same week last year",
              delta_color="normal" if yoy_rev >= 0 else "inverse")

    st.divider()

    # ── Weekly revenue trend ──────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    weekly = (
        s.groupby("Week")
        .agg(Revenue=("Revenue", "sum"), GP=("GP", "sum"), Qty=("Qty", "sum"))
        .reset_index().sort_values("Week")
    )
    weekly["GP%"] = (weekly["GP"] / weekly["Revenue"].replace(0, pd.NA) * 100).round(1)
    weekly["label"] = weekly["Week"].dt.strftime("w/c %d %b")

    with col_left:
        st.markdown("**Weekly Revenue**")
        if USE_PLOTLY:
            fig = px.bar(
                weekly, x="label", y="Revenue",
                labels={"Revenue": "$", "label": ""},
                color_discrete_sequence=[C["primary"]],
            )
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.bar_chart(weekly.set_index("label")["Revenue"], height=280)

    with col_right:
        st.markdown("**Weekly GP %**")
        if USE_PLOTLY:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=weekly["label"], y=weekly["GP%"],
                mode="lines+markers",
                line=dict(color=C["success"], width=2),
                marker=dict(size=6),
            ))
            fig2.add_hline(y=37, line_dash="dash", line_color=C["neutral"],
                           annotation_text="37% target",
                           annotation_position="bottom right")
            fig2.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_ticksuffix="%")
            fig2.update_xaxes(tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.line_chart(weekly.set_index("label")["GP%"], height=280)

    st.divider()

    # ── Day-of-week pattern ───────────────────────────────────────────────────
    col_dow, col_subdept = st.columns(2)

    dow_avg = (
        s.groupby("DOW")["Revenue"]
        .mean().reindex(DOW_ORDER).reset_index()
    )
    dow_avg.columns = ["Day", "Avg Revenue"]
    dow_avg["Avg Revenue"] = dow_avg["Avg Revenue"].fillna(0)

    with col_dow:
        st.markdown("**Average Revenue by Day of Week**")
        if USE_PLOTLY:
            fig3 = px.bar(
                dow_avg, x="Day", y="Avg Revenue",
                labels={"Avg Revenue": "Avg $", "Day": ""},
                color="Avg Revenue",
                color_continuous_scale=[[0, "#AED6F1"], [1, C["primary"]]],
            )
            fig3.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                               coloraxis_showscale=False)
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.bar_chart(dow_avg.set_index("Day")["Avg Revenue"], height=260)

    with col_subdept:
        st.markdown("**Revenue by Sub-Department (period)**")
        subdept_rev = (
            s.groupby("SubDept")
            .agg(Revenue=("Revenue", "sum"), GP=("GP", "sum"))
            .reset_index()
            .sort_values("Revenue", ascending=False)
        )
        subdept_rev["GP%"] = (
            subdept_rev["GP"] / subdept_rev["Revenue"].replace(0, pd.NA) * 100
        ).round(1)
        if USE_PLOTLY:
            fig4 = px.pie(
                subdept_rev, values="Revenue", names="SubDept",
                color="SubDept",
                color_discrete_map=SUBDEPT_COLORS,
                hole=0.4,
            )
            fig4.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                               legend=dict(orientation="h", y=-0.15))
            fig4.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.dataframe(subdept_rev[["SubDept", "Revenue", "GP%"]],
                         hide_index=True, use_container_width=True)

    st.divider()

    # ── Upcoming trading days ─────────────────────────────────────────────────
    st.markdown("**Next 7 Trading Days**")
    upcoming = cal[
        (cal["date"] > today) &
        (cal["date"] <= today + pd.Timedelta(days=10))
    ].sort_values("date").head(7)

    if not upcoming.empty:
        cols = st.columns(len(upcoming))
        for col, (_, row) in zip(cols, upcoming.iterrows()):
            is_delivery = row.get("is_delivery_day", 0) == 1
            is_order    = row.get("is_order_day", 0) == 1
            is_open     = row.get("is_store_open", 0) == 1
            label = row["date"].strftime("%a\n%d %b")
            note  = ("🚚 Delivery" if is_delivery
                     else "📋 Order" if is_order
                     else "✅ Open" if is_open
                     else "🔒 Closed")
            bg = ("#D5E8D4" if is_delivery
                  else "#DAE8FC" if is_order
                  else "#FFFFFF" if is_open
                  else "#F2F2F2")
            col.markdown(
                f"""<div style="background:{bg};border-radius:6px;padding:8px;
                text-align:center;border:1px solid #ddd;font-size:13px;">
                <b>{row['date'].strftime('%a')}</b><br>
                {row['date'].strftime('%d %b')}<br>
                <span style="font-size:11px">{note}</span></div>""",
                unsafe_allow_html=True,
            )

    # ── Weekly summary table ──────────────────────────────────────────────────
    st.divider()
    with st.expander("Weekly summary table"):
        disp = weekly[["label", "Revenue", "GP%", "Qty"]].copy()
        disp["Revenue"] = disp["Revenue"].map(fmt_currency)
        disp["GP%"]     = disp["GP%"].map(fmt_pct)
        disp["Qty"]     = disp["Qty"].map("{:,.0f}".format)
        disp.columns    = ["Week", "Revenue", "GP %", "Units Sold"]
        st.dataframe(disp.sort_values("Week", ascending=False),
                     hide_index=True, use_container_width=True)
