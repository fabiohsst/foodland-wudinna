"""
migrate_v2.py — Foodland Wudinna
Star-schema migration: creates the new normalised database structure and
migrates all existing data into it.

New tables
----------
  dim_product         — one row per product; central FK anchor
  dim_date            — one row per calendar day; includes SA holidays
  dim_supplier        — one row per supplier
  fact_sales          — sales facts (FK to dim_product + dim_date)
  fact_invoice        — invoice/price-change events
  fact_stock          — stock-on-hand snapshots
  ref_item_price      — current sell / cost prices per product
  ref_invoice_mapping — invoice description → product mapping

Compatibility views
-------------------
  v_sales, v_item_price, v_price_history, v_stock_on_hand, v_item_reference
  These mirror the old flat-table columns exactly so every existing app
  (panel.py, waste_dashboard.py, app.py, etc.) keeps working unchanged.

virtiofs constraint
-------------------
  Builds the entire new DB in /tmp, then shutil.copy2() to the mount.
  Never writes directly to the OneDrive-backed virtiofs path.

Usage
-----
    python migrate_v2.py
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent
DB_DEST = ROOT / "foodland_data.db"
DB_TEMP = Path(tempfile.mktemp(suffix=".db", prefix="foodland_v2_"))

REF_DIR       = ROOT / "01_data" / "reference"
HOLIDAYS_CSV  = REF_DIR / "sa_holidays_prophet.csv"
MAPPING_CSV   = REF_DIR / "invoice_item_mapping.csv"


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_conn() -> sqlite3.Connection:
    """Open existing DB in immutable read-only mode (safe on virtiofs)."""
    if not DB_DEST.exists():
        raise FileNotFoundError(f"Source DB not found: {DB_DEST}")
    return sqlite3.connect(f"file:{DB_DEST}?immutable=1", uri=True)


def report(label: str, n: int):
    print(f"  {label:<40}  {n:>7,}")


# ── Schema ────────────────────────────────────────────────────────────────────

DDL = """
-- ─────────────────────────────────────────
--  Dimension tables
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dim_product (
    product_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    sub_dept     TEXT,
    category     TEXT,
    sell_unit    TEXT    DEFAULT 'each',
    plu          TEXT,
    active       INTEGER DEFAULT 1,
    created_at   TEXT    DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_id      TEXT PRIMARY KEY,   -- ISO YYYY-MM-DD
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    month_name   TEXT    NOT NULL,
    week_num     INTEGER NOT NULL,   -- ISO week number
    day_of_week  INTEGER NOT NULL,   -- 0=Mon … 6=Sun
    day_name     TEXT    NOT NULL,
    is_weekend   INTEGER NOT NULL,   -- 1 for Sat/Sun
    is_holiday   INTEGER DEFAULT 0,
    holiday_name TEXT,
    is_trading   INTEGER NOT NULL    -- 1 if store open per operating schedule
);

CREATE TABLE IF NOT EXISTS dim_supplier (
    supplier_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT UNIQUE NOT NULL COLLATE NOCASE,
    delivery_days  TEXT        -- e.g. 'TUE,FRI'
);

-- ─────────────────────────────────────────
--  Fact tables
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id        TEXT    NOT NULL REFERENCES dim_date(date_id),
    product_id     INTEGER NOT NULL REFERENCES dim_product(product_id),
    store_name     TEXT,
    department     TEXT,
    apn            TEXT,
    sales_inc_gst  REAL,
    cost_ex_gst    REAL,
    cost_inc_gst   REAL,
    gp_pct         REAL,
    gp_dollars     REAL,
    lines          INTEGER,
    quantity       REAL,
    sales_ex_gst   REAL,
    store_sales_ex   REAL,
    store_sales_inc  REAL,
    online_sales_ex  REAL,
    online_sales_inc REAL,
    date_imported  TEXT,
    source_file    TEXT,
    UNIQUE(date_id, product_id)
);

CREATE TABLE IF NOT EXISTS fact_invoice (
    invoice_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id       TEXT    NOT NULL REFERENCES dim_date(date_id),
    invoice_no    TEXT    NOT NULL,
    product_id    INTEGER NOT NULL REFERENCES dim_product(product_id),
    supplier_id   INTEGER REFERENCES dim_supplier(supplier_id),
    cost_per_unit REAL,
    sell_price    REAL,
    gp_pct        REAL,
    source        TEXT,
    UNIQUE(invoice_no, product_id)
);

CREATE TABLE IF NOT EXISTS fact_stock (
    stock_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id     TEXT    NOT NULL REFERENCES dim_date(date_id),
    product_id  INTEGER NOT NULL REFERENCES dim_product(product_id),
    stock       REAL,
    source      TEXT,
    UNIQUE(product_id, date_id)
);

-- ─────────────────────────────────────────
--  Reference tables
-- ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ref_item_price (
    product_id         INTEGER PRIMARY KEY REFERENCES dim_product(product_id),
    sell_price_manual  REAL,
    sell_price         REAL,
    cost_price         REAL,
    updated_at         TEXT DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS ref_invoice_mapping (
    mapping_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_description TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    product_id          INTEGER REFERENCES dim_product(product_id),
    units_per_invoice   REAL,
    sell_unit           TEXT,
    supplier_id         INTEGER REFERENCES dim_supplier(supplier_id),
    verified            INTEGER DEFAULT 0,
    notes               TEXT
);

-- ─────────────────────────────────────────
--  Compatibility views
--  (preserve old column names so all apps keep working)
-- ─────────────────────────────────────────

CREATE VIEW IF NOT EXISTS v_sales AS
SELECT
    s.date_id           AS date,
    p.name,
    p.sub_dept,
    s.store_name,
    s.department,
    s.apn,
    s.sales_inc_gst,
    s.cost_ex_gst,
    s.cost_inc_gst,
    s.gp_pct,
    s.gp_dollars,
    s.lines,
    s.quantity,
    s.sales_ex_gst,
    s.store_sales_ex,
    s.store_sales_inc,
    s.online_sales_ex,
    s.online_sales_inc,
    s.date_imported,
    s.source_file
FROM  fact_sales s
JOIN  dim_product p ON s.product_id = p.product_id;

CREATE VIEW IF NOT EXISTS v_item_price AS
SELECT
    p.name,
    r.sell_price_manual,
    r.sell_price,
    r.cost_price
FROM  ref_item_price r
JOIN  dim_product p ON r.product_id = p.product_id;

CREATE VIEW IF NOT EXISTS v_price_history AS
SELECT
    i.date_id     AS date,
    i.invoice_no,
    p.name        AS pos_name,
    i.cost_per_unit,
    i.sell_price,
    i.gp_pct,
    i.source
FROM  fact_invoice i
JOIN  dim_product p ON i.product_id = p.product_id
ORDER BY i.date_id;

CREATE VIEW IF NOT EXISTS v_stock_on_hand AS
SELECT
    p.name,
    s.stock,
    s.source,
    s.date_id AS date_recorded
FROM  fact_stock s
JOIN  dim_product p ON s.product_id = p.product_id;

CREATE VIEW IF NOT EXISTS v_item_reference AS
SELECT plu, name
FROM   dim_product
WHERE  plu IS NOT NULL;
"""


# ── Step 1 — Build dim_date ───────────────────────────────────────────────────

def build_dim_date(conn: sqlite3.Connection, start: date, end: date):
    """
    Populate dim_date for every calendar day from start to end (inclusive).
    Marks SA public holidays and trading days per store schedule:
      Mon–Fri 08:30–18:00, Sat 08:30–12:00, Sun + holidays = closed.
    """
    holidays: dict[str, str] = {}
    if HOLIDAYS_CSV.exists():
        hdf = pd.read_csv(HOLIDAYS_CSV)
        for _, row in hdf.iterrows():
            holidays[str(row["ds"])[:10]] = str(row["holiday"])

    rows = []
    day = start
    MONTH_NAMES = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    DAY_NAMES   = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

    while day <= end:
        ds         = day.isoformat()
        dow        = day.weekday()          # 0=Mon … 6=Sun
        is_weekend = 1 if dow >= 5 else 0
        is_hol     = 1 if ds in holidays else 0
        hol_name   = holidays.get(ds)
        # Store is open Mon-Fri (not holiday) or Sat (not holiday)
        is_trading = 1 if (dow <= 4 and not is_hol) or (dow == 5 and not is_hol) else 0

        rows.append((
            ds,
            day.year,
            day.month,
            MONTH_NAMES[day.month - 1],
            day.isocalendar()[1],    # ISO week number
            dow,
            DAY_NAMES[dow],
            is_weekend,
            is_hol,
            hol_name,
            is_trading,
        ))
        day += timedelta(days=1)

    conn.executemany(
        """INSERT OR IGNORE INTO dim_date
           (date_id, year, month, month_name, week_num,
            day_of_week, day_name, is_weekend, is_holiday, holiday_name, is_trading)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    return len(rows)


# ── Step 2 — Build dim_product ────────────────────────────────────────────────

def build_dim_product(conn: sqlite3.Connection, src: sqlite3.Connection) -> dict[str, int]:
    """
    Collects all unique product names from sales, item_price, item_reference,
    price_history, stock_on_hand and the invoice mapping CSV.

    For each product, picks the most-common sub_dept from sales rows.
    Copies sell_unit from invoice_item_mapping where available.

    Returns a name → product_id mapping dict.
    """
    # Collect all names
    names: set[str] = set()

    for table, col in [
        ("sales",         "name"),
        ("item_price",    "name"),
        ("item_reference","name"),
        ("price_history", "pos_name"),
        ("stock_on_hand", "name"),
    ]:
        for (n,) in src.execute(f"SELECT DISTINCT {col} FROM {table}"):
            if n:
                names.add(n.strip().upper())

    # Include POS names from the invoice mapping CSV
    sell_unit_map: dict[str, str] = {}
    if MAPPING_CSV.exists():
        mdf = pd.read_csv(MAPPING_CSV)
        for _, row in mdf.iterrows():
            pn = str(row["pos_name"]).strip().upper()
            names.add(pn)
            if pd.notna(row.get("sell_unit")):
                sell_unit_map[pn] = str(row["sell_unit"]).strip().lower()

    # Build best sub_dept per name from sales (most common non-null value)
    sub_dept_map: dict[str, str] = {}
    rows_sd = src.execute(
        """SELECT name, sub_dept, COUNT(*) c
           FROM sales
           WHERE sub_dept IS NOT NULL AND sub_dept != ''
           GROUP BY name, sub_dept
           ORDER BY name, c DESC"""
    ).fetchall()
    seen: set[str] = set()
    for name, sd, _ in rows_sd:
        key = name.strip().upper()
        if key not in seen:
            sub_dept_map[key] = sd
            seen.add(key)

    # PLU map from item_reference
    plu_map: dict[str, str] = {}
    for plu, name in src.execute("SELECT plu, name FROM item_reference"):
        if plu and name:
            plu_map[name.strip().upper()] = str(plu)

    # Insert into dim_product
    product_rows = []
    for n in sorted(names):
        product_rows.append((
            n,
            sub_dept_map.get(n),
            None,                       # category — reserved for future
            sell_unit_map.get(n, "each"),
            plu_map.get(n),
        ))

    conn.executemany(
        """INSERT OR IGNORE INTO dim_product (name, sub_dept, category, sell_unit, plu)
           VALUES (?,?,?,?,?)""",
        product_rows,
    )

    # Return name → product_id lookup
    return {
        name: pid
        for name, pid in conn.execute("SELECT name, product_id FROM dim_product")
    }


# ── Step 3 — Build dim_supplier ───────────────────────────────────────────────

def build_dim_supplier(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Seeds dim_supplier from the invoice mapping CSV.
    Hard-codes Freshlink with known delivery days.
    Returns name (upper) → supplier_id mapping.
    """
    suppliers = [("FRESHLINK", "TUE,FRI")]

    if MAPPING_CSV.exists():
        mdf = pd.read_csv(MAPPING_CSV)
        for sup in mdf["supplier"].dropna().unique():
            key = str(sup).strip().upper()
            if key not in {s[0] for s in suppliers}:
                suppliers.append((key, None))

    conn.executemany(
        "INSERT OR IGNORE INTO dim_supplier (name, delivery_days) VALUES (?,?)",
        suppliers,
    )

    return {
        name.upper(): sid
        for name, sid in conn.execute("SELECT name, supplier_id FROM dim_supplier")
    }


# ── Step 4 — Migrate fact_sales ───────────────────────────────────────────────

def migrate_fact_sales(
    conn: sqlite3.Connection,
    src: sqlite3.Connection,
    pid_map: dict[str, int],
) -> int:
    rows = src.execute(
        """SELECT date, name, store_name, department, apn,
                  sales_inc_gst, cost_ex_gst, cost_inc_gst, gp_pct, gp_dollars,
                  lines, quantity, sales_ex_gst,
                  store_sales_ex, store_sales_inc, online_sales_ex, online_sales_inc,
                  date_imported, source_file
           FROM sales
           WHERE quantity > 0"""
    ).fetchall()

    params = []
    skipped = 0
    for r in rows:
        (dt, name, store, dept, apn,
         s_inc, c_ex, c_inc, gp_pct, gp_dol,
         lines, qty, s_ex,
         sse, ssi, ose, osi,
         di, sf) = r
        pid = pid_map.get(name.strip().upper() if name else "")
        if pid is None:
            skipped += 1
            continue
        params.append((
            str(dt)[:10], pid, store, dept, apn,
            s_inc, c_ex, c_inc, gp_pct, gp_dol,
            lines, qty, s_ex,
            sse, ssi, ose, osi,
            di, sf,
        ))

    conn.executemany(
        """INSERT OR IGNORE INTO fact_sales
           (date_id, product_id, store_name, department, apn,
            sales_inc_gst, cost_ex_gst, cost_inc_gst, gp_pct, gp_dollars,
            lines, quantity, sales_ex_gst,
            store_sales_ex, store_sales_inc, online_sales_ex, online_sales_inc,
            date_imported, source_file)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        params,
    )
    if skipped:
        print(f"    ⚠  fact_sales: {skipped} rows skipped (product not found in dim_product)")
    return len(params)


# ── Step 5 — Migrate fact_invoice (price_history) ─────────────────────────────

def migrate_fact_invoice(
    conn: sqlite3.Connection,
    src: sqlite3.Connection,
    pid_map: dict[str, int],
    sup_map: dict[str, int],
) -> int:
    rows = src.execute(
        "SELECT date, invoice_no, pos_name, cost_per_unit, sell_price, gp_pct, source "
        "FROM price_history"
    ).fetchall()

    params = []
    skipped = 0
    for dt, inv, pos_name, cpu, sp, gp, source in rows:
        pid = pid_map.get(pos_name.strip().upper() if pos_name else "")
        if pid is None:
            skipped += 1
            continue
        # Normalise date: handle both YYYY-MM-DD and DD/MM/YYYY formats
        dt_str = str(dt).strip()
        if "/" in dt_str:
            parts = dt_str.split("/")
            dt_str = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        else:
            dt_str = dt_str[:10]
        # Infer supplier from source field (e.g. "INV8543 Freshlink")
        sid = None
        if source:
            for sup_name, sup_id in sup_map.items():
                if sup_name in source.upper():
                    sid = sup_id
                    break
        params.append((dt_str, str(inv), pid, sid, cpu, sp, gp, source))

    conn.executemany(
        """INSERT OR IGNORE INTO fact_invoice
           (date_id, invoice_no, product_id, supplier_id,
            cost_per_unit, sell_price, gp_pct, source)
           VALUES (?,?,?,?,?,?,?,?)""",
        params,
    )
    if skipped:
        print(f"    ⚠  fact_invoice: {skipped} rows skipped (product not found)")
    return len(params)


# ── Step 6 — Migrate fact_stock ───────────────────────────────────────────────

def migrate_fact_stock(
    conn: sqlite3.Connection,
    src: sqlite3.Connection,
    pid_map: dict[str, int],
) -> int:
    rows = src.execute(
        "SELECT name, stock, source, date_recorded FROM stock_on_hand"
    ).fetchall()

    params = []
    skipped = 0
    for name, stock, source, dr in rows:
        pid = pid_map.get(name.strip().upper() if name else "")
        if pid is None:
            skipped += 1
            continue
        params.append((str(dr)[:10], pid, stock, source))

    conn.executemany(
        """INSERT OR IGNORE INTO fact_stock (date_id, product_id, stock, source)
           VALUES (?,?,?,?)""",
        params,
    )
    if skipped:
        print(f"    ⚠  fact_stock: {skipped} rows skipped (product not found)")
    return len(params)


# ── Step 7 — Migrate ref_item_price ──────────────────────────────────────────

def migrate_ref_item_price(
    conn: sqlite3.Connection,
    src: sqlite3.Connection,
    pid_map: dict[str, int],
) -> int:
    rows = src.execute(
        "SELECT name, sell_price_manual, sell_price, cost_price FROM item_price"
    ).fetchall()

    params = []
    skipped = 0
    for name, spm, sp, cp in rows:
        pid = pid_map.get(name.strip().upper() if name else "")
        if pid is None:
            skipped += 1
            continue
        params.append((pid, spm, sp, cp))

    conn.executemany(
        """INSERT OR REPLACE INTO ref_item_price
           (product_id, sell_price_manual, sell_price, cost_price)
           VALUES (?,?,?,?)""",
        params,
    )
    if skipped:
        print(f"    ⚠  ref_item_price: {skipped} rows skipped (product not found)")
    return len(params)


# ── Step 8 — Migrate ref_invoice_mapping ─────────────────────────────────────

def migrate_ref_invoice_mapping(
    conn: sqlite3.Connection,
    pid_map: dict[str, int],
    sup_map: dict[str, int],
) -> int:
    if not MAPPING_CSV.exists():
        print(f"    ⚠  {MAPPING_CSV.name} not found — skipping invoice mapping")
        return 0

    mdf = pd.read_csv(MAPPING_CSV)
    params = []
    skipped = 0
    for _, row in mdf.iterrows():
        inv_desc = str(row["invoice_description"]).strip()
        pos_name = str(row["pos_name"]).strip().upper() if pd.notna(row["pos_name"]) else None

        pid = pid_map.get(pos_name) if pos_name else None
        if pid is None:
            skipped += 1

        sup_name = str(row.get("supplier", "")).strip().upper() if pd.notna(row.get("supplier")) else None
        sid = sup_map.get(sup_name) if sup_name else None

        units = row.get("units_per_invoice")
        units = float(units) if pd.notna(units) else None

        sell_unit = str(row["sell_unit"]).strip() if pd.notna(row.get("sell_unit")) else None
        verified  = 1 if str(row.get("verified", "false")).lower() == "true" else 0
        notes     = str(row["notes"]).strip() if pd.notna(row.get("notes")) else None

        params.append((inv_desc, pid, units, sell_unit, sid, verified, notes))

    conn.executemany(
        """INSERT OR IGNORE INTO ref_invoice_mapping
           (invoice_description, product_id, units_per_invoice, sell_unit,
            supplier_id, verified, notes)
           VALUES (?,?,?,?,?,?,?)""",
        params,
    )
    if skipped:
        print(f"    ⚠  ref_invoice_mapping: {skipped} rows with no matching product_id (unverified mappings)")
    return len(params)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    SEP = "─" * 54

    print(f"\n  Foodland Wudinna — Database Migration v2")
    print(f"  Star schema: dim/fact/ref structure")
    print(f"  {SEP}\n")

    # ── Read source data ──────────────────────────────────────────────────────
    print("  Reading source database …")
    src = read_conn()

    (min_date, max_date) = src.execute(
        "SELECT MIN(date), MAX(date) FROM sales"
    ).fetchone()
    # Extend dim_date one year in either direction for safety
    dim_start = date.fromisoformat(min_date) - timedelta(days=30)
    dim_end   = date.fromisoformat(max_date) + timedelta(days=365)

    # ── Build new DB in /tmp ──────────────────────────────────────────────────
    print(f"  Building new schema in {DB_TEMP.name} …\n")
    conn = sqlite3.connect(DB_TEMP)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")

    # Apply DDL (tables + views).
    # executescript() is safe here because we're in /tmp — not on the virtiofs mount.
    conn.executescript(DDL)

    print(f"  {SEP}")
    print(f"  {'Table':<40}  {'Rows':>7}")
    print(f"  {SEP}")

    # 1 — dim_date
    n = build_dim_date(conn, dim_start, dim_end)
    report("dim_date", n)

    # 2 — dim_product
    pid_map = build_dim_product(conn, src)
    n = conn.execute("SELECT COUNT(*) FROM dim_product").fetchone()[0]
    report("dim_product", n)

    # 3 — dim_supplier
    sup_map = build_dim_supplier(conn)
    n = conn.execute("SELECT COUNT(*) FROM dim_supplier").fetchone()[0]
    report("dim_supplier", n)

    conn.commit()

    # 4 — fact_sales
    n = migrate_fact_sales(conn, src, pid_map)
    report("fact_sales", n)

    # 5 — fact_invoice
    n = migrate_fact_invoice(conn, src, pid_map, sup_map)
    report("fact_invoice", n)

    # 6 — fact_stock
    n = migrate_fact_stock(conn, src, pid_map)
    report("fact_stock", n)

    # 7 — ref_item_price
    n = migrate_ref_item_price(conn, src, pid_map)
    report("ref_item_price", n)

    # 8 — ref_invoice_mapping
    n = migrate_ref_invoice_mapping(conn, pid_map, sup_map)
    report("ref_invoice_mapping", n)

    conn.commit()
    src.close()

    # ── Integrity check ───────────────────────────────────────────────────────
    print(f"\n  {SEP}")
    print("  Integrity checks …\n")

    # Orphan check: fact_sales rows with no matching dim_date
    orphan_dates = conn.execute(
        """SELECT COUNT(*) FROM fact_sales s
           LEFT JOIN dim_date d ON s.date_id = d.date_id
           WHERE d.date_id IS NULL"""
    ).fetchone()[0]
    print(f"    fact_sales orphan dates:     {orphan_dates}")

    orphan_prod = conn.execute(
        """SELECT COUNT(*) FROM fact_sales s
           LEFT JOIN dim_product p ON s.product_id = p.product_id
           WHERE p.product_id IS NULL"""
    ).fetchone()[0]
    print(f"    fact_sales orphan products:  {orphan_prod}")

    sub_dept_coverage = conn.execute(
        """SELECT ROUND(100.0 * SUM(CASE WHEN sub_dept IS NOT NULL THEN 1 ELSE 0 END)
                  / COUNT(*), 1)
           FROM dim_product"""
    ).fetchone()[0]
    print(f"    dim_product sub_dept cover:  {sub_dept_coverage}%")

    conn.close()

    # ── Copy to mount ─────────────────────────────────────────────────────────
    print(f"\n  Copying to {DB_DEST.name} …")
    shutil.copy2(DB_TEMP, DB_DEST)
    DB_TEMP.unlink(missing_ok=True)

    size_kb = DB_DEST.stat().st_size / 1024
    print(f"  Done.  {DB_DEST.name}  ({size_kb:,.0f} KB)")
    print(f"\n  {SEP}\n")


if __name__ == "__main__":
    main()
