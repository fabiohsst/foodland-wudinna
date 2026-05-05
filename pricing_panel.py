"""
pricing_panel.py — Price Update Panel
Foodland Wudinna Fruit & Veg

Interactive review and approval of Freshlink invoice price changes.

Run with:  streamlit run pricing_panel.py --server.port 8508
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Price Update Panel",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 3.5rem; }
    div[data-testid="metric-container"] { background: #f8f9fa; border-radius: 8px; padding: 10px 16px; }
</style>
""", unsafe_allow_html=True)


# ── Imports ───────────────────────────────────────────────────────────────────
from pricing.generate_price_updates import (
    parse_invoice,
    process_invoice,
    load_item_prices,
    load_mapping,
    load_price_history as pricing_load_history,
    load_current_specials,
)
from db import (
    load_invoice_mapping,
    load_price_history,
    upsert_item_prices,
    append_price_history,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def results_to_df(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        flag    = str(r.get("Flag", ""))
        special = bool(r.get("On Special"))
        flagged = bool(flag) and "On special" not in flag
        if special:   status = "On special"
        elif flagged: status = "Flagged"
        else:         status = "OK"
        rows.append({
            "Approve":      r.get("Approve") == "Y",
            "Status":       status,
            "POS Item":     r.get("POS Item", ""),
            "Invoice Line": r.get("Invoice Line", ""),
            "Unit":         r.get("Sell Unit", ""),
            "Units/Inv":    r.get("Units/Invoice"),
            "New Cost":     r.get("New Cost/Unit"),
            "Prev Cost":    r.get("Prev Cost/Unit") or None,
            "Cost Chg%":    r.get("Cost Δ%") or None,
            "Curr Sell":    r.get("Current Sell") or None,
            "Sugg Sell":    r.get("Suggested Sell"),
            "Sell Chg%":    r.get("Sell Δ%") or None,
            "GP%":          r.get("GP% @ Suggested") or None,
            "Flag":         flag,
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🏷️ Price Update Panel")
    st.caption("Foodland Wudinna — Fruit & Veg")
    st.divider()

    mapping_df = load_invoice_mapping()
    total_m = len(mapping_df)
    verif_m = int(mapping_df["verified"].sum()) if not mapping_df.empty else 0
    st.markdown("**Mapping status**")
    c1, c2 = st.columns(2)
    c1.metric("Total entries", total_m)
    c2.metric("Verified", verif_m)
    if verif_m < total_m:
        st.warning(f"{total_m - verif_m} unverified")

    st.divider()
    st.markdown("**Settings**")
    st.caption("GP target: **40%**  |  Flag threshold: **±15%**")
    st.caption("Prices rounded up to nearest X.X9")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AREA — TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_review, tab_history = st.tabs(["Invoice Review", "Price History"])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — INVOICE REVIEW
# ─────────────────────────────────────────────────────────────────────────────
with tab_review:

    # on_change callback: fires the moment the user selects a file.
    # At this point uploaded IS non-None and getvalue() works reliably.
    # We read the bytes immediately and store them — after this the
    # file object may return None on subsequent reruns (known Streamlit bug).
    def _on_upload():
        f = st.session_state.get("_uploader")
        if f is not None:
            st.session_state["_pending_bytes"] = f.getvalue()
            st.session_state["_pending_name"]  = f.name
            st.session_state["_pending_key"]   = f"{f.name}_{f.size}"
        else:
            # User cleared the uploader
            for k in ["_pending_bytes", "_pending_name", "_pending_key",
                      "_last_file", "_results", "_unmatched",
                      "_inv_no", "_inv_date", "_applied"]:
                st.session_state.pop(k, None)

    st.file_uploader(
        "Drag a Freshlink invoice here (PDF or CSV)",
        type=["pdf", "csv"],
        key="_uploader",
        on_change=_on_upload,
    )

    # ── Step 1: process if we have new pending bytes ──────────────────────────
    if "_pending_bytes" in st.session_state:
        file_key = st.session_state["_pending_key"]

        if st.session_state.get("_last_file") != file_key:
            with st.spinner("Parsing invoice…"):
                try:
                    suffix = Path(st.session_state["_pending_name"]).suffix.lower()
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(st.session_state["_pending_bytes"])
                        tmp_path = Path(tmp.name)

                    rows_parsed = parse_invoice(tmp_path)
                    tmp_path.unlink(missing_ok=True)

                    if not rows_parsed:
                        st.error("No invoice lines found in the file.")
                    else:
                        inv_date = rows_parsed[0].get("date", date.today().isoformat())
                        inv_no   = rows_parsed[0].get("invoice_no", Path(st.session_state["_pending_name"]).stem)

                        results, unmatched = process_invoice(
                            rows_parsed,
                            load_mapping(),
                            load_item_prices(),
                            pricing_load_history(),
                            load_current_specials(),
                            inv_date,
                            inv_no,
                        )

                        st.session_state["_last_file"] = file_key
                        st.session_state["_results"]   = results
                        st.session_state["_unmatched"] = unmatched
                        st.session_state["_inv_no"]    = inv_no
                        st.session_state["_inv_date"]  = inv_date
                        st.session_state["_applied"]   = False

                except Exception as e:
                    st.error(f"Failed to process invoice: {e}")
                    st.exception(e)

    # ── Step 2: display results ───────────────────────────────────────────────
    if "_results" not in st.session_state:
        st.caption("Upload an invoice above to get started.")
    else:
        results   = st.session_state["_results"]
        unmatched = st.session_state["_unmatched"]
        inv_no    = st.session_state["_inv_no"]
        inv_date  = st.session_state["_inv_date"]

        df = results_to_df(results)

        # Summary metrics
        st.divider()
        n_flagged  = int((df["Status"] == "Flagged").sum())
        n_approved = int(df["Approve"].sum())
        n_unmatched = len(unmatched)

        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        mc1.metric("Invoice lines",  len(df) + n_unmatched)
        mc2.metric("Matched",        len(df))
        mc3.metric("Auto-approved",  n_approved)
        mc4.metric("Flagged",        n_flagged)
        mc5.metric("Unmatched",      n_unmatched)
        st.caption(f"Invoice **{inv_no}** · {inv_date}")

        # Filter controls
        st.divider()
        fc1, fc2, _ = st.columns([2, 2, 4])
        show = fc1.selectbox(
            "Show", ["All", "Flagged", "Auto-approved", "On special"],
            label_visibility="collapsed",
        )
        search = fc2.text_input(
            "Search", placeholder="Filter by name…",
            label_visibility="collapsed",
        )

        view = df.copy()
        if show == "Flagged":
            view = view[view["Status"] == "Flagged"]
        elif show == "Auto-approved":
            view = view[view["Status"] == "OK"]
        elif show == "On special":
            view = view[view["Status"] == "On special"]
        if search:
            view = view[view["POS Item"].str.upper().str.contains(search.upper(), na=False)]

        # Editable table
        st.markdown("**Tick Approve to include a price change, untick to skip**")
        edited = st.data_editor(
            view,
            use_container_width=True,
            hide_index=True,
            height=min(40 + len(view) * 35, 600),
            disabled=[c for c in view.columns if c != "Approve"],
            key="review_editor",
        )

        # Merge edits back when a filter is active
        if len(edited) == len(df):
            df_final = edited
        else:
            df_final = df.copy()
            df_final.loc[view.index, "Approve"] = edited["Approve"].values

        n_to_apply = int(df_final["Approve"].sum())

        # Apply section
        st.divider()
        if st.session_state.get("_applied"):
            st.success(f"✅ Prices applied for invoice {inv_no}. Upload a new invoice to continue.")
        else:
            bcol1, bcol2 = st.columns([2, 6])
            apply_btn = bcol1.button(
                f"Apply {n_to_apply} price change{'s' if n_to_apply != 1 else ''}",
                type="primary",
                disabled=(n_to_apply == 0),
            )
            bcol2.caption(f"{n_to_apply} selected · {len(df_final) - n_to_apply} skipped")

            if apply_btn:
                price_rows   = []
                history_rows = []
                for _, row in df_final[df_final["Approve"]].iterrows():
                    name = row["POS Item"]
                    sell = row["Sugg Sell"]
                    cost = row["New Cost"]
                    if not name or not sell or not cost:
                        continue
                    price_rows.append({
                        "Name":         name,
                        "sell_price":   float(sell),
                        "cost_price":   round(float(cost), 4),
                        "price_source": "invoice",
                    })
                    history_rows.append({
                        "date":          inv_date,
                        "invoice_no":    inv_no,
                        "pos_name":      name,
                        "cost_per_unit": round(float(cost), 4),
                        "sell_price":    float(sell),
                        "gp_pct":        row.get("GP%"),
                        "source":        f"invoice_{inv_no}",
                    })

                with st.spinner("Writing to database…"):
                    written  = upsert_item_prices(price_rows)
                    inserted = append_price_history(history_rows)

                st.session_state["_applied"] = True
                st.success(
                    f"✅ {written} price{'s' if written != 1 else ''} updated · "
                    f"{inserted} history record{'s' if inserted != 1 else ''} saved "
                    f"(invoice {inv_no})"
                )

        # Unmatched
        if unmatched:
            with st.expander(f"⚠️ {len(unmatched)} unmatched lines"):
                st.caption("Add these to invoice_item_mapping.csv and re-upload.")
                for u in unmatched:
                    st.code(u)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — PRICE HISTORY
# ─────────────────────────────────────────────────────────────────────────────
with tab_history:

    hist_df = load_price_history()

    if hist_df.empty:
        st.info("No price history recorded yet.")
    else:
        hist_df["date"] = pd.to_datetime(hist_df["date"], errors="coerce")
        hist_df = hist_df.sort_values("date", ascending=False)

        hc1, hc2, hc3 = st.columns(3)
        hc1.metric("Total records",    len(hist_df))
        hc2.metric("Products tracked", hist_df["pos_name"].nunique())
        hc3.metric("Invoices logged",  hist_df["invoice_no"].nunique())
        st.divider()

        fc1, fc2 = st.columns([3, 3])
        search_h = fc1.text_input(
            "Filter by product", placeholder="Type a product name…",
            key="hist_search", label_visibility="collapsed",
        )
        inv_list = ["All invoices"] + sorted(
            hist_df["invoice_no"].dropna().unique().tolist(), reverse=True
        )
        sel_inv = fc2.selectbox("Invoice", inv_list, label_visibility="collapsed")

        view_h = hist_df.copy()
        if search_h:
            view_h = view_h[view_h["pos_name"].str.upper().str.contains(search_h.upper(), na=False)]
        if sel_inv != "All invoices":
            view_h = view_h[view_h["invoice_no"] == sel_inv]

        disp = view_h[["date", "invoice_no", "pos_name", "cost_per_unit", "sell_price", "gp_pct", "source"]].copy()
        disp["date"] = disp["date"].dt.strftime("%d %b %Y")

        st.dataframe(disp, use_container_width=True, hide_index=True,
                     height=min(40 + len(disp) * 35, 580))
