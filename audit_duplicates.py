"""
audit_duplicates.py — Find duplicate rows in fact_sales, fact_dump, fact_markdown.

Rules (per POS export behaviour):
  • The same product cannot appear twice on the same date in any POS-sourced table.
  • Duplicate key = (date_id, product_id) when product_id is not NULL,
                    (date_id, apn, description) when product_id is NULL.
  • fact_waste_log is excluded — it is entered manually and can repeat.

Run:
    python audit_duplicates.py

Output:
    Prints a full duplicate report to the terminal.
    Does NOT delete anything — a separate --fix flag is required for that.

Usage with --fix:
    python audit_duplicates.py --fix
    → Keeps one row per key (the most recently imported one) and deletes the rest.
    → Prints how many rows were removed from each table.
"""

import argparse
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT   = Path(__file__).parent
DB_SRC = ROOT / "foodland_data.db"


def _open(path: Path) -> sqlite3.Connection:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    shutil.copy2(str(path), tmp.name)
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    return conn, tmp.name


def _write_back(tmp_path: str):
    """Copy the modified DB back to the mount."""
    shutil.copy2(tmp_path, str(DB_SRC))


def _section(title: str):
    print()
    print("━" * 60)
    print(f"  {title}")
    print("━" * 60)


# ── Duplicate finders ─────────────────────────────────────────────────────────

def find_sales_dupes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """fact_sales — UNIQUE(date_id, product_id) constraint exists but let's verify."""
    return conn.execute("""
        SELECT
            fs.date_id,
            dp.name        AS product_name,
            fs.product_id,
            COUNT(*)       AS n,
            GROUP_CONCAT(fs.source_file, ' | ') AS source_files,
            GROUP_CONCAT(fs.date_imported, ' | ') AS import_dates
        FROM fact_sales fs
        LEFT JOIN dim_product dp ON fs.product_id = dp.product_id
        GROUP BY fs.date_id, fs.product_id
        HAVING n > 1
        ORDER BY fs.date_id, product_name
    """).fetchall()


def find_dump_dupes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """fact_dump — no UNIQUE constraint. Natural key = (date_id, apn, description)."""
    return conn.execute("""
        SELECT
            fd.date_id,
            fd.apn,
            fd.description,
            fd.department,
            COUNT(*)       AS n,
            SUM(fd.qty)    AS total_qty,
            GROUP_CONCAT(fd.source_file, ' | ') AS source_files
        FROM fact_dump fd
        GROUP BY fd.date_id, fd.apn, fd.description
        HAVING n > 1
        ORDER BY fd.date_id, fd.description
    """).fetchall()


def find_markdown_dupes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """fact_markdown — no UNIQUE constraint. Natural key = (date_id, apn, description)."""
    return conn.execute("""
        SELECT
            fm.date_id,
            fm.apn,
            fm.description,
            fm.department,
            COUNT(*)          AS n,
            SUM(fm.total_sell) AS total_sell_sum,
            GROUP_CONCAT(fm.source_file, ' | ') AS source_files
        FROM fact_markdown fm
        GROUP BY fm.date_id, fm.apn, fm.description
        HAVING n > 1
        ORDER BY fm.date_id, fm.description
    """).fetchall()


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(sales, dump, markdown):
    print("\n" + "=" * 60)
    print("  DUPLICATE AUDIT REPORT")
    print("  Foodland Wudinna — foodland_data.db")
    print("=" * 60)

    _section(f"fact_sales  ({len(sales)} duplicate groups found)")
    if not sales:
        print("  ✅  No duplicates found.")
    else:
        print(f"  {'Date':<12} {'Product':<40} {'Count':>5}  Source files")
        print(f"  {'-'*12} {'-'*40} {'-'*5}  {'-'*30}")
        for r in sales:
            print(f"  {r['date_id']:<12} {str(r['product_name'] or '?'):<40} {r['n']:>5}  {r['source_files']}")

    _section(f"fact_dump  ({len(dump)} duplicate groups found)")
    if not dump:
        print("  ✅  No duplicates found.")
    else:
        print(f"  {'Date':<12} {'Description':<40} {'Count':>5}  Source files")
        print(f"  {'-'*12} {'-'*40} {'-'*5}  {'-'*30}")
        for r in dump:
            print(f"  {r['date_id']:<12} {str(r['description'] or '?'):<40} {r['n']:>5}  {r['source_files']}")

    _section(f"fact_markdown  ({len(markdown)} duplicate groups found)")
    if not markdown:
        print("  ✅  No duplicates found.")
    else:
        print(f"  {'Date':<12} {'Description':<40} {'Count':>5}  Source files")
        print(f"  {'-'*12} {'-'*40} {'-'*5}  {'-'*30}")
        for r in markdown:
            print(f"  {r['date_id']:<12} {str(r['description'] or '?'):<40} {r['n']:>5}  {r['source_files']}")

    total = len(sales) + len(dump) + len(markdown)
    print()
    print("=" * 60)
    if total == 0:
        print("  ✅  Database is clean — no duplicates found.")
    else:
        print(f"  ⚠  {total} duplicate group(s) found across all tables.")
        print("  Run with --fix to remove them (keeps the latest import).")
    print("=" * 60)
    print()


# ── Fix (delete duplicates) ───────────────────────────────────────────────────

def fix_sales(conn: sqlite3.Connection) -> int:
    """Keep the row with the highest sale_id (latest insert) per (date_id, product_id)."""
    removed = conn.execute("""
        DELETE FROM fact_sales
        WHERE sale_id NOT IN (
            SELECT MAX(sale_id)
            FROM fact_sales
            GROUP BY date_id, product_id
        )
    """).rowcount
    return removed


def fix_dump(conn: sqlite3.Connection) -> int:
    """Keep the row with the highest dump_id per (date_id, apn, description)."""
    removed = conn.execute("""
        DELETE FROM fact_dump
        WHERE dump_id NOT IN (
            SELECT MAX(dump_id)
            FROM fact_dump
            GROUP BY date_id, apn, description
        )
    """).rowcount
    return removed


def fix_markdown(conn: sqlite3.Connection) -> int:
    """Keep the row with the highest markdown_id per (date_id, apn, description)."""
    removed = conn.execute("""
        DELETE FROM fact_markdown
        WHERE markdown_id NOT IN (
            SELECT MAX(markdown_id)
            FROM fact_markdown
            GROUP BY date_id, apn, description
        )
    """).rowcount
    return removed


def add_missing_constraints(conn: sqlite3.Connection):
    """
    SQLite cannot ALTER TABLE ADD CONSTRAINT, so we recreate fact_dump and
    fact_markdown with the UNIQUE constraint via a rename → create → copy → drop.
    """
    conn.executescript("""
        PRAGMA foreign_keys=OFF;

        -- fact_dump
        ALTER TABLE fact_dump RENAME TO _fact_dump_old;
        CREATE TABLE fact_dump (
            dump_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            date_id       TEXT    NOT NULL REFERENCES dim_date(date_id),
            product_id    INTEGER REFERENCES dim_product(product_id),
            department    TEXT,
            apn           TEXT,
            description   TEXT,
            qty           REAL,
            unit_cost_ex  REAL,
            unit_sell_ex  REAL,
            reason        TEXT,
            total_cost_ex REAL,
            total_sell_ex REAL,
            source_file   TEXT,
            UNIQUE(date_id, apn, description)
        );
        INSERT OR IGNORE INTO fact_dump
            SELECT * FROM _fact_dump_old;
        DROP TABLE _fact_dump_old;

        -- fact_markdown
        ALTER TABLE fact_markdown RENAME TO _fact_markdown_old;
        CREATE TABLE fact_markdown (
            markdown_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            date_id         TEXT    NOT NULL REFERENCES dim_date(date_id),
            product_id      INTEGER REFERENCES dim_product(product_id),
            department      TEXT,
            apn             TEXT,
            description     TEXT,
            sub_dept        TEXT,
            lines           REAL,
            potential_sell  REAL,
            total_sell      REAL,
            total_cost      REAL,
            discount_given  REAL,
            realised_profit REAL,
            source_file     TEXT,
            UNIQUE(date_id, apn, description)
        );
        INSERT OR IGNORE INTO fact_markdown
            SELECT * FROM _fact_markdown_old;
        DROP TABLE _fact_markdown_old;

        -- Recreate indexes
        CREATE INDEX IF NOT EXISTS idx_fact_dump_date     ON fact_dump(date_id);
        CREATE INDEX IF NOT EXISTS idx_fact_dump_product  ON fact_dump(product_id);
        CREATE INDEX IF NOT EXISTS idx_fact_markdown_date    ON fact_markdown(date_id);
        CREATE INDEX IF NOT EXISTS idx_fact_markdown_product ON fact_markdown(product_id);

        PRAGMA foreign_keys=ON;
    """)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Audit (and optionally fix) duplicate rows in foodland_data.db")
    parser.add_argument("--fix", action="store_true",
                        help="Remove duplicates and add missing UNIQUE constraints. "
                             "Keeps the most recently inserted row per key.")
    args = parser.parse_args()

    if not DB_SRC.exists():
        print(f"ERROR: database not found at {DB_SRC}")
        return

    print(f"\nOpening: {DB_SRC}")
    conn, tmp_path = _open(DB_SRC)

    try:
        # Always run the audit first
        sales    = find_sales_dupes(conn)
        dump     = find_dump_dupes(conn)
        markdown = find_markdown_dupes(conn)

        print_report(sales, dump, markdown)

        if args.fix:
            total = len(sales) + len(dump) + len(markdown)
            if total == 0:
                print("Nothing to fix.")
                return

            print("Applying fixes …")
            conn.row_factory = None  # switch off for writes
            conn2 = sqlite3.connect(tmp_path)
            conn2.execute("PRAGMA foreign_keys=OFF")

            r_sales    = fix_sales(conn2)
            r_dump     = fix_dump(conn2)
            r_markdown = fix_markdown(conn2)

            print(f"  Removed from fact_sales:    {r_sales}")
            print(f"  Removed from fact_dump:     {r_dump}")
            print(f"  Removed from fact_markdown: {r_markdown}")

            print("\nAdding UNIQUE constraints to fact_dump and fact_markdown …")
            add_missing_constraints(conn2)

            conn2.commit()
            conn2.close()

            print("Copying fixed database back …")
            _write_back(tmp_path)
            print("✅  Done. Database updated.")
        else:
            print("(Read-only audit — no changes made.)\n")

    finally:
        conn.close()
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
