"""
build_dim_item.py
Generates dim_item.csv — one row per unique item sold in the Fruit & Veg dept.

The item list is derived from actual sales transactions (not just item_reference.csv,
which is incomplete). item_reference.csv provides the PLU number where available.

Sources:
  - sales_fruit_2025.csv    : primary item universe + ABC classification (full year)
  - sales_fruit_2026.csv    : sub-department (has Sub Department Name column)
  - item_reference.csv      : PLU enrichment (best-effort match by name)

Output: ../07_powerbi/data/dim_item.csv
"""

import pandas as pd
import numpy as np
import re
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
ROOT       = SCRIPT_DIR.parent
REF_CSV    = ROOT / "01_data" / "reference" / "item_reference.csv"
OUTPUT     = SCRIPT_DIR / "data" / "dim_item.csv"

# CSV fallbacks (used only if SQLite DB is unavailable)
SALES_2025 = ROOT / "01_data" / "raw" / "sales_fruit_2025.csv"
SALES_2026 = ROOT / "01_data" / "raw" / "sales_fruit_2026.csv"

EXCLUDE_PATTERN = r"FRUIT AND VEG|REDUCED FRUIT"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def normalise_name(s):
    """Collapse embedded newlines and extra whitespace from POS export names."""
    return re.sub(r"\s+", " ", str(s)).strip()

# ── Load and normalise sales data ─────────────────────────────────────────────
def _load_year(year: int) -> pd.DataFrame:
    """Load one year of sales from SQLite; fall back to CSV if unavailable."""
    try:
        from db import load_sales as _db_load
        df = _db_load()
        if not df.empty:
            df = df[df["Year"] == year].copy()
            # Restore columns expected by downstream logic
            df = df.rename(columns={"SubDept": "Sub Department Name", "Qty": "Quantity"})
            df["APN"] = None   # APN not stored in sales table; PLU via item_reference
            return df
    except Exception:
        pass
    # CSV fallback
    path = SALES_2025 if year == 2025 else SALES_2026
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()
    df["Name"] = df["Name"].apply(normalise_name)
    return df

s25 = _load_year(2025)
s26 = _load_year(2026)
s25["Name"] = s25["Name"].apply(normalise_name)
s26["Name"] = s26["Name"].apply(normalise_name)

# ── Build item universe from 2025 sales (full year, most complete) ────────────
# Exclude catch-all rows (no APN or name matches exclusion pattern)
s25_clean = s25[
    ~s25["Name"].str.upper().str.contains(EXCLUDE_PATTERN, na=False)
].copy()
s26_clean = s26[
    ~s26["Name"].str.upper().str.contains(EXCLUDE_PATTERN, na=False)
].copy()

# Union of all item names from both years
all_names = pd.Series(
    pd.concat([s25_clean["Name"], s26_clean["Name"]]).unique()
).sort_values().reset_index(drop=True)
dim = pd.DataFrame({"name": all_names})

# ── Sub-department from 2026 (has Sub Department Name column) ─────────────────
SUBDEPT_COL = "Sub Department Name"

def mode_val(series):
    clean = series.dropna()
    clean = clean[clean.str.strip() != ""]
    return clean.mode().iloc[0] if not clean.empty else "Unknown"

if SUBDEPT_COL in s26.columns:
    subdept_map = (
        s26_clean.groupby("Name")[SUBDEPT_COL]
        .agg(mode_val)
        .reset_index()
        .rename(columns={"Name": "name", SUBDEPT_COL: "sub_department"})
    )
    # Normalise POS catch-all label
    subdept_map["sub_department"] = subdept_map["sub_department"].replace(
        "Fruit & Vege Department Open", "Misc"
    )
    dim = dim.merge(subdept_map, on="name", how="left")
    dim["sub_department"] = dim["sub_department"].fillna("Unknown")
else:
    dim["sub_department"] = "Unknown"

# ── APN: most recent non-null APN per item ────────────────────────────────────
apn_map = (
    pd.concat([
        s26_clean[s26_clean["APN"].notna()][["Name", "APN"]],
        s25_clean[s25_clean["APN"].notna()][["Name", "APN"]],
    ])
    .drop_duplicates(subset="Name", keep="first")
    .rename(columns={"Name": "name", "APN": "apn"})
)
dim = dim.merge(apn_map, on="name", how="left")

# ── PLU from item_reference (best-effort name match) ─────────────────────────
try:
    from db import load_item_reference as _db_ref
    ref = _db_ref()
    ref["name"] = ref["name"].apply(normalise_name)
    ref = ref.rename(columns={"plu": "plu", "name": "ref_name"})
except Exception:
    ref = pd.read_csv(REF_CSV)
    ref.columns = ref.columns.str.strip()
    ref["Name"] = ref["Name"].apply(normalise_name)
    ref = ref.rename(columns={"PLU": "plu", "Name": "ref_name"})

dim = dim.merge(ref.rename(columns={"ref_name": "name"}), on="name", how="left")

# ── ABC classification from 2025 (full year) ──────────────────────────────────
rev_col = "Sales Ex GST"
s25_clean[rev_col] = pd.to_numeric(s25_clean[rev_col], errors="coerce").fillna(0)

item_rev = (
    s25_clean.groupby("Name")[rev_col]
    .sum()
    .sort_values(ascending=False)
    .reset_index()
    .rename(columns={"Name": "name", rev_col: "revenue_2025"})
)

total = item_rev["revenue_2025"].sum()
item_rev["cumshare"] = item_rev["revenue_2025"].cumsum() / total
item_rev["abc_class"] = np.where(
    item_rev["cumshare"].shift(1, fill_value=0) < 0.80, "A",
    np.where(item_rev["cumshare"].shift(1, fill_value=0) < 0.95, "B", "C")
)

dim = dim.merge(item_rev[["name", "revenue_2025", "abc_class"]], on="name", how="left")
dim["abc_class"]    = dim["abc_class"].fillna("C")
dim["revenue_2025"] = dim["revenue_2025"].fillna(0).round(2)

# ── Surrogate key and column order ────────────────────────────────────────────
dim = dim.sort_values("name").reset_index(drop=True)
dim.insert(0, "item_key", dim.index + 1)

dim = dim[["item_key", "plu", "apn", "name", "sub_department", "abc_class", "revenue_2025"]]

# ── Save ──────────────────────────────────────────────────────────────────────
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
dim.to_csv(OUTPUT, index=False)

ref_coverage = dim["plu"].notna().sum()
apn_coverage = dim["apn"].notna().sum()

print(f"dim_item saved → {OUTPUT}")
print(f"  Total items      : {len(dim):,}")
print(f"  PLU mapped       : {ref_coverage:,} / {len(dim):,}")
print(f"  APN populated    : {apn_coverage:,} / {len(dim):,}")
print(f"\n  ABC breakdown:")
print(dim["abc_class"].value_counts().to_string())
print(f"\n  Sub-dept coverage:")
print(dim["sub_department"].value_counts().to_string())
