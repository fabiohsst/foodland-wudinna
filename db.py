"""
db.py — Shared SQLite access layer for Foodland Wudinna.

Schema
------
Star schema (v4, migrated April 2026):
  dim_product, dim_date, dim_supplier
  fact_sales, fact_invoice, fact_stock
  fact_dump, fact_markdown, fact_waste_log
  ref_item_price, ref_invoice_mapping

Compatibility views (v_sales, v_item_price, v_price_history,
v_stock_on_hand, v_item_reference, v_waste_summary) mirror legacy
column names so all existing apps continue to work without modification.

Reading
-------
All read functions open the DB with the `immutable=1` URI flag.
This bypasses SQLite locking, which fails on the virtiofs (Windows/OneDrive)
mount.  Safe as long as only one writer is active at a time (which is always
the case here — a single import script).

Writing
-------
For any write operation we:
  1. Copy the DB from the mount to /tmp
  2. Open and modify the /tmp copy (normal SQLite, no virtiofs)
     FK enforcement is ON for all write connections.
  3. Verify the /tmp copy is not truncated before copying back.
  4. Copy the result back to the mount.
  5. Run _verify_db() on the destination to confirm integrity.
  6. Clean up the /tmp copy.

Usage in Streamlit apps
-----------------------
    from db import load_sales, load_item_price   # etc.

Usage in scripts
----------------
Same imports, no Streamlit dependency.
"""

import shutil
import sqlite3
import struct
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

# ── Location ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DB   = ROOT / "foodland_data.db"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _verify_db(path: Path) -> None:
    """
    Confirm the SQLite file on disk is not truncated.

    Reads the 32-byte SQLite header, extracts the declared page count and page
    size, and compares against the actual file size.  Raises RuntimeError if
    more than 2% of pages are missing (2% allows for 1-2 pages of tolerance).

    Called automatically by _write_conn() after every copy-back.
    """
    with open(path, "rb") as f:
        header = f.read(32)
    if len(header) < 32:
        raise RuntimeError(
            f"DB file too small after copy: {path.stat().st_size} bytes"
        )
    magic = header[:16]
    if magic != b"SQLite format 3\x00":
        raise RuntimeError(f"Not a valid SQLite file after copy: {path}")
    page_size  = struct.unpack(">H", header[16:18])[0]
    hdr_pages  = struct.unpack(">I", header[28:32])[0]
    if page_size == 0 or hdr_pages == 0:
        return  # edge case: empty DB or 65536-byte pages
    actual_pages = path.stat().st_size // page_size
    if actual_pages < hdr_pages * 0.98:
        raise RuntimeError(
            f"DB truncation detected after copy-back! "
            f"Header declares {hdr_pages} pages, "
            f"file contains {actual_pages} pages. "
            f"The /tmp copy is preserved — investigate before re-running."
        )


def _read_conn() -> sqlite3.Connection:
    """Open DB in immutable read-only mode (no locking, safe on virtiofs)."""
    if not DB.exists():
        raise FileNotFoundError(f"Database not found: {DB}")
    return sqlite3.connect(f"file:{DB}?immutable=1", uri=True)


@contextmanager
def _write_conn():
    """
    Context manager for write operations.

    1. Copies DB to /tmp.
    2. Opens a writable connection with FK enforcement ON.
    3. Yields the connection; commits on clean exit, rolls back on exception.
    4. Verifies the /tmp copy is intact before touching the mount.
    5. Copies back to the OneDrive mount.
    6. Verifies the destination file is not truncated.
    7. Cleans up the /tmp copy.

    If any step after (3) fails, the mount copy is left untouched.
    """
    tmp = Path(tempfile.mktemp(suffix=".db", prefix="foodland_"))
    try:
        shutil.copy2(DB, tmp)
        conn = sqlite3.connect(tmp)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        # Verify /tmp copy before touching mount
        _verify_db(tmp)
        # Only copy back if we got here without raising
        shutil.copy2(tmp, DB)
        # Verify destination
        _verify_db(DB)
    finally:
        tmp.unlink(missing_ok=True)


# ── Read — Sales ──────────────────────────────────────────────────────────────

def load_sales() -> pd.DataFrame:
    """
    Return normalised sales history.

    Reads from v_sales (compatibility view over fact_sales + dim_product).

    Columns: Date, Name, SubDept, Revenue, Cost, GP, Qty,
             Year, Week (period start), Month (period start), DOW
    Filters: removes FRUIT AND VEG / REDUCED open-ring rows; Qty > 0.
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT date, name, sub_dept, department,
                   sales_ex_gst, cost_ex_gst,
                   (sales_ex_gst - cost_ex_gst) AS gp_dollars,
                   quantity
            FROM   v_sales
            WHERE  quantity > 0
              AND  department = 'FRUIT & VEG'
              AND  name NOT LIKE '%FRUIT AND VEG%'
              AND  name NOT LIKE '%REDUCED%'
            """,
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "date":        "Date",
        "name":        "Name",
        "sub_dept":    "SubDept",
        "department":  "Department",
        "sales_ex_gst": "Revenue",
        "cost_ex_gst":  "Cost",
        "gp_dollars":   "GP",
        "quantity":     "Qty",
    })
    df["Date"]    = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df["Revenue"] = pd.to_numeric(df["Revenue"], errors="coerce").fillna(0)
    df["Cost"]    = pd.to_numeric(df["Cost"],    errors="coerce").fillna(0)
    df["GP"]      = pd.to_numeric(df["GP"],      errors="coerce").fillna(0)
    df["Qty"]     = pd.to_numeric(df["Qty"],     errors="coerce").fillna(0)
    df["SubDept"] = df["SubDept"].fillna("Other")
    df = df.dropna(subset=["Date"])
    df["Year"]  = df["Date"].dt.year
    df["Week"]  = df["Date"].dt.to_period("W").apply(lambda p: p.start_time)
    df["Month"] = df["Date"].dt.to_period("M").apply(lambda p: p.start_time)
    df["DOW"]   = df["Date"].dt.day_name()
    return df


# ── Read — Item price ─────────────────────────────────────────────────────────

def load_item_price() -> pd.DataFrame:
    """
    Return current item price table.

    Reads from v_item_price (compatibility view over ref_item_price + dim_product).
    Columns: Name, sell_price, cost_price, price_source, updated_at
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            "SELECT name, sell_price, cost_price, price_source, updated_at FROM v_item_price",
            conn,
        )
    finally:
        conn.close()
    df = df.rename(columns={"name": "Name"})
    return df


# ── Read — Price history ──────────────────────────────────────────────────────

def load_price_history() -> pd.DataFrame:
    """
    Return full price history log.

    Reads from v_price_history (compatibility view over fact_invoice + dim_product).
    Columns: date, invoice_no, pos_name, cost_per_unit, sell_price, gp_pct, source
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM v_price_history ORDER BY date", conn)
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


# ── Read — Stock on hand ──────────────────────────────────────────────────────

def load_stock_on_hand(date_recorded: str | None = None) -> pd.DataFrame:
    """
    Return stock on hand snapshot.

    Reads from v_stock_on_hand (compatibility view over fact_stock + dim_product).
    Pass date_recorded (ISO string) to filter to a specific snapshot date.
    If omitted, returns the most recent snapshot.

    Columns: name, stock, source, date_recorded
    """
    conn = _read_conn()
    try:
        if date_recorded:
            df = pd.read_sql_query(
                "SELECT name, stock, source, date_recorded FROM v_stock_on_hand "
                "WHERE date_recorded = ?",
                conn,
                params=(date_recorded,),
            )
        else:
            latest = conn.execute(
                "SELECT MAX(date_id) FROM fact_stock"
            ).fetchone()[0]
            df = pd.read_sql_query(
                "SELECT name, stock, source, date_recorded FROM v_stock_on_hand "
                "WHERE date_recorded = ?",
                conn,
                params=(latest,),
            )
    finally:
        conn.close()
    return df


# ── Read — Item reference ─────────────────────────────────────────────────────

def load_item_reference() -> pd.DataFrame:
    """
    Return item reference table (PLU → name mapping).

    Reads from v_item_reference (compatibility view over dim_product).
    Columns: plu, name
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query("SELECT plu, name FROM v_item_reference", conn)
    finally:
        conn.close()
    return df


# ── Read — New star-schema helpers ────────────────────────────────────────────

def load_dim_product() -> pd.DataFrame:
    """
    Return the full product dimension.

    Columns: product_id, name, sub_dept, department, sell_unit, apn, active, created_at
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            "SELECT product_id, name, sub_dept, department, sell_unit, apn, active, created_at "
            "FROM dim_product ORDER BY name",
            conn,
        )
    finally:
        conn.close()
    return df


def load_dim_date(
    start: str | None = None,
    end: str | None = None,
    trading_only: bool = False,
) -> pd.DataFrame:
    """
    Return the date dimension, optionally filtered.

    Columns: date_id, year, month, month_name, week_num, day_of_week,
             day_name, is_weekend, is_holiday, holiday_name, is_trading
    """
    where_clauses = []
    params = []
    if start:
        where_clauses.append("date_id >= ?")
        params.append(start)
    if end:
        where_clauses.append("date_id <= ?")
        params.append(end)
    if trading_only:
        where_clauses.append("is_trading = 1")

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            f"SELECT * FROM dim_date {where} ORDER BY date_id",
            conn,
            params=params if params else None,
        )
    finally:
        conn.close()
    df["date_id"] = pd.to_datetime(df["date_id"], errors="coerce")
    return df


def load_invoice_mapping() -> pd.DataFrame:
    """
    Return the invoice description → product mapping table.

    Columns: mapping_id, invoice_description, product_id, pos_name,
             units_per_invoice, sell_unit, supplier_id, supplier_name,
             verified, notes
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT m.mapping_id, m.invoice_description,
                   m.product_id, p.name AS pos_name,
                   m.units_per_invoice, m.sell_unit,
                   m.supplier_id, s.name AS supplier_name,
                   m.verified, m.notes
            FROM  ref_invoice_mapping m
            LEFT  JOIN dim_product  p ON m.product_id  = p.product_id
            LEFT  JOIN dim_supplier s ON m.supplier_id = s.supplier_id
            ORDER BY m.invoice_description
            """,
            conn,
        )
    finally:
        conn.close()
    return df


# ── Read — Dump waste (fact_dump) ────────────────────────────────────────────

def load_dump(department: str | None = None) -> pd.DataFrame:
    """
    Return dump stock transactions (full write-offs).

    Joins to dim_product for name and sub_dept where matched.

    Columns: dump_id, date_id, product_id, description, sub_dept, department,
             apn, item_no, qty, unit_cost_ex, unit_sell_ex, reason,
             total_cost_ex, total_sell_ex, source_file

    Parameters
    ----------
    department : filter to a specific department string (e.g. 'FRUIT & VEG').
                 Pass None to return all departments.
    """
    where = "WHERE fd.department = ?" if department else ""
    params = (department,) if department else None
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            f"""
            SELECT fd.dump_id, fd.date_id, fd.product_id,
                   COALESCE(dp.name, fd.description) AS description,
                   dp.sub_dept,
                   fd.department, fd.apn, fd.item_no,
                   fd.qty, fd.unit_cost_ex, fd.unit_sell_ex, fd.reason,
                   fd.total_cost_ex, fd.total_sell_ex, fd.source_file
            FROM fact_dump fd
            LEFT JOIN dim_product dp ON fd.product_id = dp.product_id
            {where}
            ORDER BY fd.date_id
            """,
            conn,
            params=params,
        )
    finally:
        conn.close()
    df["date_id"] = pd.to_datetime(df["date_id"], errors="coerce")
    return df


def load_markdown(department: str | None = None) -> pd.DataFrame:
    """
    Return markdown (discounted sale) aggregate lines.

    Joins to dim_product for name and sub_dept where matched.

    Columns: markdown_id, period_start, period_end, product_id, description,
             sub_dept, department, apn, item_no, weight_kg, qty,
             potential_sell, total_sell, avg_unit_kg_sell, total_cost,
             avg_cost_kg_unit, discount_given, realised_profit, gp_pct,
             source_file

    Parameters
    ----------
    department : filter to a specific department string (e.g. 'FRUIT & VEG').
                 Pass None to return all departments.
    """
    where = "WHERE fm.department = ?" if department else ""
    params = (department,) if department else None
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            f"""
            SELECT fm.markdown_id, fm.period_start, fm.period_end, fm.product_id,
                   COALESCE(dp.name, fm.description) AS description,
                   dp.sub_dept,
                   fm.department, fm.apn, fm.item_no,
                   fm.weight_kg, fm.qty, fm.potential_sell, fm.total_sell,
                   fm.avg_unit_kg_sell, fm.total_cost, fm.avg_cost_kg_unit,
                   fm.discount_given, fm.realised_profit, fm.gp_pct,
                   fm.source_file
            FROM fact_markdown fm
            LEFT JOIN dim_product dp ON fm.product_id = dp.product_id
            {where}
            ORDER BY fm.department, fm.description
            """,
            conn,
            params=params,
        )
    finally:
        conn.close()
    return df


# ── Read — Manual waste log (fact_waste_log) ─────────────────────────────────

def load_waste_log() -> pd.DataFrame:
    """
    Return the manual FV waste log entries.

    Joins to dim_product for name and sub_dept where matched.

    Columns: log_id, date_id, product_id, description, sub_dept,
             qty, unit, sell_price, action, new_price, reason,
             costed_cost, cost_source, source_file

    action values: Binned | Reduced | Stir Fry | Fruit Plate

    Notes on cost columns:
      costed_cost — best-available cost of goods (qty × cost_price from
                    ref_item_price). NULL if item not in ref_item_price.
      cost_source — 'confirmed' (matched via ref_item_price) or
                    'estimated' (fallback calculation).
    """
    conn = _read_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT wl.log_id, wl.date_id, wl.product_id,
                   COALESCE(dp.name, wl.item_name) AS description,
                   dp.sub_dept,
                   wl.qty, wl.unit, wl.sell_price, wl.action,
                   wl.new_price, wl.reason,
                   wl.costed_cost, wl.cost_source, wl.source_file
            FROM fact_waste_log wl
            LEFT JOIN dim_product dp ON wl.product_id = dp.product_id
            ORDER BY wl.date_id
            """,
            conn,
        )
    finally:
        conn.close()
    df["date_id"] = pd.to_datetime(df["date_id"], errors="coerce")
    return df


# ── Write — Append price history (fact_invoice) ───────────────────────────────

def append_price_history(rows: list[dict]) -> int:
    """
    Insert new price-change events (idempotent — skips duplicates).

    Each dict must contain: date, invoice_no, pos_name,
    and optionally: cost_per_unit, sell_price, gp_pct, source.

    Returns the number of rows actually inserted.
    """
    import re as _re

    if not rows:
        return 0

    def _norm(s):
        return _re.sub(r"\s+", " ", str(s)).strip().upper()

    with _write_conn() as conn:
        pid_map = {
            name: pid
            for name, pid in conn.execute("SELECT name, product_id FROM dim_product")
        }

        params = []
        for r in rows:
            name = _norm(r.get("pos_name", ""))
            pid  = pid_map.get(name)
            if pid is None:
                continue  # product not found — skip silently
            params.append((
                str(r["date"])[:10],
                str(r["invoice_no"]),
                pid,
                r.get("cost_per_unit"),
                r.get("sell_price"),
                r.get("gp_pct"),
                str(r.get("source", "")),
            ))

        cur = conn.executemany(
            """INSERT OR IGNORE INTO fact_invoice
               (date_id, invoice_no, product_id, cost_per_unit, sell_price, gp_pct, source)
               VALUES (?,?,?,?,?,?,?)""",
            params,
        )
        inserted = cur.rowcount if cur.rowcount >= 0 else 0
    return inserted


# ── Write — Upsert item price (ref_item_price) ────────────────────────────────

def upsert_item_prices(rows: list[dict]) -> int:
    """
    Insert or update current sell/cost prices per product.

    Each dict must contain: Name (or name).
    Optional fields: sell_price, cost_price, price_source.

    Returns the number of rows written.
    """
    import re as _re
    from datetime import date as _date

    def _norm(s):
        return _re.sub(r"\s+", " ", str(s)).strip().upper()

    with _write_conn() as conn:
        pid_map = {
            name: pid
            for name, pid in conn.execute("SELECT name, product_id FROM dim_product")
        }

        params = []
        for r in rows:
            name = _norm(r.get("Name", r.get("name", "")))
            pid  = pid_map.get(name)
            if pid is None:
                # Auto-register unknown products
                conn.execute(
                    "INSERT OR IGNORE INTO dim_product (name, sell_unit) VALUES (?,?)",
                    (name, "each"),
                )
                pid = conn.execute(
                    "SELECT product_id FROM dim_product WHERE name=?", (name,)
                ).fetchone()[0]
                pid_map[name] = pid
            params.append((
                pid,
                r.get("sell_price"),
                r.get("cost_price"),
                r.get("price_source", "manual"),
                _date.today().isoformat(),
            ))

        cur = conn.executemany(
            """INSERT OR REPLACE INTO ref_item_price
               (product_id, sell_price, cost_price, price_source, updated_at)
               VALUES (?,?,?,?,?)""",
            params,
        )
        written = cur.rowcount if cur.rowcount >= 0 else len(params)
    return written


# ── Write — Append stock snapshot (fact_stock) ────────────────────────────────

def append_stock_snapshot(rows: list[dict], date_recorded: str) -> int:
    """
    Insert a new stock-on-hand snapshot (idempotent per product+date).

    Each dict must contain: name, and optionally: stock, source.

    Returns the number of rows inserted.
    """
    import re as _re

    def _norm(s):
        return _re.sub(r"\s+", " ", str(s)).strip().upper()

    with _write_conn() as conn:
        pid_map = {
            name: pid
            for name, pid in conn.execute("SELECT name, product_id FROM dim_product")
        }

        params = []
        for r in rows:
            name = _norm(r["name"])
            pid  = pid_map.get(name)
            if pid is None:
                continue
            params.append((
                date_recorded,
                pid,
                r.get("stock"),
                str(r.get("source", "")),
            ))

        cur = conn.executemany(
            """INSERT OR IGNORE INTO fact_stock (date_id, product_id, stock, source)
               VALUES (?,?,?,?)""",
            params,
        )
        inserted = cur.rowcount if cur.rowcount >= 0 else 0
    return inserted


# ── Write — Import sales rows (fact_sales) ────────────────────────────────────

def import_sales_rows(rows: list[tuple]) -> tuple[int, int]:
    """
    Insert sales rows into fact_sales (idempotent — UNIQUE on date_id + product_id).

    Each tuple must match this column order:
    (date, department, name, sub_dept,
     sales_inc_gst, cost_ex_gst, cost_inc_gst, lines,
     quantity, sales_ex_gst, date_imported, source_file)

    Automatically creates dim_product entries for any new product names.

    Returns (inserted, skipped).
    """
    import re as _re

    if not rows:
        return 0, 0

    def _norm(s):
        return _re.sub(r"\s+", " ", str(s)).strip().upper()

    with _write_conn() as conn:
        pid_map = {
            name: pid
            for name, pid in conn.execute("SELECT name, product_id FROM dim_product")
        }

        fact_params = []
        for r in rows:
            (date, dept, name, sub_dept,
             s_inc, c_ex, c_inc, lines, qty, s_ex,
             di, sf) = r

            norm_name = _norm(name) if name else None
            if not norm_name:
                continue

            pid = pid_map.get(norm_name)
            if pid is None:
                conn.execute(
                    "INSERT OR IGNORE INTO dim_product (name, sub_dept, sell_unit) VALUES (?,?,?)",
                    (norm_name, sub_dept, "each"),
                )
                pid = conn.execute(
                    "SELECT product_id FROM dim_product WHERE name=?", (norm_name,)
                ).fetchone()[0]
                pid_map[norm_name] = pid

            fact_params.append((
                str(date)[:10], pid, dept,
                s_inc, c_ex, c_inc,
                lines, qty, s_ex,
                di, sf,
            ))

        cur = conn.executemany(
            """INSERT OR IGNORE INTO fact_sales
               (date_id, product_id, department,
                sales_inc_gst, cost_ex_gst, cost_inc_gst,
                lines, quantity, sales_ex_gst,
                date_imported, source_file)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            fact_params,
        )
        inserted = cur.rowcount if cur.rowcount >= 0 else len(fact_params)

    skipped = len(rows) - inserted
    return inserted, skipped


# ── Write — Upsert invoice mapping ───────────────────────────────────────────

def upsert_invoice_mapping(rows: list[dict]) -> int:
    """
    Insert or update invoice description → product mappings.

    Each dict must contain: invoice_description, pos_name.
    Optional: units_per_invoice, sell_unit, supplier, verified, notes.

    Returns the number of rows written.
    """
    import re as _re

    def _norm(s):
        return _re.sub(r"\s+", " ", str(s)).strip().upper()

    with _write_conn() as conn:
        pid_map = {
            name: pid
            for name, pid in conn.execute("SELECT name, product_id FROM dim_product")
        }
        sup_map = {
            name.upper(): sid
            for name, sid in conn.execute("SELECT name, supplier_id FROM dim_supplier")
        }

        params = []
        for r in rows:
            inv_desc = str(r.get("invoice_description", "")).strip()
            pos_name = _norm(r.get("pos_name", ""))
            pid  = pid_map.get(pos_name)
            sup  = _norm(r.get("supplier", ""))
            sid  = sup_map.get(sup)
            units = r.get("units_per_invoice")
            units = float(units) if units is not None else None
            verified = 1 if str(r.get("verified", "false")).lower() in ("true", "1") else 0
            params.append((
                inv_desc, pid, units,
                str(r.get("sell_unit", "")).strip() or None,
                sid, verified,
                str(r.get("notes", "")).strip() or None,
            ))

        cur = conn.executemany(
            """INSERT OR REPLACE INTO ref_invoice_mapping
               (invoice_description, product_id, units_per_invoice, sell_unit,
                supplier_id, verified, notes)
               VALUES (?,?,?,?,?,?,?)""",
            params,
        )
        written = cur.rowcount if cur.rowcount >= 0 else len(params)
    return written
