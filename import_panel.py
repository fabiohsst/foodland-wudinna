"""
import_panel.py — Data Import Panel
Foodland Wudinna

Simple browser-based interface for importing data files into the database.
No command line required.

Supported file types:
  Sales Report    (.csv)   → fact_sales
  Dump Report     (.xlsx)  → fact_dump
  Markdown Report (.csv)   → fact_markdown
  Waste Log       (.xlsx)  → fact_waste_log

Launch: streamlit run import_panel.py --server.port 8506
"""

import io
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Import parsers and DB writers from existing scripts ───────────────────────
from import_sales import load_csv as _parse_sales_csv, build_rows as _build_sales_rows
from import_waste import (
    parse_dump        as _parse_dump,
    parse_markdown_csv as _parse_markdown,
    parse_waste_log   as _parse_waste_log,
    load_dump         as _db_load_dump,
    load_markdown_rows as _db_load_markdown,
    load_waste_log_rows as _db_load_waste_log,
    build_apn_map, build_name_map,
)
from db import import_sales_rows, _write_conn


# ── Import type definitions ───────────────────────────────────────────────────

TYPES = {
    "sales": {
        "label":   "Sales Report",
        "emoji":   "🧾",
        "desc":    "Weekly POS export",
        "hint":    "CSV file (.csv)",
        "exts":    ["csv"],
    },
    "dump": {
        "label":   "Dump Report",
        "emoji":   "🗑️",
        "desc":    "GAP waste dump report",
        "hint":    "Excel file (.xlsx)",
        "exts":    ["xlsx"],
    },
    "markdown": {
        "label":   "Markdown Report",
        "emoji":   "📉",
        "desc":    "GAP markdown export",
        "hint":    "CSV file (.csv)",
        "exts":    ["csv"],
    },
    "waste_log": {
        "label":   "Waste Log",
        "emoji":   "📋",
        "desc":    "Manual FV waste log",
        "hint":    "Excel file (.xlsx)",
        "exts":    ["xlsx"],
    },
}


# ── Session state helpers ─────────────────────────────────────────────────────

def _reset():
    """Clear all import-related session state and return to the first step."""
    for k in ["import_type", "file_bytes", "file_name", "preview", "result"]:
        st.session_state.pop(k, None)
    st.session_state["step"] = "select"


def _go(step: str):
    st.session_state["step"] = step


# ── Preview ───────────────────────────────────────────────────────────────────

def _preview_sales(file_bytes: bytes, file_name: str) -> dict:
    df = _parse_sales_csv(io.BytesIO(file_bytes))
    dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
    depts = (
        df.get("Department Name", pd.Series(dtype=str))
        .dropna()
        .value_counts()
        .to_dict()
    )
    return {
        "rows":     len(df),
        "date_min": dates.min().strftime("%d %b %Y") if not dates.empty else "—",
        "date_max": dates.max().strftime("%d %b %Y") if not dates.empty else "—",
        "groups":   depts,
        "group_label": "Departments",
        "_df":      df,
    }


def _preview_dump(file_bytes: bytes, file_name: str) -> dict:
    period_start, period_end, rows = _parse_dump(io.BytesIO(file_bytes))
    dept_counts: dict = {}
    for r in rows:
        d = r.get("department") or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
    return {
        "rows":      len(rows),
        "date_min":  period_start or "—",
        "date_max":  period_end   or "—",
        "groups":    dept_counts,
        "group_label": "Departments",
        "_rows":     rows,
        "_period_start": period_start,
    }


def _preview_markdown(file_bytes: bytes, file_name: str) -> dict:
    rows = _parse_markdown(io.BytesIO(file_bytes))
    dept_counts: dict = {}
    dates = []
    for r in rows:
        d = r.get("department") or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
        if r.get("date_id"):
            dates.append(r["date_id"])
    return {
        "rows":      len(rows),
        "date_min":  min(dates) if dates else "—",
        "date_max":  max(dates) if dates else "—",
        "groups":    dept_counts,
        "group_label": "Departments",
        "_rows":     rows,
    }


def _preview_waste_log(file_bytes: bytes, file_name: str) -> dict:
    rows = _parse_waste_log(io.BytesIO(file_bytes))
    action_counts: dict = {}
    dates = []
    for r in rows:
        a = r.get("action") or "Unknown"
        action_counts[a] = action_counts.get(a, 0) + 1
        if r.get("date_id"):
            dates.append(r["date_id"])
    return {
        "rows":      len(rows),
        "date_min":  min(dates) if dates else "—",
        "date_max":  max(dates) if dates else "—",
        "groups":    action_counts,
        "group_label": "Entry types",
        "_rows":     rows,
    }


def _build_preview(import_type: str, file_bytes: bytes, file_name: str) -> dict:
    if import_type == "sales":
        return _preview_sales(file_bytes, file_name)
    if import_type == "dump":
        return _preview_dump(file_bytes, file_name)
    if import_type == "markdown":
        return _preview_markdown(file_bytes, file_name)
    return _preview_waste_log(file_bytes, file_name)


# ── Import ────────────────────────────────────────────────────────────────────

def _do_import(import_type: str, file_bytes: bytes, file_name: str, preview: dict) -> dict:
    if import_type == "sales":
        rows = _build_sales_rows(preview["_df"], file_name)
        inserted, skipped = import_sales_rows(rows)
        return {"inserted": inserted, "skipped": skipped}

    if import_type == "dump":
        with _write_conn() as conn:
            apn_map  = build_apn_map(conn)
            name_map = build_name_map(conn)
            n = _db_load_dump(
                preview["_rows"], apn_map, name_map,
                preview.get("_period_start"), file_name, conn,
            )
        return {"inserted": n, "skipped": 0}

    if import_type == "markdown":
        with _write_conn() as conn:
            apn_map  = build_apn_map(conn)
            name_map = build_name_map(conn)
            n = _db_load_markdown(preview["_rows"], apn_map, name_map, file_name, conn)
        return {"inserted": n, "skipped": 0}

    # waste_log
    with _write_conn() as conn:
        name_map = build_name_map(conn)
        cost_map = {
            pid: cost
            for pid, cost in conn.execute(
                "SELECT product_id, cost_price FROM ref_item_price WHERE cost_price IS NOT NULL"
            )
        }
        n = _db_load_waste_log(preview["_rows"], name_map, cost_map, file_name, conn)
    return {"inserted": n, "skipped": 0}


# ── Render helpers ────────────────────────────────────────────────────────────

def _render_preview_card(preview: dict):
    row_count = preview["rows"]
    if row_count == 0:
        st.warning("The file appears to be empty — nothing to import.")
        return

    st.success(f"✅  **{row_count:,} rows** found in the file")
    st.markdown("")

    c1, c2 = st.columns(2)
    c1.metric("From", preview["date_min"])
    c2.metric("To",   preview["date_max"])

    groups = preview.get("groups") or {}
    if groups:
        st.markdown(f"**{preview.get('group_label', 'Breakdown')}**")
        parts = "  ·  ".join(
            f"{k}  ({v:,})" for k, v in sorted(groups.items())
        )
        st.caption(parts)


def _step_indicator(current: str):
    steps  = ["select", "upload", "preview", "done"]
    labels = ["Choose type", "Upload file", "Preview", "Done"]
    idx    = steps.index(current) if current in steps else 0
    cols   = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, labels)):
        if i < idx:
            col.markdown(f"<div style='text-align:center;color:#aaa;font-size:12px'>✓ {label}</div>", unsafe_allow_html=True)
        elif i == idx:
            col.markdown(f"<div style='text-align:center;color:#1a73e8;font-weight:600;font-size:12px'>● {label}</div>", unsafe_allow_html=True)
        else:
            col.markdown(f"<div style='text-align:center;color:#ccc;font-size:12px'>○ {label}</div>", unsafe_allow_html=True)
    st.markdown("")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Import Data", page_icon="📥", layout="centered")
st.title("📥 Import Data")
st.caption("Foodland Wudinna")
st.divider()

# Initialise step
if "step" not in st.session_state:
    st.session_state["step"] = "select"

step = st.session_state["step"]

_step_indicator(step)


# ── Step 1: Choose type ───────────────────────────────────────────────────────
if step == "select":
    st.markdown("### What are you importing?")
    st.markdown("")

    col_a, col_b = st.columns(2)
    tiles = list(TYPES.items())

    for i, (key, info) in enumerate(tiles):
        col = col_a if i % 2 == 0 else col_b
        with col:
            if st.button(
                f"{info['emoji']}  **{info['label']}**\n\n"
                f"{info['desc']}\n\n"
                f"*{info['hint']}*",
                use_container_width=True,
                key=f"tile_{key}",
            ):
                st.session_state["import_type"] = key
                _go("upload")
                st.rerun()


# ── Step 2: Upload file ───────────────────────────────────────────────────────
elif step == "upload":
    import_type = st.session_state.get("import_type", "sales")
    info = TYPES[import_type]

    st.markdown(f"### {info['emoji']}  Upload your {info['label']}")
    st.caption(f"Expected format: **{info['hint']}**")
    st.markdown("")

    # File uploader — cache bytes immediately to survive Streamlit reruns
    uploaded = st.file_uploader(
        "Drop your file here or click Browse",
        type=info["exts"],
        key="uploader",
        label_visibility="collapsed",
    )
    if uploaded is not None:
        st.session_state["file_bytes"] = uploaded.read()
        st.session_state["file_name"]  = uploaded.name

    file_ready = bool(st.session_state.get("file_bytes"))

    if file_ready:
        st.caption(f"📎  **{st.session_state['file_name']}** — ready")

    st.markdown("")
    col_back, col_next = st.columns([1, 4])
    with col_back:
        if st.button("← Back"):
            _reset()
            st.rerun()
    with col_next:
        if file_ready:
            if st.button("Preview →", type="primary"):
                st.session_state.pop("preview", None)   # force fresh parse
                _go("preview")
                st.rerun()


# ── Step 3: Preview ───────────────────────────────────────────────────────────
elif step == "preview":
    import_type = st.session_state.get("import_type", "sales")
    file_bytes  = st.session_state.get("file_bytes", b"")
    file_name   = st.session_state.get("file_name", "unknown")
    info        = TYPES[import_type]

    st.markdown(f"### {info['emoji']}  {info['label']} — Preview")
    st.caption(f"File: **{file_name}**")
    st.markdown("")

    # Parse once and cache in session state
    if "preview" not in st.session_state:
        with st.spinner("Reading file…"):
            try:
                st.session_state["preview"] = _build_preview(
                    import_type, file_bytes, file_name
                )
            except Exception as exc:
                st.error(
                    "⚠️  Could not read the file.\n\n"
                    "Please make sure you selected the correct file type and try again.\n\n"
                    f"*Detail: {exc}*"
                )
                if st.button("← Start over"):
                    _reset()
                    st.rerun()
                st.stop()

    preview = st.session_state["preview"]
    _render_preview_card(preview)

    if preview["rows"] == 0:
        if st.button("← Start over"):
            _reset()
            st.rerun()
        st.stop()

    st.markdown("")
    col_back, col_import = st.columns([1, 4])
    with col_back:
        if st.button("← Back"):
            st.session_state.pop("preview", None)
            _go("upload")
            st.rerun()
    with col_import:
        btn_label = f"Import {preview['rows']:,} rows  ▶"
        if st.button(btn_label, type="primary"):
            with st.spinner("Importing into database…"):
                try:
                    result = _do_import(import_type, file_bytes, file_name, preview)
                    st.session_state["result"] = result
                    _go("done")
                    st.rerun()
                except Exception as exc:
                    st.error(
                        "⚠️  Import failed.\n\n"
                        "The file was not saved. Please try again or contact Fábio.\n\n"
                        f"*Detail: {exc}*"
                    )


# ── Step 4: Done ──────────────────────────────────────────────────────────────
elif step == "done":
    import_type = st.session_state.get("import_type", "sales")
    file_name   = st.session_state.get("file_name", "unknown")
    result      = st.session_state.get("result", {})
    info        = TYPES[import_type]

    inserted = result.get("inserted", 0)
    skipped  = result.get("skipped",  0)

    st.balloons()
    st.success("## ✅  Import complete!")
    st.markdown("")

    c1, c2 = st.columns(2)
    c1.metric("Rows added to database", f"{inserted:,}")
    if skipped > 0:
        c2.metric("Skipped (already in database)", f"{skipped:,}")

    st.markdown("")
    st.caption(
        f"**{info['label']}** — {file_name}  \n"
        f"Imported: {datetime.now().strftime('%d %b %Y at %H:%M')}"
    )

    st.markdown("")
    if st.button("📥  Import another file", type="primary"):
        _reset()
        st.rerun()
