"""
parse_supplier_prices.py — Convert the weekly supplier price sheet to a
standardised CSV for use in the demand forecast model.

USAGE
-----
Run once each Wednesday after receiving the supplier sheet:

    python 01_data/operational/parse_supplier_prices.py  --file "Supplier Prices 07Apr2026.xlsx"

Output:
    01_data/operational/supplier_prices_YYYYMMDD.csv   (dated with next week's Monday)

The app and predict.py will automatically detect this file.

SUPPLIER SHEET ASSUMPTIONS
---------------------------
The script expects an Excel file where each row is an item with at least:
  - An item name column  (default: "Description" or "Name")
  - A cost price column  (default: "Cost", "Cost Ex GST", or "Unit Cost")

If your supplier uses different column names, set COST_COL and NAME_COL below.
The script prints unmatched items so you can adjust mappings over time.
"""

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# ── Configuration ──────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent.parent.parent   # foodland_wudinna/
SENSITIVITY    = ROOT / "01_data/reference/item_price_sensitivity.csv"
OUTPUT_DIR     = ROOT / "01_data/operational"

# Target gross margin used to convert cost → expected sell price.
# Adjust per item in ITEM_MARGINS below if some products run a different margin.
DEFAULT_MARGIN = 0.40

# Per-item margin overrides  {normalised_name: margin}
# Add entries here as you learn which items run tighter or wider margins.
ITEM_MARGINS: dict[str, float] = {
    # Example — remove or adjust as needed:
    # "TOMATOES TRUSS LOOSE PER KG": 0.25,
}

# Candidate column names to search for in the supplier sheet
CANDIDATE_NAME_COLS = ["description", "name", "item", "product", "item description"]
CANDIDATE_COST_COLS = ["cost", "cost ex gst", "unit cost", "cost price", "buy price", "nett"]


# ── Helpers ────────────────────────────────────────────────────────────────────
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def next_monday(ref: date = None) -> date:
    """Return the Monday of next week (delivery week)."""
    ref = ref or date.today()
    days_ahead = (7 - ref.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return ref + timedelta(days=days_ahead)


def find_col(columns: list[str], candidates: list[str]) -> str | None:
    lower = [c.lower().strip() for c in columns]
    for candidate in candidates:
        if candidate in lower:
            return columns[lower.index(candidate)]
    return None


# ── Main ───────────────────────────────────────────────────────────────────────
def parse_supplier_sheet(filepath: Path, week_start: date = None) -> pd.DataFrame:
    """
    Read the supplier price sheet and return a standardised DataFrame:
        Name | cost_price | sell_price | margin | week_start

    sell_price is the expected retail price ex GST, computed as:
        sell_price = cost_price / (1 - margin)

    This is what goes into the model as the basis for price_ratio.
    """
    print(f"Reading: {filepath.name}")

    if filepath.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(filepath, header=0)
    else:
        raw = pd.read_csv(filepath)

    raw.columns = raw.columns.str.strip()

    name_col = find_col(raw.columns.tolist(), CANDIDATE_NAME_COLS)
    cost_col = find_col(raw.columns.tolist(), CANDIDATE_COST_COLS)

    if name_col is None or cost_col is None:
        print("\n⚠️  Could not auto-detect columns.")
        print(f"   Available columns: {raw.columns.tolist()}")
        print(f"   Set NAME_COL / COST_COL at the top of this script.")
        sys.exit(1)

    print(f"  Name column: '{name_col}'  |  Cost column: '{cost_col}'")

    df = raw[[name_col, cost_col]].copy()
    df.columns = ["Name_raw", "cost_price"]
    df["Name"]       = df["Name_raw"].apply(norm)
    df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce")
    df = df.dropna(subset=["cost_price"])
    df = df[df["cost_price"] > 0]

    # Apply margin
    df["margin"] = df["Name"].map(ITEM_MARGINS).fillna(DEFAULT_MARGIN)
    df["sell_price"] = (df["cost_price"] / (1 - df["margin"])).round(4)

    # Tag week
    df["week_start"] = (week_start or next_monday()).isoformat()

    result = df[["Name", "cost_price", "sell_price", "margin", "week_start"]].copy()

    # ── Match against known items ──────────────────────────────────────────────
    if SENSITIVITY.exists():
        known = pd.read_csv(SENSITIVITY)["Name"].apply(norm).tolist()
        matched   = result[result["Name"].isin(known)]
        unmatched = result[~result["Name"].isin(known)]
        print(f"\n  Matched to known items: {len(matched)}/{len(result)}")
        if len(unmatched) > 0:
            print(f"  Unmatched items (not in sales history — new or renamed?):")
            for n in unmatched["Name"].tolist():
                print(f"    • {n}")
    else:
        print(f"  (item_price_sensitivity.csv not found — skipping match check)")

    return result


def main():
    parser = argparse.ArgumentParser(description="Parse weekly supplier price sheet.")
    parser.add_argument("--file", required=True, help="Path to the supplier Excel/CSV file.")
    parser.add_argument("--week", default=None,
                        help="Week start date YYYY-MM-DD (default: next Monday).")
    args = parser.parse_args()

    filepath   = Path(args.file)
    week_start = date.fromisoformat(args.week) if args.week else next_monday()

    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    result = parse_supplier_sheet(filepath, week_start)

    out_name = f"supplier_prices_{week_start.strftime('%Y%m%d')}.csv"
    out_path = OUTPUT_DIR / out_name
    result.to_csv(out_path, index=False)

    print(f"\n✅  Saved {len(result)} items → {out_path.relative_to(ROOT)}")
    print(f"   Week start: {week_start}")
    print(f"   The app will use this automatically on next run.")


if __name__ == "__main__":
    main()
