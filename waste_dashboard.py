"""
waste_dashboard.py — Waste & Markdown Dashboard  (v4)
Foodland Wudinna

Departments supported: FRUIT & VEG · DAIRY · MEAT
Selected at the top of the page via a radio button.

Section 1 — Total Waste
    Source: GAP Dump (fact_dump)  +  Manual Log Binned (fact_waste_log, FV only)
    Metric: cost of stock that generated zero revenue.
    Markdown excluded — those items were sold (at a discount), not wasted.

Section 2 — Markdown & Reductions
    Source: GAP Markdown (fact_markdown, individual transaction dates)
    Optional: Manual Log Reduced (fact_waste_log, FV only)
    Metric: discount given vs realised profit (negative = sold below cost).
    Now date-based → weekly and monthly trends available for all departments.

Section 3 — Weekly Detail
    GAP Dump entries + Markdown entries for a selected week.

Section 4 — Daily Detail (FV only)
    Manual Log Binned + Reduced entries for a selected date.

Launch: streamlit run waste_dashboard.py --server.port 8503
"""

import sys
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
DB   = ROOT / "foodland_data.db"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    USE_PLOTLY = True
except ImportError:
    USE_PLOTLY = False


# ── Constants ─────────────────────────────────────────────────────────────────
MANUAL_LOG_START = pd.Timestamp("2026-03-25")

COLORS = {
    "GAP Dump":    "#E74C3C",
    "Binned":      "#2E86AB",
    "Discount":    "#E67E22",
    "Below Cost":  "#C0392B",
    "Above Cost":  "#27AE60",
    "neutral":     "#95A5A6",
    "target_line": "#E74C3C",
}

DEPT_LABELS = {
    "FRUIT & VEG": "🥦 Fruit & Veg",
    "DAIRY":       "🥛 Dairy",
    "MEAT":        "🥩 Meat",
}


# ── DB connection ─────────────────────────────────────────────────────────────
def _conn():
    return sqlite3.connect(f"file:{DB}?immutable=1", uri=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False, ttl=300)
def load_dump(department: str) -> pd.DataFrame:
    """GAP POS dump transactions for the given department. waste_cost = total_cost_ex."""
    conn = _conn()
    df = pd.read_sql_query(
        """
        SELECT fd.date_id,
               COALESCE(dp.name, fd.description) AS item,
               COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown') AS sub_dept,
               fd.qty,
               fd.total_cost_ex AS waste_cost,
               fd.reason,
               fd.unit_cost_ex
        FROM   fact_dump fd
        LEFT   JOIN dim_product dp ON fd.product_id = dp.product_id
        WHERE  fd.department = ?
          AND  fd.total_cost_ex IS NOT NULL
        """,
        conn, params=(department,),
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date_id"])
    return df.drop(columns="date_id")


@st.cache_data(show_spinner=False, ttl=300)
def load_binned() -> pd.DataFrame:
    """Manual Log Binned entries — FV only. waste_cost = costed_cost (qty × cost_price)."""
    conn = _conn()
    df = pd.read_sql_query(
        """
        SELECT wl.date_id,
               COALESCE(dp.name, wl.item_name) AS item,
               COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown') AS sub_dept,
               wl.qty,
               wl.unit,
               wl.costed_cost
        FROM   fact_waste_log wl
        LEFT   JOIN dim_product dp ON wl.product_id = dp.product_id
        WHERE  wl.action = 'Binned'
        """,
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date_id"])
    df = df.drop(columns="date_id")
    df["waste_cost"] = df["costed_cost"].fillna(0).round(4)
    return df


@st.cache_data(show_spinner=False, ttl=300)
def load_reduced() -> pd.DataFrame:
    """Manual Log Reduced entries — FV only. net_above_cost = new_price × qty − cost."""
    conn = _conn()
    df = pd.read_sql_query(
        """
        SELECT wl.date_id,
               COALESCE(dp.name, wl.item_name) AS item,
               COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown') AS sub_dept,
               wl.qty,
               wl.unit,
               wl.new_price,
               wl.costed_cost
        FROM   fact_waste_log wl
        LEFT   JOIN dim_product dp ON wl.product_id = dp.product_id
        WHERE  wl.action = 'Reduced'
          AND  wl.new_price IS NOT NULL
        """,
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date_id"])
    df = df.drop(columns="date_id")
    df["cost_per_unit"] = (df["costed_cost"] / df["qty"].replace(0, None)).where(df["qty"] > 0)
    df["revenue"]    = (df["new_price"] * df["qty"]).round(4)
    df["cost_total"] = df["costed_cost"].fillna(0).round(4)
    df["net_above_cost"] = (df["revenue"] - df["cost_total"]).round(4)
    return df


@st.cache_data(show_spinner=False, ttl=300)
def load_markdown(department: str) -> pd.DataFrame:
    """
    GAP POS markdown — individual transaction dates, all departments.
    realised_profit = total_sell − total_cost  (negative = sold below cost).
    """
    conn = _conn()
    df = pd.read_sql_query(
        """
        SELECT fm.date_id,
               COALESCE(dp.name, fm.description) AS item,
               COALESCE(NULLIF(dp.sub_dept, 'None'), NULLIF(fm.sub_dept, 'None'), 'Unknown') AS sub_dept,
               fm.lines,
               fm.potential_sell,
               fm.total_sell,
               fm.total_cost,
               fm.discount_given,
               fm.realised_profit
        FROM   fact_markdown fm
        LEFT   JOIN dim_product dp ON fm.product_id = dp.product_id
        WHERE  fm.department = ?
        """,
        conn, params=(department,),
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date_id"])
    return df.drop(columns="date_id")


@st.cache_data(show_spinner=False, ttl=300)
def load_revenue(department: str) -> pd.DataFrame:
    """Daily revenue for a given department from fact_sales."""
    conn = _conn()
    df = pd.read_sql_query(
        """
        SELECT fs.date_id,
               COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown') AS sub_dept,
               SUM(fs.sales_ex_gst) AS revenue
        FROM   fact_sales fs
        LEFT   JOIN dim_product dp ON fs.product_id = dp.product_id
        WHERE  fs.department = ?
        GROUP  BY fs.date_id, COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown')
        """,
        conn, params=(department,),
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date_id"])
    return df.drop(columns="date_id")


# ══════════════════════════════════════════════════════════════════════════════
# PERIOD HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def add_period_cols(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["week_start"] = d["date"] - pd.to_timedelta(d["date"].dt.dayofweek, unit="D")
    d["week_label"] = d["week_start"].dt.strftime("w/c %d %b '%y")
    d["month_start"] = d["date"].values.astype("datetime64[M]").astype("datetime64[ns]")
    d["month_label"] = d["date"].dt.strftime("%b %Y")
    d["day_name"]    = d["date"].dt.day_name()
    return d


def period_end_date(start: pd.Timestamp, groupby: str) -> pd.Timestamp:
    if groupby == "week":
        return start + pd.Timedelta(days=5)
    return (start + pd.DateOffset(months=1)) - pd.Timedelta(days=1)


def period_revenue(rev: pd.DataFrame, start, end) -> float:
    mask = (rev["date"] >= pd.Timestamp(start)) & (rev["date"] <= pd.Timestamp(end))
    return float(rev.loc[mask, "revenue"].sum())


def aggregate_waste(dump: pd.DataFrame, binned: pd.DataFrame, groupby: str) -> pd.DataFrame:
    """Combine GAP Dump and Manual Log Binned into one per-period table."""
    start_col = "week_start" if groupby == "week" else "month_start"
    label_col = "week_label" if groupby == "week" else "month_label"

    dump_agg = (
        dump.groupby([start_col, label_col])
        .agg(dump_cost=("waste_cost", "sum"))
        .reset_index()
        .rename(columns={start_col: "period_start", label_col: "label"})
    )
    bin_agg = (
        binned.groupby([start_col, label_col])
        .agg(binned_cost=("waste_cost", "sum"))
        .reset_index()
        .rename(columns={start_col: "period_start", label_col: "label"})
    ) if not binned.empty else pd.DataFrame(columns=["period_start", "label", "binned_cost"])

    merged = pd.merge(dump_agg, bin_agg, on=["period_start", "label"], how="outer").fillna(0)
    merged["has_manual_log"] = (merged["period_start"] >= MANUAL_LOG_START)
    merged["total_waste"] = merged["dump_cost"] + merged["binned_cost"]
    return merged.sort_values("period_start")


def aggregate_markdown(md: pd.DataFrame, groupby: str) -> pd.DataFrame:
    """Aggregate markdown by week or month."""
    start_col = "week_start" if groupby == "week" else "month_start"
    label_col = "week_label" if groupby == "week" else "month_label"

    if md.empty:
        return pd.DataFrame(columns=["period_start", "label", "discount_given",
                                     "realised_profit", "below_cost_lines", "lines"])

    agg = (
        md.groupby([start_col, label_col])
        .agg(
            discount_given=("discount_given", "sum"),
            realised_profit=("realised_profit", "sum"),
            below_cost_lines=("realised_profit", lambda x: (x < 0).sum()),
            lines=("lines", "sum"),
        )
        .reset_index()
        .rename(columns={start_col: "period_start", label_col: "label"})
    )
    return agg.sort_values("period_start")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — TOTAL WASTE
# ══════════════════════════════════════════════════════════════════════════════

def render_waste_section(dump: pd.DataFrame, binned: pd.DataFrame,
                         rev: pd.DataFrame, groupby: str, date_filter,
                         has_manual_log: bool):
    cutoff, max_date = date_filter
    dump_f   = dump[dump["date"] >= cutoff]
    binned_f = binned[binned["date"] >= cutoff] if not binned.empty else binned

    waste_agg = aggregate_waste(dump_f, binned_f, groupby)
    if waste_agg.empty:
        st.info("No waste data for the selected period.")
        return

    total_dump   = dump_f["waste_cost"].sum()
    total_binned = binned_f["waste_cost"].sum() if not binned_f.empty else 0.0
    total_waste  = total_dump + total_binned
    rev_total    = period_revenue(rev, cutoff, max_date)
    wr_pct       = total_waste / rev_total * 100 if rev_total > 0 else 0

    # ── KPIs ──────────────────────────────────────────────────────────────────
    wr_color = "normal" if wr_pct < 5 else "inverse"
    wr_delta = "above 5% target" if wr_pct > 5 else "within target"
    if has_manual_log:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Waste Cost", f"${total_waste:.2f}")
        c2.metric("GAP Dump", f"${total_dump:.2f}")
        c3.metric("Manual Log Binned", f"${total_binned:.2f}")
        c4.metric("FV Revenue", f"${rev_total:,.2f}")
        c5.metric("Waste / Revenue", f"{wr_pct:.1f}%", delta=wr_delta, delta_color=wr_color)
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Waste Cost (GAP Dump)", f"${total_waste:.2f}")
        c2.metric("Revenue", f"${rev_total:,.2f}")
        c3.metric("Waste / Revenue", f"{wr_pct:.1f}%", delta=wr_delta, delta_color=wr_color)

    # ── Notes ─────────────────────────────────────────────────────────────────
    st.info(
        "**Markdown excluded** — only stock that generated zero revenue is measured here "
        "(GAP Dump" + (" + Manual Log Binned" if has_manual_log else "") +
        "). Discounted sales are tracked separately in the Markdown & Reductions tab."
    )
    if has_manual_log:
        if not binned_f.empty:
            st.caption(
                f"ℹ️ Manual Log available from **{MANUAL_LOG_START.strftime('%d %b %Y')}** "
                f"— covers loose/weight items only. GAP Dump covers barcoded products."
            )
        else:
            st.warning(
                "Manual Log not available for the selected period. "
                "Waste total reflects GAP Dump (barcoded products) only."
            )
    else:
        st.caption("ℹ️ GAP Dump data only. Manual waste log is not available for this department.")

    st.markdown("")

    # ── Trend chart ───────────────────────────────────────────────────────────
    if USE_PLOTLY:
        _waste_trend_chart(waste_agg, rev, groupby, has_manual_log)
    else:
        st.bar_chart(waste_agg.set_index("label")[["dump_cost"] +
                     (["binned_cost"] if has_manual_log else [])])

    st.divider()

    # ── Top offenders ─────────────────────────────────────────────────────────
    st.markdown("**Top Items by Waste Cost**")
    frames = [dump_f[["item", "qty", "waste_cost"]].assign(source="GAP Dump")]
    if has_manual_log and not binned_f.empty:
        frames.append(binned_f[["item", "qty", "waste_cost"]].assign(source="Binned"))
    combined_items = pd.concat(frames)
    top = (
        combined_items[combined_items["waste_cost"] > 0]
        .groupby("item")
        .agg(waste_cost=("waste_cost", "sum"), qty=("qty", "sum"),
             events=("waste_cost", "count"))
        .sort_values("waste_cost", ascending=False)
        .head(12)
        .reset_index()
    )
    if USE_PLOTLY and not top.empty:
        fig = px.bar(
            top.sort_values("waste_cost"),
            x="waste_cost", y="item", orientation="h",
            labels={"waste_cost": "Cost ($)", "item": ""},
            color="waste_cost", color_continuous_scale="Reds",
        )
        fig.update_layout(
            height=max(300, len(top) * 28),
            coloraxis_showscale=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=0, l=0, r=0),
            xaxis=dict(tickprefix="$", gridcolor="#f0f0f0"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Waste / Revenue — both views ──────────────────────────────────────────
    st.markdown("**Waste / Revenue by Period**")
    st.caption(
        "Both views apply the same period filter selected in the sidebar. "
        "⚠ = Manual Log not yet active — loose/weight item waste not included."
        + (" Open-ring dump items fall into 'Unknown' — deselecting that sub-department "
           "will silently drop those entries." if has_manual_log else "")
    )
    col_week, col_month = st.columns(2)
    with col_week:
        st.markdown("**By Week**")
        _waste_summary_table(aggregate_waste(dump_f, binned_f, "week"), rev, "week")
    with col_month:
        st.markdown("**By Month**")
        _waste_summary_table(aggregate_waste(dump_f, binned_f, "month"), rev, "month")


def _waste_trend_chart(waste_agg: pd.DataFrame, rev: pd.DataFrame,
                       groupby: str, has_manual_log: bool):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="GAP Dump",
        x=waste_agg["label"], y=waste_agg["dump_cost"],
        marker_color=COLORS["GAP Dump"], marker_line_width=0,
        hovertemplate="%{x}<br>GAP Dump: $%{y:.2f}<extra></extra>",
    ))
    if has_manual_log and "binned_cost" in waste_agg.columns and waste_agg["binned_cost"].sum() > 0:
        fig.add_trace(go.Bar(
            name="Manual Log Binned",
            x=waste_agg["label"], y=waste_agg["binned_cost"],
            marker_color=COLORS["Binned"], marker_line_width=0,
            hovertemplate="%{x}<br>Binned: $%{y:.2f}<extra></extra>",
        ))

    wr_points = []
    for _, row in waste_agg.iterrows():
        if row["total_waste"] > 0:
            ps = pd.Timestamp(row["period_start"])
            pe = period_end_date(ps, groupby)
            rv = period_revenue(rev, ps, pe)
            if rv > 0:
                wr_points.append({"label": row["label"],
                                  "pct": row["total_waste"] / rv * 100})
    if wr_points:
        wr = pd.DataFrame(wr_points)
        fig.add_trace(go.Scatter(
            name="Waste/Rev %",
            x=wr["label"], y=wr["pct"],
            mode="lines+markers",
            line=dict(color="#27AE60", width=2, dash="dot"),
            marker=dict(size=6, symbol="diamond"),
            yaxis="y2",
            hovertemplate="%{x}<br>Waste/Rev: %{y:.1f}%<extra></extra>",
        ))

    annotations = []
    if has_manual_log:
        for _, row in waste_agg[~waste_agg["has_manual_log"]].iterrows():
            if row["dump_cost"] > 0:
                annotations.append(dict(
                    x=row["label"], y=row["dump_cost"],
                    text="GAP only", showarrow=False,
                    yanchor="bottom", font=dict(size=9, color="#888"),
                    yref="y",
                ))

    fig.update_layout(
        barmode="stack", height=400,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=10, b=0, l=0, r=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#f0f0f0", tickprefix="$", title="Waste Cost"),
        yaxis2=dict(title="Waste/Rev %", overlaying="y", side="right",
                    ticksuffix="%", showgrid=False, range=[0, 20]),
        annotations=annotations,
    )
    if wr_points:
        fig.add_hline(
            y=5, line_dash="dash", line_color=COLORS["target_line"], line_width=1,
            annotation_text="5% target", annotation_position="top right",
            yref="y2",
        )
    st.plotly_chart(fig, use_container_width=True)


def _waste_summary_table(waste_agg: pd.DataFrame, rev: pd.DataFrame, groupby: str):
    rows = []
    for _, row in waste_agg.iterrows():
        ps = pd.Timestamp(row["period_start"])
        pe = period_end_date(ps, groupby)
        rv = period_revenue(rev, ps, pe)
        wr = f"{row['total_waste'] / rv * 100:.1f}%" if rv > 0 and row["total_waste"] > 0 else "—"
        note = "" if row.get("has_manual_log", True) else "⚠ GAP only"
        rows.append({
            "Period":       row["label"],
            "GAP Dump ($)": f"${row['dump_cost']:.2f}" if row["dump_cost"] > 0 else "—",
            "Binned ($)":   f"${row.get('binned_cost', 0):.2f}" if row.get("binned_cost", 0) > 0 else "—",
            "Total ($)":    f"${row['total_waste']:.2f}",
            "Rev ($)":      f"${rv:,.0f}" if rv > 0 else "—",
            "W/R %":        wr,
            "Note":         note,
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if any(r["Note"] for r in rows):
            st.caption("⚠ = Manual Log not yet active — loose/weight waste not included.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — MARKDOWN & REDUCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def render_markdown_section(markdown: pd.DataFrame, reduced: pd.DataFrame,
                            rev: pd.DataFrame, groupby: str, date_filter,
                            has_manual_log: bool):
    cutoff, max_date = date_filter
    md_f  = markdown[markdown["date"] >= cutoff] if not markdown.empty else markdown
    red_f = reduced[reduced["date"] >= cutoff]   if not reduced.empty  else reduced

    if md_f.empty and red_f.empty:
        st.info("No markdown data for the selected period.")
        return

    # ── KPIs ──────────────────────────────────────────────────────────────────
    md_disc       = md_f["discount_given"].sum()  if not md_f.empty else 0.0
    md_profit     = md_f["realised_profit"].sum() if not md_f.empty else 0.0
    md_below      = md_f.loc[md_f["realised_profit"] < 0, "realised_profit"].sum() if not md_f.empty else 0.0
    md_below_lines = int((md_f["realised_profit"] < 0).sum()) if not md_f.empty else 0
    md_lines      = len(md_f)

    if has_manual_log and not red_f.empty:
        red_net   = red_f["net_above_cost"].sum()
        red_below = red_f[red_f["net_above_cost"] < 0]["net_above_cost"].sum()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("GAP Markdown — Discount Given", f"${md_disc:.2f}")
        c2.metric("GAP Markdown — Realised P/L", f"${md_profit:.2f}")
        c3.metric("GAP Markdown — Below-Cost Loss", f"${md_below:.2f}", delta_color="inverse" if md_below < 0 else "off")
        c4.metric("Manual Log Reduced — Net vs Cost", f"${red_net:.2f}")
        c5.metric("Manual Log — Below-Cost Loss", f"${red_below:.2f}", delta_color="inverse" if red_below < 0 else "off")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Discount Given", f"${md_disc:.2f}")
        c2.metric("Realised P/L", f"${md_profit:.2f}")
        c3.metric("Below-Cost Lines", f"{int(md_below_lines)}")

    if md_below < 0:
        st.warning(
            f"**${abs(md_below):.2f}** in markdowns sold below cost — "
            "stock recovered some revenue but did not cover the cost of goods."
        )

    st.markdown("")

    # ── Trend chart ───────────────────────────────────────────────────────────
    if not md_f.empty:
        md_agg = aggregate_markdown(md_f, groupby)
        if USE_PLOTLY and not md_agg.empty:
            _markdown_trend_chart(md_agg, rev, groupby)

        st.divider()

        # ── Left: top items by discount | Right: period summary table ─────────
        col_l, col_r = st.columns([3, 2])

        with col_l:
            st.markdown("**Top Items by Discount Given**")
            top_disc = (
                md_f.groupby("item")
                .agg(
                    discount_given=("discount_given", "sum"),
                    realised_profit=("realised_profit", "sum"),
                    lines=("lines", "sum"),
                )
                .reset_index()
                .sort_values("discount_given", ascending=False)
                .head(15)
            )
            if USE_PLOTLY and not top_disc.empty:
                top_disc["colour"] = top_disc["realised_profit"].apply(
                    lambda v: COLORS["Below Cost"] if v < 0 else COLORS["Above Cost"]
                )
                fig = go.Figure(go.Bar(
                    x=top_disc["discount_given"].iloc[::-1],
                    y=top_disc["item"].iloc[::-1],
                    orientation="h",
                    marker_color=top_disc["colour"].iloc[::-1],
                    customdata=top_disc["realised_profit"].iloc[::-1],
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "Discount: $%{x:.2f}<br>"
                        "Realised P/L: $%{customdata:.2f}<extra></extra>"
                    ),
                ))
                fig.update_layout(
                    height=max(300, len(top_disc) * 28),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=0, l=0, r=0),
                    xaxis=dict(tickprefix="$", gridcolor="#f0f0f0", title="Discount Given ($)"),
                    yaxis=dict(showgrid=False),
                )
                fig.add_vline(x=0, line_color="#888", line_width=1)
                st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "🟥 Red = sold below cost (monetary loss). "
                "🟩 Green = sold above cost (margin reduced but not lost)."
            )

        with col_r:
            st.markdown(f"**{'Weekly' if groupby == 'week' else 'Monthly'} Summary**")
            _markdown_summary_table(md_agg, rev, groupby)

    # ── Manual Log Reduced (FV only) ──────────────────────────────────────────
    if has_manual_log and not red_f.empty:
        st.divider()
        st.markdown("**Manual Log Reduced — Net vs Cost per Item**")
        st.caption(
            "Revenue (new price × qty) minus cost (cost_price × qty). "
            "Green = sold above cost. Red = sold below cost."
        )
        item_red = (
            red_f.groupby("item")
            .agg(
                net_above_cost=("net_above_cost", "sum"),
                revenue=("revenue", "sum"),
                cost_total=("cost_total", "sum"),
                events=("net_above_cost", "count"),
            )
            .reset_index()
            .sort_values("net_above_cost")
        )
        if USE_PLOTLY and not item_red.empty:
            item_red["colour"] = item_red["net_above_cost"].apply(
                lambda v: COLORS["Below Cost"] if v < 0 else COLORS["Above Cost"]
            )
            fig = go.Figure(go.Bar(
                x=item_red["net_above_cost"],
                y=item_red["item"],
                orientation="h",
                marker_color=item_red["colour"],
                hovertemplate="<b>%{y}</b><br>Net vs cost: $%{x:.2f}<extra></extra>",
            ))
            fig.add_vline(x=0, line_color="#888", line_width=1)
            fig.update_layout(
                height=max(300, len(item_red) * 26),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=10, b=0, l=0, r=0),
                xaxis=dict(tickprefix="$", gridcolor="#f0f0f0", title="Net above cost ($)"),
                yaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("Detailed reduction entries (Manual Log Reduced)"):
            detail = red_f[["date", "item", "qty", "unit", "new_price",
                             "cost_per_unit", "revenue", "cost_total",
                             "net_above_cost"]].copy()
            detail["date"] = detail["date"].dt.strftime("%a %d %b")
            for col in ["new_price", "cost_per_unit", "revenue", "cost_total", "net_above_cost"]:
                detail[col] = detail[col].map("${:.2f}".format)
            detail["qty"] = detail["qty"].round(3)
            st.dataframe(
                detail.rename(columns={
                    "date": "Date", "item": "Item", "qty": "Qty", "unit": "Unit",
                    "new_price": "New Price", "cost_per_unit": "Cost/Unit",
                    "revenue": "Revenue", "cost_total": "Cost",
                    "net_above_cost": "Net vs Cost",
                }),
                hide_index=True, use_container_width=True,
            )


def _markdown_trend_chart(md_agg: pd.DataFrame, rev: pd.DataFrame, groupby: str):
    """
    Two-panel stacked chart:
      Top (65%): Discount Given bars + Realised P/L line (both $, shared axis)
      Bottom (35%): Discount as % of Revenue
    Splitting into two panels eliminates triple-axis label collisions.
    """
    # ── Discount/Rev % — compute before drawing ────────────────────────────────
    dr_rows = []
    partial_labels = set()
    all_revs = [period_revenue(rev, pd.Timestamp(r["period_start"]),
                               period_end_date(pd.Timestamp(r["period_start"]), groupby))
                for _, r in md_agg.iterrows()]
    median_rev = sorted(all_revs)[len(all_revs) // 2] if all_revs else 1

    for (_, row), rv in zip(md_agg.iterrows(), all_revs):
        if rv > 0:
            dr_rows.append({"label": row["label"], "pct": row["discount_given"] / rv * 100})
            # Flag weeks where revenue < 40% of median — likely partial period
            if rv < median_rev * 0.4:
                partial_labels.add(row["label"])

    dr = pd.DataFrame(dr_rows) if dr_rows else pd.DataFrame(columns=["label", "pct"])

    # ── Figure with two stacked subplots ──────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.10,
        subplot_titles=("Discount Given & Realised P/L", "Discount as % of Revenue"),
    )

    # ── Panel 1: Discount bars ─────────────────────────────────────────────────
    fig.add_trace(go.Bar(
        name="Discount Given",
        x=md_agg["label"], y=md_agg["discount_given"],
        marker_color=COLORS["Discount"],
        marker_line_width=0,
        opacity=0.85,
        hovertemplate="%{x}<br>Discount Given: $%{y:.2f}<extra></extra>",
    ), row=1, col=1)

    # ── Panel 1: Realised P/L — neutral connecting line + colour-coded markers ─
    # Connecting line in neutral grey so sign-coloured markers stand out clearly
    fig.add_trace(go.Scatter(
        name="Realised P/L",
        x=md_agg["label"], y=md_agg["realised_profit"],
        mode="lines+markers",
        line=dict(color="#7F8C8D", width=1.5, dash="dot"),
        marker=dict(
            color=[COLORS["Above Cost"] if v >= 0 else COLORS["Below Cost"]
                   for v in md_agg["realised_profit"]],
            size=10,
            symbol="diamond",
            line=dict(width=1, color="white"),
        ),
        hovertemplate="%{x}<br>Realised P/L: $%{y:.2f}<extra></extra>",
    ), row=1, col=1)

    # Zero reference line for Realised P/L
    fig.add_hline(y=0, line_color="#BDC3C7", line_width=1.2,
                  line_dash="solid", row=1, col=1)

    # ── Panel 2: Discount/Rev % bars ──────────────────────────────────────────
    if not dr.empty:
        bar_colors = ["#D5DBDB" if lbl in partial_labels else "#8E44AD"
                      for lbl in dr["label"]]
        fig.add_trace(go.Bar(
            name="Disc/Rev %",
            x=dr["label"], y=dr["pct"],
            marker_color=bar_colors,
            marker_line_width=0,
            opacity=0.85,
            hovertemplate="%{x}<br>Disc/Rev: %{y:.1f}%<extra></extra>",
            showlegend=True,
        ), row=2, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        height=460,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=0, l=0, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
        barmode="group",
    )
    # Panel 1 axes
    fig.update_yaxes(tickprefix="$", gridcolor="#f0f0f0", row=1, col=1)
    fig.update_xaxes(showgrid=False, row=1, col=1)
    # Panel 2 axes
    fig.update_yaxes(ticksuffix="%", gridcolor="#f0f0f0", rangemode="tozero", row=2, col=1)
    fig.update_xaxes(showgrid=False, row=2, col=1)

    # Partial-period annotation on panel 2
    if partial_labels:
        fig.add_annotation(
            text="⚠ greyed bars = partial period (fewer trading days → inflated %)",
            xref="paper", yref="paper", x=0, y=-0.06,
            showarrow=False, font=dict(size=11, color="#7F8C8D"),
            align="left",
        )

    st.plotly_chart(fig, use_container_width=True)


def _markdown_summary_table(md_agg: pd.DataFrame, rev: pd.DataFrame, groupby: str):
    rows = []
    for _, row in md_agg.iterrows():
        ps = pd.Timestamp(row["period_start"])
        pe = period_end_date(ps, groupby)
        rv = period_revenue(rev, ps, pe)
        dr = f"{row['discount_given'] / rv * 100:.1f}%" if rv > 0 else "—"
        rows.append({
            "Period":        row["label"],
            "Discount ($)":  f"${row['discount_given']:.2f}",
            "Realised P/L":  f"${row['realised_profit']:.2f}",
            "Below-Cost":    int(row["below_cost_lines"]),
            "Rev ($)":       f"${rv:,.0f}" if rv > 0 else "—",
            "Disc/Rev %":    dr,
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — WEEKLY DETAIL
# ══════════════════════════════════════════════════════════════════════════════

def render_weekly_detail(dump: pd.DataFrame, binned: pd.DataFrame,
                         reduced: pd.DataFrame, markdown: pd.DataFrame,
                         rev: pd.DataFrame, has_manual_log: bool):
    # Build week list from dump + binned
    week_pairs = set(
        dump[["week_start", "week_label"]].apply(tuple, axis=1).tolist()
    )
    if has_manual_log and not binned.empty:
        week_pairs |= set(binned[["week_start", "week_label"]].apply(tuple, axis=1).tolist())

    if not week_pairs:
        st.info("No data available.")
        return

    all_weeks  = sorted(week_pairs, reverse=True)
    week_labels = [w[1] for w in all_weeks]
    sel_label   = st.selectbox("Select week:", week_labels)
    sel_start   = next(w[0] for w in all_weeks if w[1] == sel_label)
    sel_end     = sel_start + pd.Timedelta(days=6)

    dump_wk    = dump[dump["week_start"] == sel_start]
    binned_wk  = binned[binned["week_start"] == sel_start] if not binned.empty else pd.DataFrame()
    red_wk     = reduced[reduced["week_start"] == sel_start] if not reduced.empty else pd.DataFrame()
    md_wk      = markdown[markdown["week_start"] == sel_start] if not markdown.empty else pd.DataFrame()
    wk_rev     = period_revenue(rev, sel_start, sel_end)

    total_waste = dump_wk["waste_cost"].sum() + (binned_wk["waste_cost"].sum() if not binned_wk.empty else 0)
    wr = total_waste / wk_rev * 100 if wk_rev > 0 else 0

    cols = st.columns(5 if has_manual_log else 4)
    cols[0].metric("Total Waste", f"${total_waste:.2f}")
    cols[1].metric("GAP Dump", f"${dump_wk['waste_cost'].sum():.2f}")
    if has_manual_log:
        cols[2].metric("Binned", f"${binned_wk['waste_cost'].sum() if not binned_wk.empty else 0:.2f}")
        cols[3].metric("Revenue", f"${wk_rev:,.2f}")
        cols[4].metric("Waste/Rev", f"{wr:.1f}%", delta_color="inverse" if wr > 5 else "off")
    else:
        cols[2].metric("Revenue", f"${wk_rev:,.2f}")
        cols[3].metric("Waste/Rev", f"{wr:.1f}%", delta_color="inverse" if wr > 5 else "off")

    st.markdown("")
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**GAP Dump — this week**")
        if dump_wk.empty:
            st.info("No GAP Dump entries.")
        else:
            disp = dump_wk[["date", "item", "qty", "waste_cost", "reason"]].copy()
            disp["date"] = disp["date"].dt.strftime("%a %d %b")
            disp["waste_cost"] = disp["waste_cost"].map("${:.2f}".format)
            disp["qty"] = disp["qty"].round(2)
            st.dataframe(disp.rename(columns={
                "date": "Date", "item": "Item", "qty": "Qty",
                "waste_cost": "Cost", "reason": "Reason",
            }), hide_index=True, use_container_width=True)
            st.caption(f"Total: **${dump_wk['waste_cost'].sum():.2f}** · {len(dump_wk)} lines")

    with col_r:
        if has_manual_log:
            st.markdown("**Manual Log Binned — this week**")
            if binned_wk.empty:
                st.info("No binned entries.")
            else:
                disp = binned_wk[["date", "item", "qty", "unit", "waste_cost"]].copy()
                disp["date"] = disp["date"].dt.strftime("%a %d %b")
                disp["waste_cost"] = disp["waste_cost"].map("${:.2f}".format)
                disp["qty"] = disp["qty"].round(3)
                st.dataframe(disp.rename(columns={
                    "date": "Date", "item": "Item", "qty": "Qty",
                    "unit": "Unit", "waste_cost": "Cost",
                }), hide_index=True, use_container_width=True)
                st.caption(f"Total: **${binned_wk['waste_cost'].sum():.2f}** · {len(binned_wk)} entries")
        else:
            st.markdown("**GAP Markdown — this week**")
            if md_wk.empty:
                st.info("No markdown entries this week.")
            else:
                disp = md_wk[["date", "item", "discount_given", "realised_profit"]].copy()
                disp["date"] = disp["date"].dt.strftime("%a %d %b")
                disp["discount_given"]   = disp["discount_given"].map("${:.2f}".format)
                disp["realised_profit"]  = disp["realised_profit"].map("${:.2f}".format)
                st.dataframe(disp.rename(columns={
                    "date": "Date", "item": "Item",
                    "discount_given": "Discount", "realised_profit": "Realised P/L",
                }), hide_index=True, use_container_width=True)
                st.caption(
                    f"Total discount: **${md_wk['discount_given'].sum():.2f}** · "
                    f"Realised P/L: **${md_wk['realised_profit'].sum():.2f}** · "
                    f"{len(md_wk)} lines"
                )

    if has_manual_log and not red_wk.empty:
        st.divider()
        st.markdown("**Reduced items this week** *(not waste — sold at reduced price)*")
        disp = red_wk[["date", "item", "qty", "unit", "new_price",
                        "cost_per_unit", "revenue", "cost_total", "net_above_cost"]].copy()
        disp["date"] = disp["date"].dt.strftime("%a %d %b")
        for col in ["new_price", "cost_per_unit", "revenue", "cost_total", "net_above_cost"]:
            disp[col] = disp[col].map("${:.2f}".format)
        disp["qty"] = disp["qty"].round(3)
        st.dataframe(disp.rename(columns={
            "date": "Date", "item": "Item", "qty": "Qty", "unit": "Unit",
            "new_price": "New Price", "cost_per_unit": "Cost/Unit",
            "revenue": "Revenue", "cost_total": "Cost", "net_above_cost": "Net vs Cost",
        }), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — DAILY DETAIL (FV only)
# ══════════════════════════════════════════════════════════════════════════════

def render_daily_detail(binned: pd.DataFrame, reduced: pd.DataFrame,
                        rev: pd.DataFrame):
    avail_dates = sorted(binned["date"].dt.date.unique(), reverse=True)
    if not avail_dates:
        st.warning("No manual log entries found.")
        st.stop()

    sel_date = st.selectbox(
        "Select date:",
        avail_dates,
        format_func=lambda x: x.strftime("%d %B %Y  (%A)"),
    )
    df_bin = binned[binned["date"].dt.date == sel_date]
    df_red = reduced[reduced["date"].dt.date == sel_date] if not reduced.empty else pd.DataFrame()
    day_rev = period_revenue(rev, pd.Timestamp(sel_date), pd.Timestamp(sel_date))

    waste = df_bin["waste_cost"].sum()
    wr = waste / day_rev * 100 if day_rev > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Binned waste cost", f"${waste:.2f}")
    c2.metric("FV Revenue", f"${day_rev:,.2f}")
    c3.metric("Waste/Rev", f"{wr:.1f}%", delta_color="inverse" if wr > 5 else "off")

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Binned**")
        if df_bin.empty:
            st.info("No binned entries for this date.")
        else:
            disp = df_bin[["item", "qty", "unit", "waste_cost"]].copy()
            disp["waste_cost"] = disp["waste_cost"].map("${:.2f}".format)
            disp["qty"] = disp["qty"].round(3)
            st.dataframe(disp.rename(columns={
                "item": "Item", "qty": "Qty", "unit": "Unit", "waste_cost": "Cost",
            }), hide_index=True, use_container_width=True)
    with col_r:
        st.markdown("**Reduced**")
        if df_red.empty:
            st.info("No reduced entries for this date.")
        else:
            disp = df_red[["item", "qty", "unit", "new_price",
                            "cost_per_unit", "net_above_cost"]].copy()
            for col in ["new_price", "cost_per_unit", "net_above_cost"]:
                disp[col] = disp[col].map("${:.2f}".format)
            disp["qty"] = disp["qty"].round(3)
            st.dataframe(disp.rename(columns={
                "item": "Item", "qty": "Qty", "unit": "Unit",
                "new_price": "New Price", "cost_per_unit": "Cost/Unit",
                "net_above_cost": "Net vs Cost",
            }), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Waste Dashboard", page_icon="🗑️", layout="wide")
st.title("🗑️ Waste & Markdown Dashboard")
st.caption("Foodland Wudinna")

# ── Department selector ────────────────────────────────────────────────────────
dept_label = st.radio(
    "Department:",
    options=list(DEPT_LABELS.values()),
    horizontal=True,
    index=0,
)
dept_key      = {v: k for k, v in DEPT_LABELS.items()}[dept_label]
has_manual_log = (dept_key == "FRUIT & VEG")

st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────
try:
    dump_raw     = load_dump(dept_key)
    markdown_raw = load_markdown(dept_key)
    rev_raw      = load_revenue(dept_key)
    if has_manual_log:
        binned_raw  = load_binned()
        reduced_raw = load_reduced()
    else:
        binned_raw  = pd.DataFrame()
        reduced_raw = pd.DataFrame()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

if dump_raw.empty and markdown_raw.empty:
    st.warning("No waste data found for this department.")
    st.stop()

# Add period columns
dump_raw     = add_period_cols(dump_raw)     if not dump_raw.empty     else dump_raw
markdown_raw = add_period_cols(markdown_raw) if not markdown_raw.empty else markdown_raw
if not binned_raw.empty:
    binned_raw = add_period_cols(binned_raw)
if not reduced_raw.empty:
    reduced_raw = add_period_cols(reduced_raw)

# Normalise sub_dept nulls for filter
for _df in [dump_raw, binned_raw, reduced_raw, markdown_raw]:
    if not _df.empty and "sub_dept" in _df.columns:
        _df["sub_dept"] = _df["sub_dept"].fillna("Unknown").replace("None", "Unknown")

# Build sub_dept list from all sources
_sub_sets = []
for _df in [dump_raw, binned_raw, reduced_raw, markdown_raw]:
    if not _df.empty and "sub_dept" in _df.columns:
        _sub_sets += _df["sub_dept"].dropna().unique().tolist()
_all_sub_depts = sorted(set(_sub_sets))


def _apply_sub_dept(df: pd.DataFrame, sel: list) -> pd.DataFrame:
    if df.empty or "sub_dept" not in df.columns:
        return df
    return df[df["sub_dept"].isin(sel)]


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Waste Dashboard")
    st.divider()

    max_date = dump_raw["date"].max() if not dump_raw.empty else pd.Timestamp.now()
    period_opt = st.radio("Period:", ["Last 4 wks", "Last 8 wks", "YTD", "All"],
                          horizontal=False, index=1)
    if period_opt == "Last 4 wks":
        cutoff = max_date - pd.Timedelta(weeks=4)
    elif period_opt == "Last 8 wks":
        cutoff = max_date - pd.Timedelta(weeks=8)
    elif period_opt == "YTD":
        cutoff = pd.Timestamp(max_date.year, 1, 1)
    else:
        cutoff = pd.Timestamp("2000-01-01")

    groupby = st.radio("Group by:", ["Week", "Month"], horizontal=True).lower()

    st.divider()
    st.markdown("**Sub-department**")
    sel_sub_depts = st.pills(
        label="sub_dept_filter",
        options=_all_sub_depts,
        default=_all_sub_depts,
        selection_mode="multi",
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**Cost basis**")
    if has_manual_log:
        st.caption(
            "• GAP Dump → invoice cost (total_cost_ex)\n"
            "• Log Binned → qty × cost_price (ref_item_price)\n"
            "• Log Reduced → new_price × qty vs cost\n"
            "• Stir Fry / Fruit Plate → excluded (store use)"
        )
    else:
        st.caption("• GAP Dump → invoice cost (total_cost_ex)\n• Manual log: not available")

    st.divider()
    st.markdown("**Benchmarks**")
    st.markdown("| Metric | Target |\n|---|---|\n| Waste / Revenue | < 5% |")

    st.divider()
    d_range = (f"{dump_raw['date'].min().strftime('%d %b')} – "
               f"{dump_raw['date'].max().strftime('%d %b %Y')}") if not dump_raw.empty else "—"
    md_range = (f"{markdown_raw['date'].min().strftime('%d %b')} – "
                f"{markdown_raw['date'].max().strftime('%d %b %Y')}") if not markdown_raw.empty else "—"
    st.caption(
        f"**GAP Dump:** {len(dump_raw)} lines · {d_range}\n\n"
        f"**GAP Markdown:** {len(markdown_raw)} lines · {md_range}"
        + (f"\n\n**Manual Log:** {len(binned_raw) + len(reduced_raw)} entries"
           if has_manual_log else "")
    )
    if st.button("↺ Refresh"):
        st.cache_data.clear()
        st.rerun()

# ── Apply filters ──────────────────────────────────────────────────────────────
_sel = sel_sub_depts if sel_sub_depts else _all_sub_depts

dump_view     = _apply_sub_dept(dump_raw,     _sel)
markdown_view = _apply_sub_dept(markdown_raw, _sel)
rev_view      = _apply_sub_dept(rev_raw,      _sel)
binned_view   = _apply_sub_dept(binned_raw,   _sel) if not binned_raw.empty  else binned_raw
reduced_view  = _apply_sub_dept(reduced_raw,  _sel) if not reduced_raw.empty else reduced_raw

date_filter = (cutoff, max_date)

# ── Tabs ───────────────────────────────────────────────────────────────────────
if has_manual_log:
    tab_waste, tab_markdown, tab_weekly, tab_daily = st.tabs([
        "📦 Total Waste", "📉 Markdown & Reductions", "📅 Weekly Detail", "📋 Daily Detail"
    ])
else:
    tab_waste, tab_markdown, tab_weekly = st.tabs([
        "📦 Total Waste", "📉 Markdown & Reductions", "📅 Weekly Detail"
    ])

with tab_waste:
    st.subheader(f"Total Waste Cost — {dept_label}")
    st.caption(
        "Stock that generated **zero revenue** — dumped or disposed. "
        + ("GAP Dump covers barcoded products; Manual Log covers loose/weight items."
           if has_manual_log else
           "GAP Dump data only — loose/weight item waste not tracked for this department.")
    )
    render_waste_section(dump_view, binned_view, rev_view, groupby,
                         date_filter, has_manual_log)

with tab_markdown:
    st.subheader(f"Markdown & Reductions — {dept_label}")
    st.caption(
        "Items that were **discounted but sold**. "
        "Negative realised profit means the item was sold below cost — a real monetary loss."
    )
    render_markdown_section(markdown_view, reduced_view, rev_view, groupby,
                            date_filter, has_manual_log)

with tab_weekly:
    st.subheader(f"Weekly Detail — {dept_label}")
    render_weekly_detail(dump_view, binned_view, reduced_view, markdown_view,
                         rev_view, has_manual_log)

if has_manual_log:
    with tab_daily:
        st.subheader("Daily Detail")
        st.caption("Manual Log only — GAP Dump dates reflect POS entry, not necessarily the actual disposal date.")
        render_daily_detail(binned_view, reduced_view, rev_view)
