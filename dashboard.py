"""
dashboard.py — Foodland Wudinna Store Dashboard
Entry point for the multi-page performance suite.

Run with:  streamlit run dashboard.py
Launch via: double-click "Launch Dashboard.bat"
"""

import streamlit as st

st.set_page_config(
    page_title="Foodland Wudinna — Dashboard",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Top navigation CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Hide default Streamlit header padding */
.block-container { padding-top: 1rem; }

/* Nav bar container */
.nav-bar {
    display: flex;
    gap: 6px;
    background: #1A5276;
    padding: 10px 16px;
    border-radius: 8px;
    margin-bottom: 4px;
    align-items: center;
}
.nav-title {
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
    white-space: nowrap;
    margin-right: 16px;
    letter-spacing: 0.3px;
}
.nav-spacer { flex: 1; }

/* Override Streamlit button styles inside the nav */
div[data-testid="stHorizontalBlock"] button {
    border-radius: 6px !important;
    font-size: 13px !important;
    padding: 6px 14px !important;
    transition: background 0.15s;
}
</style>
""", unsafe_allow_html=True)

# ── Page definitions ───────────────────────────────────────────────────────────
PAGES = {
    "📈 Store Pulse":            "pulse",
    "🛒 Category Intelligence":  "category",
    "♻️ Waste & Operations":     "waste",
    "🏷️ Promotions":             "promotions",
    "🎯 Ordering Accuracy":      "ordering",
}

PHASE_BADGE = {
    "pulse":      "",
    "category":   "",
    "waste":      "",
    "promotions": " ·phase 2",
    "ordering":   " ·phase 3",
}

# ── Session state default ──────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state["page"] = "pulse"

# ── Header + navigation bar ────────────────────────────────────────────────────
st.markdown(
    '<div class="nav-bar">'
    '<span class="nav-title">🛒 Foodland Wudinna</span>'
    '</div>',
    unsafe_allow_html=True,
)

nav_cols = st.columns(len(PAGES))
for col, (label, key) in zip(nav_cols, PAGES.items()):
    is_active = st.session_state["page"] == key
    if col.button(
        label,
        key=f"nav_{key}",
        use_container_width=True,
        type="primary" if is_active else "secondary",
    ):
        st.session_state["page"] = key
        st.rerun()

st.divider()

# ── Route to selected page ─────────────────────────────────────────────────────
current = st.session_state["page"]

if current == "pulse":
    from dash.pulse import render
    render()

elif current == "category":
    from dash.category import render
    render()

elif current == "waste":
    from dash.waste import render
    render()

elif current == "promotions":
    from dash.promotions import render
    render()

elif current == "ordering":
    from dash.ordering import render
    render()
