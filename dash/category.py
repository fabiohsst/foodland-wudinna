"""
dash/category.py — Category & Product Intelligence page
Sub-department breakdown, ABC classification, top/bottom items, YoY movers.
"""

import pandas as pd
import streamlit as st

from dash.common import (
    C, SUBDEPT_COLORS,
    fmt_currency, fmt_pct, gp_pct,
    load_sales,
)

try:
    import plotly.express as px
    import plotly.graph_objects as go
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False

LOOKBACK_WEEKS = 8   # window for "recent" activity


def _abc_classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add ABC column: A = top 80% cumulative revenue, B = next 15%, C = bottom 5%."""
    df = df.sort_values("Revenue", ascending=False).copy()
    total = df["Revenue"].sum()
    if total == 0:
        df["ABC"] = "C"
        return df
    df["cum_pct"] = df["Revenue"].cumsum() / total * 100
    df["ABC"] = "C"
    df.loc[df["cum_pct"] <= 95, "ABC"] = "B"
    df.loc[df["cum_pct"] <= 80, "ABC"] = "A"
    return df


def render():
    sales = load_sales()
    if sales.empty:
        st.error("No sales data found.")
        return

    # ── Sidebar filters ───────────────────────────────────────────────────────
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

    # ── Sub-department KPI cards ──────────────────────────────────────────────
    st.subheader("Sub-Department Overview")
    dept_stats = (
        s.groupby("SubDept")
        .agg(Revenue=("Revenue", "sum"), GP=("GP", "sum"),
             Qty=("Qty", "sum"), Items=("Name", "nunique"))
        .reset_index()
        .sort_values("Revenue", ascending=False)
    )
    dept_stats["GP%"] = dept_stats.apply(
        lambda r: gp_pct(r["Revenue"], r["GP"]), axis=1
    )

    cols = st.columns(len(dept_stats))
    for col, (_, row) in zip(cols, dept_stats.iterrows()):
        colour = SUBDEPT_COLORS.get(row["SubDept"], C["neutral"])
        col.markdown(
            f"""<div style="background:{colour}18;border-left:4px solid {colour};
            border-radius:6px;padding:12px;">
            <div style="font-weight:700;font-size:13px;color:{colour}">
            {row['SubDept'].upper()}</div>
            <div style="font-size:22px;font-weight:700">{fmt_currency(row['Revenue'])}</div>
            <div style="font-size:13px">GP {fmt_pct(row['GP%'])} &nbsp;·&nbsp;
            {int(row['Items'])} items</div></div>""",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Revenue trend by sub-dept ─────────────────────────────────────────────
    col_trend, col_mix = st.columns(2)

    weekly_dept = (
        s.groupby(["Week", "SubDept"])["Revenue"]
        .sum().reset_index().sort_values("Week")
    )
    weekly_dept["label"] = weekly_dept["Week"].dt.strftime("w/c %d %b")

    with col_trend:
        st.markdown("**Weekly Revenue by Sub-Department**")
        if USE_PLOTLY:
            fig = px.bar(
                weekly_dept, x="label", y="Revenue", color="SubDept",
                labels={"Revenue": "$", "label": "", "SubDept": ""},
                color_discrete_map=SUBDEPT_COLORS,
                barmode="stack",
            )
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0),
                               legend=dict(orientation="h", y=1.05))
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            pivot = weekly_dept.pivot(
                index="label", columns="SubDept", values="Revenue"
            ).fillna(0)
            st.bar_chart(pivot, height=300)

    with col_mix:
        st.markdown("**GP % by Sub-Department**")
        weekly_gp = (
            s.groupby(["Week", "SubDept"])
            .agg(Revenue=("Revenue", "sum"), GP=("GP", "sum"))
            .reset_index()
        )
        weekly_gp["GP%"] = (
            weekly_gp["GP"] / weekly_gp["Revenue"].replace(0, pd.NA) * 100
        ).round(1)
        weekly_gp["label"] = weekly_gp["Week"].dt.strftime("w/c %d %b")
        if USE_PLOTLY:
            fig2 = px.line(
                weekly_gp, x="label", y="GP%", color="SubDept",
                labels={"GP%": "GP %", "label": "", "SubDept": ""},
                color_discrete_map=SUBDEPT_COLORS,
                markers=True,
            )
            fig2.add_hline(y=37, line_dash="dash", line_color=C["neutral"],
                           annotation_text="37% target")
            fig2.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_ticksuffix="%",
                               legend=dict(orientation="h", y=1.05))
            fig2.update_xaxes(tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            pivot2 = weekly_gp.pivot(
                index="label", columns="SubDept", values="GP%"
            ).fillna(0)
            st.line_chart(pivot2, height=300)

    st.divider()

    # ── ABC classification ────────────────────────────────────────────────────
    st.subheader("Product Analysis")

    item_stats = (
        s.groupby(["Name", "SubDept"])
        .agg(Revenue=("Revenue", "sum"), GP=("GP", "sum"),
             Qty=("Qty", "sum"), Days=("Date", "nunique"))
        .reset_index()
    )
    item_stats["GP%"]         = item_stats.apply(
        lambda r: gp_pct(r["Revenue"], r["GP"]), axis=1
    )
    item_stats["Rev/Day"]     = (item_stats["Revenue"] / item_stats["Days"].clip(1)).round(2)
    item_stats                = _abc_classify(item_stats)
    total_rev                 = item_stats["Revenue"].sum()
    item_stats["Rev Share %"] = (item_stats["Revenue"] / total_rev * 100).round(1)

    tab_top, tab_bottom, tab_abc, tab_yoy = st.tabs([
        "Top 20 Items", "Bottom 20 Items", "ABC Classification", "YoY Movers"
    ])

    # Top 20
    with tab_top:
        n_items = st.slider("Show top N items", 10, 50, 20, key="top_n")
        top_items = item_stats.sort_values("Revenue", ascending=False).head(n_items)
        if USE_PLOTLY:
            fig3 = px.bar(
                top_items.sort_values("Revenue"),
                x="Revenue", y="Name", orientation="h",
                color="SubDept", color_discrete_map=SUBDEPT_COLORS,
                labels={"Revenue": "$", "Name": ""},
            )
            fig3.update_layout(
                height=max(350, n_items * 22),
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", y=1.02),
            )
            st.plotly_chart(fig3, use_container_width=True)
        disp = top_items[["Name", "SubDept", "Revenue", "GP%", "Rev Share %", "ABC"]].copy()
        disp["Revenue"] = disp["Revenue"].map(fmt_currency)
        disp["GP%"]     = disp["GP%"].map(fmt_pct)
        disp["Rev Share %"] = disp["Rev Share %"].map("{:.1f}%".format)
        st.dataframe(disp, hide_index=True, use_container_width=True)

    # Bottom 20 (active items with revenue > 0, lowest performers)
    with tab_bottom:
        active_cutoff = sales["Date"].max() - pd.Timedelta(weeks=LOOKBACK_WEEKS)
        active_names  = set(
            sales[sales["Date"] >= active_cutoff]["Name"].unique()
        )
        bottom_items = (
            item_stats[item_stats["Name"].isin(active_names)]
            .sort_values("Revenue")
            .head(20)
        )
        st.caption(
            f"Active items (sold in last {LOOKBACK_WEEKS} weeks) with lowest revenue. "
            "These are candidates for range review."
        )
        if USE_PLOTLY:
            fig4 = px.bar(
                bottom_items.sort_values("Revenue", ascending=False),
                x="Revenue", y="Name", orientation="h",
                color="SubDept", color_discrete_map=SUBDEPT_COLORS,
                labels={"Revenue": "$", "Name": ""},
            )
            fig4.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                               legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig4, use_container_width=True)
        disp2 = bottom_items[["Name", "SubDept", "Revenue", "GP%", "Days", "ABC"]].copy()
        disp2["Revenue"] = disp2["Revenue"].map(fmt_currency)
        disp2["GP%"]     = disp2["GP%"].map(fmt_pct)
        st.dataframe(disp2, hide_index=True, use_container_width=True)

    # ABC
    with tab_abc:
        abc_summary = (
            item_stats.groupby("ABC")
            .agg(Items=("Name", "count"),
                 Revenue=("Revenue", "sum"),
                 GP_sum=("GP", "sum"))
            .reindex(["A", "B", "C"])
            .reset_index()
        )
        abc_summary["GP%"]      = abc_summary.apply(
            lambda r: gp_pct(r["Revenue"], r["GP_sum"]), axis=1
        )
        abc_summary["Rev Share"] = (
            abc_summary["Revenue"] / abc_summary["Revenue"].sum() * 100
        ).round(1)

        a1, a2, a3 = st.columns(3)
        for col, (_, row) in zip([a1, a2, a3], abc_summary.iterrows()):
            colour = {"A": C["success"], "B": C["warning"], "C": C["neutral"]}[row["ABC"]]
            col.markdown(
                f"""<div style="background:{colour}18;border-left:4px solid {colour};
                border-radius:6px;padding:12px;text-align:center">
                <div style="font-size:28px;font-weight:800;color:{colour}">
                {row['ABC']}-Class</div>
                <div style="font-size:13px">{int(row['Items'])} items</div>
                <div style="font-size:20px;font-weight:700">{fmt_currency(row['Revenue'])}</div>
                <div style="font-size:12px">{row['Rev Share']:.0f}% of revenue · GP {fmt_pct(row['GP%'])}</div>
                </div>""",
                unsafe_allow_html=True,
            )

        st.markdown("")
        abc_detail = item_stats[["Name", "SubDept", "Revenue", "GP%", "ABC"]].copy()
        abc_detail["Revenue"] = abc_detail["Revenue"].map(fmt_currency)
        abc_detail["GP%"]     = abc_detail["GP%"].map(fmt_pct)
        abc_filter = st.selectbox("Filter by class", ["All", "A", "B", "C"])
        if abc_filter != "All":
            abc_detail = abc_detail[
                item_stats["ABC"] == abc_filter
            ]
        st.dataframe(
            abc_detail.sort_values("Revenue", ascending=False),
            hide_index=True, use_container_width=True, height=400,
        )

    # YoY Movers
    with tab_yoy:
        sales_2025 = sales[sales["Year"] == 2025]
        sales_2026 = sales[sales["Year"] == 2026]

        # Comparable date window: Jan–Mar only (months available in both years)
        max_month_2026 = sales_2026["Date"].max().month
        s25_comp = sales_2025[sales_2025["Date"].dt.month <= max_month_2026]
        s26_comp = sales_2026.copy()

        rev25 = s25_comp.groupby("Name")["Revenue"].sum().rename("Rev_2025")
        rev26 = s26_comp.groupby("Name")["Revenue"].sum().rename("Rev_2026")

        yoy = pd.concat([rev25, rev26], axis=1).dropna()
        yoy["Change $"]  = (yoy["Rev_2026"] - yoy["Rev_2025"]).round(0)
        yoy["Change %"]  = (
            (yoy["Rev_2026"] - yoy["Rev_2025"]) / yoy["Rev_2025"] * 100
        ).round(1)
        yoy = yoy.reset_index()

        risers  = yoy.nlargest(15,  "Change $")
        fallers = yoy.nsmallest(15, "Change $")

        c_rise, c_fall = st.columns(2)

        with c_rise:
            st.markdown("**📈 Rising Items (YoY $ change)**")
            if USE_PLOTLY:
                fig5 = px.bar(
                    risers.sort_values("Change $"),
                    x="Change $", y="Name", orientation="h",
                    color_discrete_sequence=[C["success"]],
                    labels={"Change $": "$ change", "Name": ""},
                )
                fig5.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig5, use_container_width=True)

        with c_fall:
            st.markdown("**📉 Falling Items (YoY $ change)**")
            if USE_PLOTLY:
                fig6 = px.bar(
                    fallers.sort_values("Change $", ascending=False),
                    x="Change $", y="Name", orientation="h",
                    color_discrete_sequence=[C["danger"]],
                    labels={"Change $": "$ change", "Name": ""},
                )
                fig6.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig6, use_container_width=True)

        st.caption(
            f"YoY comparison: Jan–{pd.Timestamp(2026, max_month_2026, 1).strftime('%b')} "
            f"2025 vs 2026. Only items sold in both years shown."
        )
