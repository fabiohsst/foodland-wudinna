"""
migrate_v3.py — Schema migration from v2 to v3.

Run once:
    python migrate_v3.py

Changes applied
---------------
dim_product:    DROP category; RENAME plu → apn; ADD department
                Backfill apn from fact_sales; backfill department from fact_sales;
                backfill sub_dept for the ~120 NULL items from all available CSVs.
fact_sales:     ADD sub_dept; clean APN float strings; remove 7 non-trading rows;
                backfill sub_dept from dim_product.
fact_invoice:   ADD invoice_product_name, product_name; backfill product_name.
fact_dump:      DROP item_no; clean APN float strings.
fact_waste_log: ADD costed_cost + cost_source; DROP log_cost + actual_cost.
ref_item_price: DROP sell_price_manual; ADD price_source TEXT DEFAULT 'manual'.
Views:          Rebuild v_waste_summary with new fact_waste_log columns.

Data loaded (after schema migration)
-------------------------------------
  01_data/raw/dairy_sales_2025_1.csv
  01_data/raw/dairy_sales_2025_2.csv
  01_data/raw/sales_meat_2025.csv
  01_data/raw/MD_dairy_2025.csv
  01_data/raw/MD_meat_2025.csv

Supplier audit
--------------
No supplier field exists in any POS export CSV, markdown CSV, dump report, or
waste log. dim_supplier retains its single entry (Freshlink) as the only supplier
whose invoices are stored. No change needed.

Safe to re-run — checks version flag before applying.
"""

import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DB   = ROOT / "foodland_data.db"

RAW           = ROOT / "01_data/raw"
DAIRY_2025_1  = RAW / "dairy_sales_2025_1.csv"
DAIRY_2025_2  = RAW / "dairy_sales_2025_2.csv"
MEAT_2025     = RAW / "sales_meat_2025.csv"
MD_DAIRY_2025 = RAW / "MD_dairy_2025.csv"
MD_MEAT_2025  = RAW / "MD_meat_2025.csv"

VERSION_FLAG  = "v3"          # stored in a meta table to detect re-runs


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def clean_apn(val) -> str | None:
    """Normalise APN/barcode: strip float suffix, return plain integer string."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if s in ("", "0", "None", "nan"):
        return None
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        return s if s else None


def _write_conn():
    """Context manager: copy DB to /tmp, yield writable connection, copy back."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        tmp = Path(tempfile.mktemp(suffix=".db", prefix="foodland_v3_"))
        try:
            shutil.copy2(DB, tmp)
            conn = sqlite3.connect(tmp)
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA foreign_keys=OFF")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            shutil.copy2(tmp, DB)
        finally:
            tmp.unlink(missing_ok=True)

    return _ctx()


# ─────────────────────────────────────────────────────────────────────────────
# Step 0 — Version check
# ─────────────────────────────────────────────────────────────────────────────

def check_version() -> bool:
    """Return True if migration has already been applied."""
    conn = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "_meta" not in tables:
        conn.close()
        return False
    flag = conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    conn.close()
    return flag is not None and flag[0] == VERSION_FLAG


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Build sub_dept + department lookup from all available CSVs
# ─────────────────────────────────────────────────────────────────────────────

def build_csv_lookup() -> dict[str, tuple[str, str]]:
    """
    Scan all CSVs that include Sub Department Name.
    Returns {NORMALISED_NAME: (sub_dept, department)}.
    """
    files = [
        (RAW / "dairy_sales_2025_1.csv",     "DAIRY"),
        (RAW / "dairy_sales_2025_2.csv",     "DAIRY"),
        (RAW / "sales_meat_2025.csv",        "MEAT"),
        (RAW / "sales_fruit_2026.csv",       "FRUIT & VEG"),
        (RAW / "FV_sales_28.04.26.csv",      "FRUIT & VEG"),
        (RAW / "MD_dairy_2025.csv",          "DAIRY"),
        (RAW / "MD_meat_2025.csv",           "MEAT"),
        (RAW / "MD_YTD_28.04.26.csv",        "DAIRY"),   # multi-dept, dept from col
    ]
    lookup: dict[str, tuple[str, str]] = {}
    for path, fallback_dept in files:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, usecols=lambda c: c.strip() in
                             {"Name", "Sub Department Name", "Department Name"},
                             low_memory=False, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            if "Name" not in df.columns or "Sub Department Name" not in df.columns:
                continue
            dept_col = "Department Name" if "Department Name" in df.columns else None
            for _, row in df.dropna(subset=["Name", "Sub Department Name"]).iterrows():
                key = norm(str(row["Name"]))
                sd  = str(row["Sub Department Name"]).strip()
                dept = str(row[dept_col]).strip() if dept_col else fallback_dept
                if key and sd and sd.lower() not in ("nan", "none", ""):
                    lookup[key] = (sd, dept)
        except Exception as e:
            print(f"  [WARN] Could not read {path.name}: {e}")
    print(f"  CSV lookup built: {len(lookup)} unique product names with sub_dept")
    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Schema changes (ALTER TABLE operations)
# ─────────────────────────────────────────────────────────────────────────────

def apply_schema(conn: sqlite3.Connection) -> None:
    print("  Applying schema changes...")

    # ── _meta version table ─────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # ── dim_product ─────────────────────────────────────────────────────────
    # Rename plu → apn
    try:
        conn.execute("ALTER TABLE dim_product RENAME COLUMN plu TO apn")
        print("    dim_product: RENAME plu → apn")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            print("    dim_product: apn column already exists, skipping rename")
        else:
            raise

    # Drop category (all NULL, never used)
    try:
        conn.execute("ALTER TABLE dim_product DROP COLUMN category")
        print("    dim_product: DROP COLUMN category")
    except sqlite3.OperationalError:
        print("    dim_product: category already dropped")

    # Add department
    try:
        conn.execute("ALTER TABLE dim_product ADD COLUMN department TEXT")
        print("    dim_product: ADD COLUMN department")
    except sqlite3.OperationalError:
        print("    dim_product: department already exists")

    # ── fact_sales ──────────────────────────────────────────────────────────
    try:
        conn.execute("ALTER TABLE fact_sales ADD COLUMN sub_dept TEXT")
        print("    fact_sales: ADD COLUMN sub_dept")
    except sqlite3.OperationalError:
        print("    fact_sales: sub_dept already exists")

    # ── fact_invoice ────────────────────────────────────────────────────────
    try:
        conn.execute("ALTER TABLE fact_invoice ADD COLUMN invoice_product_name TEXT")
        print("    fact_invoice: ADD COLUMN invoice_product_name")
    except sqlite3.OperationalError:
        print("    fact_invoice: invoice_product_name already exists")

    try:
        conn.execute("ALTER TABLE fact_invoice ADD COLUMN product_name TEXT")
        print("    fact_invoice: ADD COLUMN product_name")
    except sqlite3.OperationalError:
        print("    fact_invoice: product_name already exists")

    # ── fact_dump ───────────────────────────────────────────────────────────
    try:
        conn.execute("ALTER TABLE fact_dump DROP COLUMN item_no")
        print("    fact_dump: DROP COLUMN item_no")
    except sqlite3.OperationalError:
        print("    fact_dump: item_no already dropped")

    # ── fact_waste_log ──────────────────────────────────────────────────────
    try:
        conn.execute("ALTER TABLE fact_waste_log ADD COLUMN costed_cost REAL")
        print("    fact_waste_log: ADD COLUMN costed_cost")
    except sqlite3.OperationalError:
        print("    fact_waste_log: costed_cost already exists")

    try:
        conn.execute("ALTER TABLE fact_waste_log ADD COLUMN cost_source TEXT")
        print("    fact_waste_log: ADD COLUMN cost_source")
    except sqlite3.OperationalError:
        print("    fact_waste_log: cost_source already exists")

    # Migrate existing cost data before dropping source columns
    conn.execute("""
        UPDATE fact_waste_log
        SET costed_cost = COALESCE(actual_cost, log_cost),
            cost_source = CASE WHEN actual_cost IS NOT NULL THEN 'confirmed' ELSE 'estimated' END
        WHERE costed_cost IS NULL
    """)
    print(f"    fact_waste_log: migrated {conn.execute('SELECT COUNT(*) FROM fact_waste_log').fetchone()[0]} rows to costed_cost")

    try:
        conn.execute("ALTER TABLE fact_waste_log DROP COLUMN log_cost")
        print("    fact_waste_log: DROP COLUMN log_cost")
    except sqlite3.OperationalError:
        print("    fact_waste_log: log_cost already dropped")

    try:
        conn.execute("ALTER TABLE fact_waste_log DROP COLUMN actual_cost")
        print("    fact_waste_log: DROP COLUMN actual_cost")
    except sqlite3.OperationalError:
        print("    fact_waste_log: actual_cost already dropped")

    # ── ref_item_price ──────────────────────────────────────────────────────
    try:
        conn.execute("ALTER TABLE ref_item_price ADD COLUMN price_source TEXT DEFAULT 'manual'")
        print("    ref_item_price: ADD COLUMN price_source")
    except sqlite3.OperationalError:
        print("    ref_item_price: price_source already exists")

    # Set price_source = 'invoice' for items where sell_price_manual != sell_price
    # (those were set by the invoice import script)
    conn.execute("""
        UPDATE ref_item_price
        SET price_source = 'invoice'
        WHERE sell_price_manual IS NOT NULL AND ABS(sell_price_manual - sell_price) > 0.01
    """)

    try:
        conn.execute("ALTER TABLE ref_item_price DROP COLUMN sell_price_manual")
        print("    ref_item_price: DROP COLUMN sell_price_manual")
    except sqlite3.OperationalError:
        print("    ref_item_price: sell_price_manual already dropped")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Data backfills
# ─────────────────────────────────────────────────────────────────────────────

def backfill_dim_product(conn: sqlite3.Connection,
                         csv_lookup: dict[str, tuple[str, str]]) -> None:
    print("  Backfilling dim_product...")

    # ── apn: clean float strings already in dim_product ────────────────────
    rows = conn.execute("SELECT product_id, apn FROM dim_product WHERE apn IS NOT NULL").fetchall()
    cleaned = [(clean_apn(apn), pid) for pid, apn in rows if clean_apn(apn) != str(apn).strip()]
    if cleaned:
        conn.executemany("UPDATE dim_product SET apn=? WHERE product_id=?", cleaned)
        print(f"    dim_product: cleaned {len(cleaned)} APN float strings")

    # ── apn: fill NULLs from fact_sales ────────────────────────────────────
    conn.execute("""
        UPDATE dim_product
        SET apn = (
            SELECT MAX(s.apn) FROM fact_sales s
            WHERE s.product_id = dim_product.product_id
            AND s.apn IS NOT NULL AND s.apn != '' AND s.apn != '0'
        )
        WHERE apn IS NULL OR apn = '0'
    """)
    # Then clean those too (they were stored as floats)
    rows = conn.execute("SELECT product_id, apn FROM dim_product WHERE apn IS NOT NULL").fetchall()
    cleaned = []
    for pid, apn in rows:
        c = clean_apn(apn)
        if c != apn:
            cleaned.append((c, pid))
    if cleaned:
        conn.executemany("UPDATE dim_product SET apn=? WHERE product_id=?", cleaned)
    filled = conn.execute("SELECT COUNT(*) FROM dim_product WHERE apn IS NOT NULL AND apn != '0'").fetchone()[0]
    still_null = conn.execute("SELECT COUNT(*) FROM dim_product WHERE apn IS NULL OR apn='0'").fetchone()[0]
    print(f"    dim_product.apn: {filled} filled, {still_null} still NULL (genuine open-ring / PLU-less)")

    # ── department: fill from fact_sales (most frequent department per product) ─
    conn.execute("""
        UPDATE dim_product
        SET department = (
            SELECT s.department FROM fact_sales s
            WHERE s.product_id = dim_product.product_id
            GROUP BY s.department ORDER BY COUNT(*) DESC LIMIT 1
        )
        WHERE department IS NULL
    """)
    dept_filled = conn.execute("SELECT COUNT(*) FROM dim_product WHERE department IS NOT NULL").fetchone()[0]
    dept_null   = conn.execute("SELECT COUNT(*) FROM dim_product WHERE department IS NULL").fetchone()[0]
    print(f"    dim_product.department: {dept_filled} filled, {dept_null} still NULL (no sales record)")

    # ── sub_dept: fill NULLs using CSV lookup ──────────────────────────────
    null_items = conn.execute(
        "SELECT product_id, name FROM dim_product WHERE sub_dept IS NULL"
    ).fetchall()
    updates = []
    for pid, name in null_items:
        key = norm(str(name))
        if key in csv_lookup:
            sd, _ = csv_lookup[key]
            updates.append((sd, pid))
    if updates:
        conn.executemany("UPDATE dim_product SET sub_dept=? WHERE product_id=?", updates)
    still_null_sd = conn.execute("SELECT COUNT(*) FROM dim_product WHERE sub_dept IS NULL").fetchone()[0]
    print(f"    dim_product.sub_dept: fixed {len(updates)} NULLs from CSV lookup, {still_null_sd} remain NULL")


def backfill_fact_sales(conn: sqlite3.Connection) -> None:
    print("  Backfilling fact_sales...")

    # ── Clean APN float strings in fact_sales ──────────────────────────────
    rows = conn.execute(
        "SELECT sale_id, apn FROM fact_sales WHERE apn IS NOT NULL AND apn GLOB '*.*'"
    ).fetchall()
    cleaned = []
    for sid, apn in rows:
        c = clean_apn(apn)
        if c != apn:
            cleaned.append((c, sid))
    if cleaned:
        conn.executemany("UPDATE fact_sales SET apn=? WHERE sale_id=?", cleaned)
        print(f"    fact_sales: cleaned {len(cleaned)} APN float strings")

    # ── sub_dept: backfill from dim_product ────────────────────────────────
    conn.execute("""
        UPDATE fact_sales
        SET sub_dept = (
            SELECT dp.sub_dept FROM dim_product dp
            WHERE dp.product_id = fact_sales.product_id
        )
        WHERE sub_dept IS NULL
    """)
    filled = conn.execute("SELECT COUNT(*) FROM fact_sales WHERE sub_dept IS NOT NULL").fetchone()[0]
    null   = conn.execute("SELECT COUNT(*) FROM fact_sales WHERE sub_dept IS NULL").fetchone()[0]
    print(f"    fact_sales.sub_dept: {filled} filled, {null} still NULL")

    # ── Remove 7 rows on non-trading days ──────────────────────────────────
    deleted = conn.execute("""
        DELETE FROM fact_sales
        WHERE date_id IN (
            SELECT d.date_id FROM dim_date d WHERE d.is_trading = 0
        )
    """).rowcount
    print(f"    fact_sales: removed {deleted} rows on non-trading days")


def backfill_fact_invoice(conn: sqlite3.Connection) -> None:
    print("  Backfilling fact_invoice...")
    # product_name from dim_product (denormalised for readability)
    conn.execute("""
        UPDATE fact_invoice
        SET product_name = (
            SELECT dp.name FROM dim_product dp
            WHERE dp.product_id = fact_invoice.product_id
        )
        WHERE product_name IS NULL
    """)
    filled = conn.execute("SELECT COUNT(*) FROM fact_invoice WHERE product_name IS NOT NULL").fetchone()[0]
    print(f"    fact_invoice.product_name: {filled} rows filled")
    # invoice_product_name cannot be recovered for historical rows — stays NULL
    # going forward import scripts will populate it
    null_inv = conn.execute("SELECT COUNT(*) FROM fact_invoice WHERE invoice_product_name IS NULL").fetchone()[0]
    print(f"    fact_invoice.invoice_product_name: {null_inv} historical rows NULL (not recoverable from source)")


def clean_dump_apn(conn: sqlite3.Connection) -> None:
    print("  Cleaning fact_dump APN float strings...")
    rows = conn.execute(
        "SELECT dump_id, apn FROM fact_dump WHERE apn IS NOT NULL AND apn GLOB '*.*'"
    ).fetchall()
    cleaned = [(clean_apn(apn), did) for did, apn in rows if clean_apn(apn) != apn]
    if cleaned:
        conn.executemany("UPDATE fact_dump SET apn=? WHERE dump_id=?", cleaned)
        print(f"    fact_dump: cleaned {len(cleaned)} APN float strings")
    else:
        print("    fact_dump: APNs already clean")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Rebuild views
# ─────────────────────────────────────────────────────────────────────────────

V_WASTE_SUMMARY = """
CREATE VIEW v_waste_summary AS
SELECT
    'dump'              AS waste_type,
    fd.date_id          AS event_date,
    fd.product_id,
    COALESCE(dp.name, fd.description)                                 AS description,
    COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown')                  AS sub_dept,
    COALESCE(dp.department, fd.department)                            AS department,
    fd.qty,
    fd.total_cost_ex    AS waste_cost,
    NULL                AS discount_given,
    NULL                AS realised_profit,
    fd.reason,
    fd.source_file
FROM fact_dump fd
LEFT JOIN dim_product dp ON fd.product_id = dp.product_id

UNION ALL

SELECT
    'markdown'          AS waste_type,
    fm.date_id          AS event_date,
    fm.product_id,
    COALESCE(dp.name, fm.description)                                 AS description,
    COALESCE(NULLIF(dp.sub_dept, 'None'), NULLIF(fm.sub_dept, 'None'), 'Unknown') AS sub_dept,
    COALESCE(dp.department, fm.department)                            AS department,
    fm.lines            AS qty,
    CASE WHEN fm.realised_profit < 0 THEN ABS(fm.realised_profit) ELSE 0 END AS waste_cost,
    fm.discount_given,
    fm.realised_profit,
    NULL                AS reason,
    fm.source_file
FROM fact_markdown fm
LEFT JOIN dim_product dp ON fm.product_id = dp.product_id

UNION ALL

SELECT
    CASE wl.action
        WHEN 'Binned'  THEN 'dump'
        WHEN 'Reduced' THEN 'markdown'
        ELSE 'store_use'
    END                 AS waste_type,
    wl.date_id          AS event_date,
    wl.product_id,
    COALESCE(dp.name, wl.item_name)                                   AS description,
    COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown')                  AS sub_dept,
    COALESCE(dp.department, 'FRUIT & VEG')                            AS department,
    wl.qty,
    wl.costed_cost      AS waste_cost,
    CASE WHEN wl.action = 'Reduced' THEN wl.costed_cost END           AS discount_given,
    NULL                AS realised_profit,
    wl.reason,
    wl.source_file
FROM fact_waste_log wl
LEFT JOIN dim_product dp ON wl.product_id = dp.product_id
"""

def rebuild_views(conn: sqlite3.Connection) -> None:
    print("  Rebuilding views...")
    conn.execute("DROP VIEW IF EXISTS v_waste_summary")
    conn.execute(V_WASTE_SUMMARY)

    # v_item_price — remove sell_price_manual reference
    conn.execute("DROP VIEW IF EXISTS v_item_price")
    conn.execute("""
        CREATE VIEW v_item_price AS
        SELECT
            p.name,
            p.department,
            p.sub_dept,
            r.sell_price,
            r.cost_price,
            r.price_source,
            r.updated_at
        FROM ref_item_price r
        JOIN dim_product p ON r.product_id = p.product_id
    """)
    print("    v_waste_summary: rebuilt")
    print("    v_item_price: rebuilt (removed sell_price_manual, added department/sub_dept)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — Load 2025 Dairy + Meat sales
# ─────────────────────────────────────────────────────────────────────────────

DEPARTMENTS_VALID = {"DAIRY", "MEAT", "FRUIT & VEG"}


def _norm_name(s) -> str | None:
    if pd.isna(s):
        return None
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def load_sales_csv(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    """Insert sales rows from a POS export CSV. Idempotent via UNIQUE(date_id, product_id)."""
    df = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()

    if "Sales Date" in df.columns:
        df = df.rename(columns={"Sales Date": "Date"})
    if "Date" not in df.columns:
        raise ValueError(f"No Date column in {path.name}: {list(df.columns)}")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["Date", "Name"])

    def _f(row, col):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    # Build product id map
    pid_map = {n: pid for n, pid in conn.execute("SELECT name, product_id FROM dim_product")}
    # Build CSV sub_dept/dept lookup for new products
    dept_col = "Department Name" if "Department Name" in df.columns else None
    sd_col   = "Sub Department Name" if "Sub Department Name" in df.columns else None

    imported_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    source_file = path.name

    fact_rows = []
    for _, r in df.iterrows():
        nm = _norm_name(r.get("Name"))
        if not nm:
            continue
        dept = str(r.get(dept_col, "")).strip() if dept_col else None
        if dept and dept not in DEPARTMENTS_VALID:
            continue
        sd = str(r.get(sd_col, "")).strip() if sd_col else None
        if sd and sd.lower() in ("nan", "none", ""):
            sd = None

        pid = pid_map.get(nm)
        if pid is None:
            conn.execute(
                "INSERT OR IGNORE INTO dim_product (name, sub_dept, department, sell_unit, apn) VALUES (?,?,?,?,?)",
                (nm, sd, dept, "each", clean_apn(r.get("APN")))
            )
            pid = conn.execute("SELECT product_id FROM dim_product WHERE name=?", (nm,)).fetchone()[0]
            pid_map[nm] = pid
        else:
            # Update sub_dept / department / apn if currently NULL
            conn.execute("""
                UPDATE dim_product SET
                    sub_dept   = COALESCE(sub_dept, ?),
                    department = COALESCE(department, ?),
                    apn        = COALESCE(NULLIF(apn,'0'), ?)
                WHERE product_id = ?
            """, (sd, dept, clean_apn(r.get("APN")), pid))

        apn = clean_apn(r.get("APN"))
        fact_rows.append((
            str(r["Date"])[:10], pid, r.get("Store Name"), dept, apn,
            sd,
            _f(r, "Sales Inc GST"), _f(r, "Cost Ex GST"), _f(r, "Cost Inc GST"),
            _f(r, "GP %"), _f(r, "GP $"), _f(r, "Lines"), _f(r, "Quantity"),
            _f(r, "Sales Ex GST"), _f(r, "Store Sales Ex"), _f(r, "Store Sales Inc"),
            _f(r, "Online Sales Ex"), _f(r, "Online Sales Inc"),
            imported_at, source_file,
        ))

    cur = conn.executemany("""
        INSERT OR IGNORE INTO fact_sales
          (date_id, product_id, store_name, department, apn, sub_dept,
           sales_inc_gst, cost_ex_gst, cost_inc_gst, gp_pct, gp_dollars,
           lines, quantity, sales_ex_gst,
           store_sales_ex, store_sales_inc, online_sales_ex, online_sales_inc,
           date_imported, source_file)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, fact_rows)
    inserted = cur.rowcount if cur.rowcount >= 0 else len(fact_rows)
    skipped  = len(fact_rows) - inserted
    return inserted, skipped


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 — Load 2025 Markdown data
# ─────────────────────────────────────────────────────────────────────────────

def load_markdown_csv(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    """
    Insert markdown rows from a GAP POS Markdown CSV.
    Columns: Sales Date, Department Name, APN, Name, Sub Department Name,
             Cost Ex GST, Discount, Impact, Lines, Potential Sales,
             Sales Ex GST, Sales Inc GST
    Idempotent: deletes existing rows for this source_file first.
    """
    df = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()

    if "Sales Date" in df.columns:
        df = df.rename(columns={"Sales Date": "Date"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["Date", "Name", "Department Name"])
    df = df[df["Department Name"].isin(DEPARTMENTS_VALID)]

    source_file = path.name
    # Delete any prior load of this file (idempotent)
    conn.execute("DELETE FROM fact_markdown WHERE source_file=?", (source_file,))

    # Build product lookup: apn first, then name
    apn_map  = {clean_apn(a): pid for a, pid in conn.execute(
        "SELECT apn, product_id FROM dim_product WHERE apn IS NOT NULL") if clean_apn(a)}
    name_map = {n: pid for n, pid in conn.execute("SELECT name, product_id FROM dim_product")}

    def _f(row, col):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    rows = []
    for _, r in df.iterrows():
        apn  = clean_apn(r.get("APN"))
        desc = _norm_name(r.get("Name"))
        pid  = apn_map.get(apn) if apn else None
        if pid is None and desc:
            pid = name_map.get(desc)

        dept     = str(r.get("Department Name", "")).strip()
        sd       = str(r.get("Sub Department Name", "")).strip()
        if sd.lower() in ("nan", "none", ""):
            sd = None

        potential  = _f(r, "Potential Sales")
        total_sell = _f(r, "Sales Ex GST")
        total_cost = _f(r, "Cost Ex GST")
        discount   = _f(r, "Discount")         # positive markdown amount
        lines      = _f(r, "Lines")

        # realised_profit = total_sell - total_cost
        realised = None
        if total_sell is not None and total_cost is not None:
            realised = round(total_sell - total_cost, 4)

        rows.append((
            str(r["Date"])[:10], pid, dept, apn, desc, sd,
            lines, potential, total_sell, total_cost,
            discount, realised, source_file,
        ))

    conn.executemany("""
        INSERT INTO fact_markdown
          (date_id, product_id, department, apn, description, sub_dept,
           lines, potential_sell, total_sell, total_cost,
           discount_given, realised_profit, source_file)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)

    return len(rows), 0


# ─────────────────────────────────────────────────────────────────────────────
# Step 7 — APN audit report
# ─────────────────────────────────────────────────────────────────────────────

def apn_audit(conn: sqlite3.Connection) -> None:
    print()
    print("  ── APN Audit (items with NULL APN that have sales) ──────────────")
    rows = conn.execute("""
        SELECT p.name, p.department, p.sub_dept,
               COUNT(DISTINCT s.date_id) as days_sold,
               ROUND(SUM(s.sales_ex_gst),2) as total_rev
        FROM dim_product p
        JOIN fact_sales s ON s.product_id = p.product_id
        WHERE (p.apn IS NULL OR p.apn = '0') AND s.date_id >= '2025-01-01'
        GROUP BY p.product_id ORDER BY total_rev DESC
    """).fetchall()
    if not rows:
        print("  All products with sales have an APN. ✓")
    else:
        print(f"  {len(rows)} products with sales but no APN (investigate PLU assignment):")
        for r in rows:
            print(f"    {r[0][:40]:40s}  dept={r[1]}  days={r[3]}  rev=${r[4]:,.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if check_version():
        print("[SKIP] migrate_v3 already applied — use --force to re-run.")
        if "--force" not in sys.argv:
            return
        print("[FORCE] Re-running migration...")

    print("=" * 60)
    print("  Foodland Wudinna — Schema Migration v3")
    print("=" * 60)

    # Build the CSV sub_dept lookup before opening the write connection
    print("\n[1/7] Building sub_dept / department lookup from CSVs...")
    csv_lookup = build_csv_lookup()

    print("\n[2/7] Applying schema changes...")
    with _write_conn() as conn:
        apply_schema(conn)

    print("\n[3/7] Backfilling dim_product, fact_sales, fact_invoice, fact_dump...")
    with _write_conn() as conn:
        backfill_dim_product(conn, csv_lookup)
        backfill_fact_sales(conn)
        backfill_fact_invoice(conn)
        clean_dump_apn(conn)

    print("\n[4/7] Rebuilding views...")
    with _write_conn() as conn:
        rebuild_views(conn)

    print("\n[5/7] Loading 2025 Dairy sales...")
    with _write_conn() as conn:
        for csv_path in [DAIRY_2025_1, DAIRY_2025_2]:
            if csv_path.exists():
                ins, skp = load_sales_csv(conn, csv_path)
                print(f"    {csv_path.name}: {ins} inserted, {skp} skipped")
            else:
                print(f"    [WARN] {csv_path.name} not found")

    print("\n[5b/7] Loading 2025 Meat sales...")
    with _write_conn() as conn:
        if MEAT_2025.exists():
            ins, skp = load_sales_csv(conn, MEAT_2025)
            print(f"    {MEAT_2025.name}: {ins} inserted, {skp} skipped")
        else:
            print(f"    [WARN] {MEAT_2025.name} not found")

    print("\n[6/7] Loading 2025 Dairy + Meat markdowns...")
    with _write_conn() as conn:
        for md_path in [MD_DAIRY_2025, MD_MEAT_2025]:
            if md_path.exists():
                ins, _ = load_markdown_csv(conn, md_path)
                print(f"    {md_path.name}: {ins} rows loaded")
            else:
                print(f"    [WARN] {md_path.name} not found")

    print("\n[7/7] Stamping version + running audit...")
    with _write_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO _meta (key,value) VALUES (?,?)", ("schema_version", VERSION_FLAG))
        apn_audit(conn)

    # ── Final counts ──────────────────────────────────────────────────────
    r_conn = sqlite3.connect(f"file:{DB}?immutable=1", uri=True)
    print()
    print("=" * 60)
    print("  Migration complete — final row counts")
    print("=" * 60)
    for tbl in ["dim_product", "fact_sales", "fact_dump", "fact_markdown",
                "fact_waste_log", "fact_invoice", "ref_item_price"]:
        cnt = r_conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl:25s}: {cnt:7,d} rows")
    r_conn.close()

    print()
    print("  Note on dim_supplier: Only Freshlink invoices are present in the source")
    print("  data. No supplier column exists in any POS export CSV. dim_supplier")
    print("  correctly retains its single Freshlink entry — no change required.")
    print()
    print("[DONE]")


if __name__ == "__main__":
    main()
