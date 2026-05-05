"""
check_db.py — Foodland Wudinna
Quick database health check. Run this any time you want to verify the DB is
up to date after an import, or to see what data is currently loaded.

Usage:
    python check_db.py
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import db

SEP = "─" * 52

def fmt(n):
    return f"{n:,}"

def check():
    print(f"\n  Foodland Wudinna — Database Health Check")
    print(f"  {date.today().strftime('%A %d %b %Y')}")
    print(f"  {SEP}\n")

    # ── Locate and open DB ──────────────────────────────────────────────────
    db_path = Path(db.DB)
    size_kb = db_path.stat().st_size / 1024 if db_path.exists() else 0

    if size_kb < 1:
        print("  ✗  foodland_data.db is empty or missing.")
        print("     Run:  python migrate_v2.py   to rebuild it.")
        print()
        return

    print(f"  DB file:  {db_path.name}  ({size_kb:,.0f} KB)\n")

    conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    cur  = conn.cursor()

    # ── Sales (fact_sales) ──────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*), MIN(date_id), MAX(date_id) FROM fact_sales")
    n, mn, mx = cur.fetchone()
    print(f"  {'fact_sales':<22}  {fmt(n):>8} rows   {mn}  →  {mx}")

    cur.execute(
        "SELECT strftime('%Y', date_id) yr, COUNT(*) n "
        "FROM fact_sales GROUP BY yr ORDER BY yr"
    )
    for yr, cnt in cur.fetchall():
        print(f"    {yr}:  {fmt(cnt)} rows")

    # ── Other tables ────────────────────────────────────────────────────────
    print()
    for table, date_col in [
        ("dim_product",         None),
        ("ref_item_price",      None),
        ("fact_invoice",        "date_id"),
        ("fact_stock",          "date_id"),
        ("ref_invoice_mapping", None),
    ]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            if date_col:
                cur.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}")
                mn, mx = cur.fetchone()
                print(f"  {table:<22}  {fmt(n):>8} rows   {mn}  →  {mx}")
            else:
                print(f"  {table:<22}  {fmt(n):>8} rows")
        except Exception:
            print(f"  {table:<22}  (not found)")

    # ── Recent trading days ─────────────────────────────────────────────────
    print(f"\n  {SEP}")
    print("  Most recent trading days:\n")
    cur.execute(
        "SELECT date_id, COUNT(*) n FROM fact_sales "
        "GROUP BY date_id ORDER BY date_id DESC LIMIT 7"
    )
    rows = cur.fetchall()
    for dt, cnt in rows:
        print(f"    {dt}   {cnt:>3} items")

    if rows:
        latest = rows[0][0]
        today_str = date.today().isoformat()
        gap = (date.fromisoformat(today_str) - date.fromisoformat(latest)).days
        print()
        if gap == 0:
            print("  ✓  Data is current (today).")
        elif gap == 1:
            print("  ✓  Data is current (yesterday).")
        elif gap <= 3:
            print(f"  ⚠  Last data is {gap} days ago — consider importing latest POS export.")
        else:
            print(f"  ✗  Last data is {gap} days ago — import required.")

    print(f"\n  {SEP}\n")
    conn.close()


if __name__ == "__main__":
    check()
