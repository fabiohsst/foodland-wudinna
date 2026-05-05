"""
migrate_to_sqlite.py — One-time migration from CSV files to SQLite.

Creates foodland_data.db and loads:
  - sales        ← sales_fruit_2025.csv + sales_fruit_2026.csv
  - price_history ← 01_data/reference/price_history.csv
  - stock_on_hand ← 01_data/operational/stock_on_hand_v2.csv
  - item_price   ← 01_data/reference/item_price.csv
  - item_reference ← 01_data/reference/item_reference.csv

Safe to re-run: uses INSERT OR IGNORE / INSERT OR REPLACE throughout.
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent
DB      = ROOT / "foodland_data.db"
DB_TEMP = Path("/tmp/foodland_data.db")   # build here; copy to mount after

SALES_FILES = [
    ROOT / "01_data/raw/sales_fruit_2025.csv",
    ROOT / "01_data/raw/sales_fruit_2026.csv",
]
PRICE_HISTORY_CSV  = ROOT / "01_data/reference/price_history.csv"
STOCK_ON_HAND_CSV  = ROOT / "01_data/operational/stock_on_hand_v2.csv"
ITEM_PRICE_CSV     = ROOT / "01_data/reference/item_price.csv"
ITEM_REFERENCE_CSV = ROOT / "01_data/reference/item_reference.csv"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def create_schema(conn: sqlite3.Connection) -> None:
    # Use individual execute() calls — executescript() issues an implicit
    # COMMIT that can trigger journaling before PRAGMA journal_mode=MEMORY
    # takes effect (causes disk I/O error on virtiofs/Windows mounts).
    stmts = [
        """CREATE TABLE IF NOT EXISTS sales (
            date             TEXT NOT NULL,
            store_name       TEXT,
            department       TEXT,
            apn              TEXT,
            name             TEXT NOT NULL,
            sub_dept         TEXT,
            sales_inc_gst    REAL,
            cost_ex_gst      REAL,
            cost_inc_gst     REAL,
            gp_pct           REAL,
            gp_dollars       REAL,
            lines            REAL,
            quantity         REAL,
            sales_ex_gst     REAL,
            store_sales_ex   REAL,
            store_sales_inc  REAL,
            online_sales_ex  REAL,
            online_sales_inc REAL,
            date_imported    TEXT,
            source_file      TEXT,
            UNIQUE(date, name)
        )""",
        """CREATE TABLE IF NOT EXISTS price_history (
            date          TEXT NOT NULL,
            invoice_no    TEXT NOT NULL,
            pos_name      TEXT NOT NULL,
            cost_per_unit REAL,
            sell_price    REAL,
            gp_pct        REAL,
            source        TEXT,
            PRIMARY KEY (invoice_no, pos_name)
        )""",
        """CREATE TABLE IF NOT EXISTS stock_on_hand (
            name          TEXT NOT NULL,
            stock         REAL,
            source        TEXT,
            date_recorded TEXT NOT NULL,
            PRIMARY KEY (name, date_recorded)
        )""",
        """CREATE TABLE IF NOT EXISTS item_price (
            name              TEXT PRIMARY KEY,
            sell_price_manual REAL,
            sell_price        REAL,
            cost_price        REAL
        )""",
        """CREATE TABLE IF NOT EXISTS item_reference (
            plu  TEXT,
            name TEXT PRIMARY KEY
        )""",
    ]
    for stmt in stmts:
        conn.execute(stmt)
    conn.commit()
    print("Schema created.")


# ── Sales ─────────────────────────────────────────────────────────────────────
def migrate_sales(conn: sqlite3.Connection) -> None:
    total_inserted = total_skipped = 0
    imported_at    = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    for path in SALES_FILES:
        if not path.exists():
            print(f"  [SKIP] {path.name} not found")
            continue

        df = pd.read_csv(path, low_memory=False)
        df.columns = df.columns.str.strip()

        # Normalise date column name (new exports use 'Sales Date')
        if "Sales Date" in df.columns:
            df = df.rename(columns={"Sales Date": "Date"})

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["Name"] = df["Name"].apply(norm)
        df = df.dropna(subset=["Date", "Name"])

        rows = []
        for _, r in df.iterrows():
            rows.append((
                r["Date"],
                r.get("Store Name"),
                r.get("Department Name"),
                str(r.get("APN", "")) if pd.notna(r.get("APN")) else None,
                r["Name"],
                r.get("Sub Department Name"),
                _f(r, "Sales Inc GST"),
                _f(r, "Cost Ex GST"),
                _f(r, "Cost Inc GST"),
                _f(r, "GP %"),
                _f(r, "GP $"),
                _f(r, "Lines"),
                _f(r, "Quantity"),
                _f(r, "Sales Ex GST"),
                _f(r, "Store Sales Ex"),
                _f(r, "Store Sales Inc"),
                _f(r, "Online Sales Ex"),
                _f(r, "Online Sales Inc"),
                imported_at,
                path.name,
            ))

        cur = conn.executemany("""
            INSERT OR IGNORE INTO sales
            (date, store_name, department, apn, name, sub_dept,
             sales_inc_gst, cost_ex_gst, cost_inc_gst, gp_pct, gp_dollars, lines,
             quantity, sales_ex_gst, store_sales_ex, store_sales_inc,
             online_sales_ex, online_sales_inc, date_imported, source_file)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()

        inserted = cur.rowcount if cur.rowcount >= 0 else len(rows)
        skipped  = len(rows) - inserted
        total_inserted += inserted
        total_skipped  += skipped
        print(f"  {path.name}: {inserted:,} inserted, {skipped:,} skipped (duplicate)")

    print(f"  Sales total: {total_inserted:,} rows inserted, {total_skipped:,} skipped")


# ── Price history ─────────────────────────────────────────────────────────────
def migrate_price_history(conn: sqlite3.Connection) -> None:
    if not PRICE_HISTORY_CSV.exists():
        print("  [SKIP] price_history.csv not found")
        return

    df = pd.read_csv(PRICE_HISTORY_CSV)
    df = df.dropna(subset=["invoice_no", "pos_name"])

    rows = [
        (str(r["date"]), str(r["invoice_no"]), str(r["pos_name"]),
         _f(r, "cost_per_unit"), _f(r, "sell_price"), _f(r, "gp_pct"),
         str(r.get("source", "")))
        for _, r in df.iterrows()
    ]
    cur = conn.executemany("""
        INSERT OR IGNORE INTO price_history
        (date, invoice_no, pos_name, cost_per_unit, sell_price, gp_pct, source)
        VALUES (?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    print(f"  price_history: {len(rows):,} rows processed, {cur.rowcount} inserted")


# ── Stock on hand ─────────────────────────────────────────────────────────────
def migrate_stock_on_hand(conn: sqlite3.Connection) -> None:
    if not STOCK_ON_HAND_CSV.exists():
        print("  [SKIP] stock_on_hand_v2.csv not found")
        return

    df = pd.read_csv(STOCK_ON_HAND_CSV)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Name"])

    # Use the file's modification date as the snapshot date
    mtime = pd.Timestamp(STOCK_ON_HAND_CSV.stat().st_mtime, unit="s").strftime("%Y-%m-%d")

    rows = [
        (norm(r["Name"]), _f(r, "Stock"), str(r.get("Source", "")), mtime)
        for _, r in df.iterrows()
    ]
    cur = conn.executemany("""
        INSERT OR IGNORE INTO stock_on_hand (name, stock, source, date_recorded)
        VALUES (?,?,?,?)
    """, rows)
    conn.commit()
    print(f"  stock_on_hand: {cur.rowcount} rows inserted (snapshot date: {mtime})")


# ── Item price ────────────────────────────────────────────────────────────────
def migrate_item_price(conn: sqlite3.Connection) -> None:
    if not ITEM_PRICE_CSV.exists():
        print("  [SKIP] item_price.csv not found")
        return

    df = pd.read_csv(ITEM_PRICE_CSV)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Name"])

    rows = [
        (norm(r["Name"]),
         _f(r, "Sell Price (manual)"),
         _f(r, "Sell Price"),
         _f(r, "Cost Price"))
        for _, r in df.iterrows()
    ]
    cur = conn.executemany("""
        INSERT OR REPLACE INTO item_price (name, sell_price_manual, sell_price, cost_price)
        VALUES (?,?,?,?)
    """, rows)
    conn.commit()
    print(f"  item_price: {cur.rowcount} rows inserted")


# ── Item reference ────────────────────────────────────────────────────────────
def migrate_item_reference(conn: sqlite3.Connection) -> None:
    if not ITEM_REFERENCE_CSV.exists():
        print("  [SKIP] item_reference.csv not found")
        return

    df = pd.read_csv(ITEM_REFERENCE_CSV)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Name"])

    rows = [
        (str(r.get("PLU", "")) if pd.notna(r.get("PLU")) else None,
         norm(r["Name"]))
        for _, r in df.iterrows()
    ]
    cur = conn.executemany("""
        INSERT OR REPLACE INTO item_reference (plu, name) VALUES (?,?)
    """, rows)
    conn.commit()
    print(f"  item_reference: {cur.rowcount} rows inserted")


# ── Utility ───────────────────────────────────────────────────────────────────
def _f(row, col):
    """Safe float extraction — returns None for missing/non-numeric."""
    val = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Target:    {DB}")
    print(f"Building:  {DB_TEMP}")
    print()

    # Build in /tmp to avoid virtiofs journal-file limitations, then copy.
    DB_TEMP.unlink(missing_ok=True)

    with sqlite3.connect(DB_TEMP) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")  # default, works in /tmp

        print("Creating schema...")
        create_schema(conn)
        print()

        print("Migrating sales...")
        migrate_sales(conn)
        print()

        print("Migrating price history...")
        migrate_price_history(conn)
        print()

        print("Migrating stock on hand...")
        migrate_stock_on_hand(conn)
        print()

        print("Migrating item prices...")
        migrate_item_price(conn)
        print()

        print("Migrating item reference...")
        migrate_item_reference(conn)
        print()

        # Summary
        print("── Verification ──────────────────────")
        for table in ("sales", "price_history", "stock_on_hand", "item_price", "item_reference"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<20} {n:>6,} rows")

    # Copy the completed DB from /tmp to the workspace folder.
    # virtiofs on Windows can't create SQLite journal files, so we
    # build in /tmp and do a single binary copy to the mount.
    import shutil
    print(f"Copying {DB_TEMP} → {DB} ...")
    shutil.copy2(DB_TEMP, DB)
    DB_TEMP.unlink(missing_ok=True)
    print(f"Done. DB size: {DB.stat().st_size / 1024:.1f} KB")
    print()
    print("Migration complete.")
