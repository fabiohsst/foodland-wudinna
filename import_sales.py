"""
import_sales.py — Import a new POS sales CSV export into foodland_data.db.

Usage
-----
    python import_sales.py <csv_file>
    python import_sales.py 01_data/raw/sales_april_19.04.26.csv

What it does
------------
1. Reads and normalises the CSV (handles old "Date" and new "Sales Date" column names,
   handles the extra "Online Sales Ex / Inc" columns present in newer GAP exports).
2. Inserts into the `sales` table via db.import_sales_rows() — idempotent,
   UNIQUE on (date, name), so re-running the same file is always safe.
3. Moves the processed file to 01_data/raw/archive/ with a datestamp prefix.
4. Prints a concise summary: rows inserted, rows skipped, archive path.

No data is deleted from the database — only new rows are added.
"""

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent
ARCHIVE = ROOT / "01_data/raw/archive"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def _f(row, col):
    """Safe float: returns None for missing or non-numeric values."""
    val = row.get(col) if hasattr(row, "get") else None
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def build_rows(df: pd.DataFrame, source_file: str) -> list[tuple]:
    imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for _, r in df.iterrows():
        rows.append((
            r["Date"],
            r.get("Department Name"),
            r["Name"],
            r.get("Sub Department Name"),
            _f(r, "Sales Inc GST"),
            _f(r, "Cost Ex GST"),
            _f(r, "Cost Inc GST"),
            _f(r, "Lines"),
            _f(r, "Quantity"),
            _f(r, "Sales Ex GST"),
            imported_at,
            source_file,
        ))
    return rows


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()

    # Handle new GAP export column name ("Sales Date" instead of "Date")
    if "Sales Date" in df.columns:
        df = df.rename(columns={"Sales Date": "Date"})

    if "Date" not in df.columns:
        raise ValueError(
            f"Expected a 'Date' or 'Sales Date' column — found: {list(df.columns)}"
        )

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["Name"] = df["Name"].apply(norm)
    df = df.dropna(subset=["Date", "Name"])
    return df


def archive_file(path: Path) -> Path:
    """Move file to archive/ with a YYYYMMDD_ prefix."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    dest  = ARCHIVE / f"{stamp}_{path.name}"
    # If a file with the same name already exists in archive, add a counter
    if dest.exists():
        stem, suffix = path.stem, path.suffix
        for i in range(1, 100):
            dest = ARCHIVE / f"{stamp}_{stem}_{i}{suffix}"
            if not dest.exists():
                break
    shutil.move(str(path), dest)
    return dest


def main():
    parser = argparse.ArgumentParser(
        description="Import a GAP POS sales CSV into foodland_data.db"
    )
    parser.add_argument("csv_file", help="Path to the sales CSV to import")
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip moving the file to archive after import",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Importing: {csv_path.name}")
    print()

    # Load and normalise
    try:
        df = load_csv(csv_path)
    except Exception as e:
        print(f"ERROR reading CSV: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Rows in file:   {len(df):,}")

    # Build insert tuples
    rows = build_rows(df, csv_path.name)

    # Insert into DB
    from db import import_sales_rows
    inserted, skipped = import_sales_rows(rows)

    print(f"  Inserted:       {inserted:,}")
    print(f"  Skipped (dup):  {skipped:,}")
    print()

    # Archive
    if not args.no_archive:
        try:
            dest = archive_file(csv_path)
            print(f"  Archived to:    {dest.relative_to(ROOT)}")
        except Exception as e:
            print(f"  WARNING: Could not archive file — {e}", file=sys.stderr)
    else:
        print("  Archive skipped (--no-archive flag).")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
