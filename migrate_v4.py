"""
migrate_v4.py - Foodland Wudinna
Complete rebuild of foodland_data.db from source CSV/XLSX files.
Schema version: v4. Safe to re-run.

Usage:
    python migrate_v4.py
"""

import re, shutil, sqlite3, struct, tempfile, warnings
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

ROOT    = Path(__file__).parent
DB_DEST = ROOT / "foodland_data.db"

RAW          = ROOT / "01_data" / "raw"
ARCHIVE      = RAW  / "archive"
MARKDOWN_DIR = RAW  / "Markdown"
DUMP_DIR     = RAW  / "Dump"
OPERATIONAL  = ROOT / "01_data" / "operational"
REF_DIR      = ROOT / "01_data" / "reference"
WASTE_DIR    = ROOT / "05_waste"

HOLIDAYS_CSV   = REF_DIR / "sa_holidays_prophet.csv"
MAPPING_CSV    = REF_DIR / "invoice_item_mapping.csv"
ITEM_PRICE_CSV = REF_DIR / "item_price.csv"
PRICE_HIST_CSV = REF_DIR / "price_history.csv"

VALID_DEPARTMENTS = {"FRUIT & VEG", "DAIRY", "MEAT"}
SCHEMA_VERSION    = "v4"
SEP = "-" * 60


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().upper()

def clean_apn(val):
    if val is None: return None
    if isinstance(val, float) and pd.isna(val): return None
    s = str(val).strip()
    if s in ("", "0", "None", "nan"): return None
    try: return str(int(float(s)))
    except: return s if s else None

def safe_float(val):
    if val is None: return None
    if isinstance(val, float) and pd.isna(val): return None
    try: return float(val)
    except: return None

def report(label, n):
    print(f"  {label:<42}  {n:>8,}")


def _verify_db(path):
    with open(path, "rb") as f:
        header = f.read(32)
    if len(header) < 32:
        raise RuntimeError(f"DB too small: {path.stat().st_size} bytes")
    if header[:16] != b"SQLite format 3\x00":
        raise RuntimeError(f"Not a valid SQLite file: {path}")
    page_size = struct.unpack(">H", header[16:18])[0]
    hdr_pages = struct.unpack(">I", header[28:32])[0]
    if page_size == 0 or hdr_pages == 0: return
    actual = path.stat().st_size // page_size
    if actual < hdr_pages * 0.98:
        raise RuntimeError(
            f"Truncation detected: header={hdr_pages} pages, actual={actual}. "
            f"/tmp copy preserved."
        )


def _chunked_copy(src: Path, dst: Path, chunk_mb: int = 8) -> None:
    """Copy src to dst in fixed-size chunks with fsync after each.

    shutil.copy2() is unreliable on the virtiofs/OneDrive mount for files
    larger than ~10 MB — the OS write buffer gets flushed mid-stream and
    OneDrive can truncate the file.  Writing in explicit chunks with fsync
    after each ensures every byte lands before the next chunk starts.
    """
    import os
    chunk = chunk_mb * 1024 * 1024
    total = src.stat().st_size
    with open(src, "rb") as r, open(dst, "wb") as w:
        written = 0
        while written < total:
            data = r.read(chunk)
            if not data:
                break
            w.write(data)
            w.flush()
            os.fsync(w.fileno())
            written += len(data)
    if dst.stat().st_size != total:
        raise RuntimeError(
            f"Chunked copy incomplete: wrote {dst.stat().st_size} of {total} bytes"
        )


DDL = """
PRAGMA journal_mode=DELETE;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS dim_product (
    product_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    sub_dept    TEXT,
    department  TEXT,
    sell_unit   TEXT    DEFAULT 'each',
    apn         TEXT,
    active      INTEGER DEFAULT 1,
    created_at  TEXT    DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_id      TEXT PRIMARY KEY,
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    month_name   TEXT    NOT NULL,
    week_num     INTEGER NOT NULL,
    day_of_week  INTEGER NOT NULL,
    day_name     TEXT    NOT NULL,
    is_weekend   INTEGER NOT NULL,
    is_holiday   INTEGER DEFAULT 0,
    holiday_name TEXT,
    is_trading   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_supplier (
    supplier_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL COLLATE NOCASE,
    delivery_days TEXT
);

CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id       TEXT    NOT NULL REFERENCES dim_date(date_id),
    product_id    INTEGER NOT NULL REFERENCES dim_product(product_id),
    department    TEXT,
    sub_dept      TEXT,
    sales_inc_gst REAL,
    cost_ex_gst   REAL,
    cost_inc_gst  REAL,
    lines         INTEGER,
    quantity      REAL,
    sales_ex_gst  REAL,
    date_imported TEXT,
    source_file   TEXT,
    UNIQUE(date_id, product_id)
);

CREATE TABLE IF NOT EXISTS fact_invoice (
    invoice_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id              TEXT    NOT NULL REFERENCES dim_date(date_id),
    invoice_no           TEXT    NOT NULL,
    product_id           INTEGER NOT NULL REFERENCES dim_product(product_id),
    supplier_id          INTEGER REFERENCES dim_supplier(supplier_id),
    cost_per_unit        REAL,
    sell_price           REAL,
    gp_pct               REAL,
    source               TEXT,
    invoice_product_name TEXT,
    product_name         TEXT,
    UNIQUE(invoice_no, product_id)
);

CREATE TABLE IF NOT EXISTS fact_stock (
    stock_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id    TEXT    NOT NULL REFERENCES dim_date(date_id),
    product_id INTEGER NOT NULL REFERENCES dim_product(product_id),
    stock      REAL,
    stock_unit TEXT,
    stock_type TEXT    DEFAULT 'system',
    source     TEXT,
    UNIQUE(product_id, date_id)
);

CREATE TABLE IF NOT EXISTS fact_dump (
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
    source_file   TEXT
);

CREATE TABLE IF NOT EXISTS fact_markdown (
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
    source_file     TEXT
);

CREATE TABLE IF NOT EXISTS fact_waste_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id     TEXT    REFERENCES dim_date(date_id),
    product_id  INTEGER REFERENCES dim_product(product_id),
    item_name   TEXT,
    qty         REAL,
    unit        TEXT,
    sell_price  REAL,
    action      TEXT,
    new_price   REAL,
    reason      TEXT,
    costed_cost REAL,
    cost_source TEXT,
    source_file TEXT
);

CREATE TABLE IF NOT EXISTS ref_item_price (
    product_id   INTEGER PRIMARY KEY REFERENCES dim_product(product_id),
    sell_price   REAL,
    cost_price   REAL,
    price_source TEXT    DEFAULT 'manual',
    updated_at   TEXT    DEFAULT (date('now'))
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

CREATE INDEX IF NOT EXISTS idx_fact_sales_date       ON fact_sales(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_sales_product    ON fact_sales(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_sales_dept_date  ON fact_sales(department, date_id);
CREATE INDEX IF NOT EXISTS idx_fact_markdown_date    ON fact_markdown(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_markdown_product ON fact_markdown(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_dump_date        ON fact_dump(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_dump_product     ON fact_dump(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_waste_date       ON fact_waste_log(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_invoice_product  ON fact_invoice(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_invoice_date     ON fact_invoice(date_id);
CREATE INDEX IF NOT EXISTS idx_dim_product_name      ON dim_product(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_dim_product_apn       ON dim_product(apn);
"""

VIEWS = """
DROP VIEW IF EXISTS v_sales;
CREATE VIEW v_sales AS
SELECT s.date_id        AS date,
       p.name,
       COALESCE(s.sub_dept, p.sub_dept) AS sub_dept,
       p.department,
       p.apn,
       s.sales_ex_gst,
       s.sales_inc_gst,
       s.cost_ex_gst,
       s.cost_inc_gst,
       s.lines,
       s.quantity,
       s.date_imported,
       s.source_file
FROM fact_sales s JOIN dim_product p ON s.product_id = p.product_id;

DROP VIEW IF EXISTS v_item_price;
CREATE VIEW v_item_price AS
SELECT p.name, p.department, p.sub_dept,
       r.sell_price, r.cost_price, r.price_source, r.updated_at
FROM ref_item_price r JOIN dim_product p ON r.product_id = p.product_id;

DROP VIEW IF EXISTS v_price_history;
CREATE VIEW v_price_history AS
SELECT i.date_id AS date, i.invoice_no, p.name AS pos_name,
       i.cost_per_unit, i.sell_price, i.gp_pct, i.source
FROM fact_invoice i JOIN dim_product p ON i.product_id = p.product_id
ORDER BY i.date_id;

DROP VIEW IF EXISTS v_stock_on_hand;
CREATE VIEW v_stock_on_hand AS
SELECT p.name, s.stock, s.stock_unit, s.stock_type, s.source, s.date_id AS date_recorded
FROM fact_stock s JOIN dim_product p ON s.product_id = p.product_id;

DROP VIEW IF EXISTS v_item_reference;
CREATE VIEW v_item_reference AS
SELECT apn AS plu, name FROM dim_product WHERE apn IS NOT NULL;

DROP VIEW IF EXISTS v_waste_summary;
CREATE VIEW v_waste_summary AS
SELECT 'dump' AS waste_type, fd.date_id AS event_date, fd.product_id,
       COALESCE(dp.name, fd.description) AS description,
       COALESCE(NULLIF(dp.sub_dept,'None'),'Unknown') AS sub_dept,
       COALESCE(dp.department, fd.department) AS department,
       fd.qty, fd.total_cost_ex AS waste_cost,
       NULL AS discount_given, NULL AS realised_profit,
       fd.reason, fd.source_file
FROM fact_dump fd LEFT JOIN dim_product dp ON fd.product_id = dp.product_id
UNION ALL
SELECT 'markdown', fm.date_id, fm.product_id,
       COALESCE(dp.name, fm.description),
       COALESCE(NULLIF(dp.sub_dept,'None'), NULLIF(fm.sub_dept,'None'), 'Unknown'),
       COALESCE(dp.department, fm.department),
       fm.lines,
       CASE WHEN fm.realised_profit < 0 THEN ABS(fm.realised_profit) ELSE 0 END,
       fm.discount_given, fm.realised_profit, NULL, fm.source_file
FROM fact_markdown fm LEFT JOIN dim_product dp ON fm.product_id = dp.product_id
UNION ALL
SELECT CASE wl.action WHEN 'Binned' THEN 'dump' WHEN 'Reduced' THEN 'markdown' ELSE 'store_use' END,
       wl.date_id, wl.product_id,
       COALESCE(dp.name, wl.item_name),
       COALESCE(NULLIF(dp.sub_dept,'None'), 'Unknown'),
       COALESCE(dp.department, 'FRUIT & VEG'),
       wl.qty, wl.costed_cost,
       CASE WHEN wl.action = 'Reduced' THEN wl.costed_cost END,
       NULL, wl.reason, wl.source_file
FROM fact_waste_log wl LEFT JOIN dim_product dp ON wl.product_id = dp.product_id;
"""


def build_dim_date(conn):
    holidays = {}
    if HOLIDAYS_CSV.exists():
        hdf = pd.read_csv(HOLIDAYS_CSV)
        for _, row in hdf.iterrows():
            holidays[str(row["ds"])[:10]] = str(row["holiday"])

    MONTH_NAMES = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    DAY_NAMES   = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    rows, d = [], date(2024, 1, 1)
    while d <= date(2029, 12, 31):
        ds = d.isoformat()
        dow = d.weekday()
        is_hol = 1 if ds in holidays else 0
        rows.append((ds, d.year, d.month, MONTH_NAMES[d.month-1],
                     d.isocalendar()[1], dow, DAY_NAMES[dow],
                     1 if dow >= 5 else 0, is_hol, holidays.get(ds),
                     1 if dow <= 5 and not is_hol else 0))
        d += timedelta(days=1)
    conn.executemany(
        "INSERT OR IGNORE INTO dim_date VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def build_dim_supplier(conn):
    conn.execute("INSERT OR IGNORE INTO dim_supplier (name, delivery_days) VALUES (?,?)",
                 ("FRESHLINK", "TUE,FRI"))
    return {n.upper(): sid for n, sid in conn.execute(
        "SELECT name, supplier_id FROM dim_supplier")}


def _collect_all_sales_csvs():
    candidates = [
        RAW / "sales_fruit_2025.csv", RAW / "sales_fruit_2026.csv",
        RAW / "FV_sales_28.04.26.csv",
        RAW / "dairy_sales_2025_1.csv", RAW / "dairy_sales_2025_2.csv",
        RAW / "sales_meat_2025.csv",
    ]
    for p in ARCHIVE.glob("*.csv"):
        candidates.append(p)
    return [p for p in candidates if p.exists()]


def build_dim_product(conn):
    frames = []
    sell_unit_map = {}
    if MAPPING_CSV.exists():
        mdf = pd.read_csv(MAPPING_CSV, encoding="utf-8-sig")
        for _, row in mdf.dropna(subset=["pos_name"]).iterrows():
            pn = norm(str(row["pos_name"]))
            if pn and pd.notna(row.get("sell_unit")):
                sell_unit_map[pn] = str(row["sell_unit"]).strip().lower()

    needed = {"Name", "Sub Department Name", "Department Name", "APN",
              "Sales Date", "Date"}
    for csv_path in _collect_all_sales_csvs():
        try:
            df = pd.read_csv(csv_path, low_memory=False, encoding="utf-8-sig",
                             usecols=lambda c: c.strip() in needed)
            df.columns = df.columns.str.strip()
            if "Sales Date" in df.columns:
                df = df.rename(columns={"Sales Date": "Date"})
            if "Name" in df.columns:
                frames.append(df)
        except Exception as e:
            print(f"    [WARN] dim_product scan: {csv_path.name}: {e}")

    if not frames:
        return {}

    combined = pd.concat(frames, ignore_index=True)
    combined["Name"] = combined["Name"].astype(str).apply(norm)
    combined = combined[combined["Name"].str.len() > 0]

    dept_map, sub_dept_map, apn_map_prod = {}, {}, {}

    if "Department Name" in combined.columns:
        dept_df = (combined[combined["Department Name"].isin(VALID_DEPARTMENTS)]
                   [["Name","Department Name"]].drop_duplicates("Name"))
        dept_map = dict(zip(dept_df["Name"], dept_df["Department Name"]))

    if "Sub Department Name" in combined.columns:
        mask = (combined["Sub Department Name"].notna() &
                ~combined["Sub Department Name"].astype(str).str.lower().isin({"nan","none",""}))
        sd_df = combined[mask][["Name","Sub Department Name"]].drop_duplicates("Name")
        sub_dept_map = dict(zip(sd_df["Name"],
                                sd_df["Sub Department Name"].astype(str).str.strip()))

    if "APN" in combined.columns:
        apn_df = combined[combined["APN"].notna()][["Name","APN"]].drop_duplicates("Name")
        for nm, apn_raw in zip(apn_df["Name"], apn_df["APN"]):
            apn = clean_apn(apn_raw)
            if apn:
                apn_map_prod[nm] = apn

    names = set(dept_map) | set(sub_dept_map) | set(sell_unit_map) | set(apn_map_prod)
    rows = [(nm, sub_dept_map.get(nm), dept_map.get(nm),
             sell_unit_map.get(nm, "each"), apn_map_prod.get(nm))
            for nm in sorted(names)]
    conn.executemany(
        "INSERT OR IGNORE INTO dim_product (name, sub_dept, department, sell_unit, apn) "
        "VALUES (?,?,?,?,?)", rows)
    return {n: pid for n, pid in conn.execute(
        "SELECT name, product_id FROM dim_product")}


def load_invoice_mapping(conn, pid_map, sup_map):
    if not MAPPING_CSV.exists(): return 0
    df = pd.read_csv(MAPPING_CSV, encoding="utf-8-sig")
    rows = []
    for _, r in df.iterrows():
        inv_desc = str(r.get("invoice_description","")).strip()
        pos_name = norm(str(r.get("pos_name",""))) if pd.notna(r.get("pos_name")) else None
        pid = pid_map.get(pos_name) if pos_name else None
        sup = norm(str(r.get("supplier",""))) if pd.notna(r.get("supplier")) else None
        sid = sup_map.get(sup) if sup else None
        units = safe_float(r.get("units_per_invoice"))
        su    = str(r["sell_unit"]).strip() if pd.notna(r.get("sell_unit")) else None
        ver   = 1 if str(r.get("verified","false")).lower() in ("true","1") else 0
        notes = str(r["notes"]).strip() if pd.notna(r.get("notes")) else None
        rows.append((inv_desc, pid, units, su, sid, ver, notes))
    conn.executemany(
        "INSERT OR IGNORE INTO ref_invoice_mapping "
        "(invoice_description,product_id,units_per_invoice,sell_unit,supplier_id,verified,notes) "
        "VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_fact_sales(conn, pid_map):
    csv_files      = _collect_all_sales_csvs()
    total_inserted = 0
    total_skipped  = 0
    imported_at    = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    COL_RENAME = {
        "Sales Date":"Date","Department Name":"department",
        "Sub Department Name":"sub_dept","APN":"apn_raw",
        "Sales Inc GST":"sales_inc_gst","Cost Ex GST":"cost_ex_gst",
        "Cost Inc GST":"cost_inc_gst","Lines":"lines",
        "Quantity":"quantity","Sales Ex GST":"sales_ex_gst",
    }

    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path, low_memory=False, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            df = df.rename(columns={k:v for k,v in COL_RENAME.items() if k in df.columns})
            if "Date" not in df.columns: continue

            df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df["Name"] = df["Name"].astype(str).apply(norm)
            df = df.dropna(subset=["Date","Name"])
            df = df[df["Name"].str.len() > 0]
            if "department" in df.columns:
                df = df[df["department"].isin(VALID_DEPARTMENTS)]

            # Register new products
            new_names = set(df["Name"]) - set(pid_map)
            if new_names:
                sd_col   = "sub_dept"   if "sub_dept"   in df.columns else None
                dept_col = "department" if "department" in df.columns else None
                for nm in new_names:
                    mask = df["Name"] == nm
                    sd   = df.loc[mask, sd_col].dropna().iloc[0]   if sd_col   and mask.any() else None
                    dept = df.loc[mask, dept_col].dropna().iloc[0] if dept_col and mask.any() else None
                    sd   = str(sd).strip()   if sd   and str(sd).lower()   not in ("nan","none","") else None
                    dept = str(dept).strip() if dept and str(dept).lower() not in ("nan","none","") else None
                    apn_raw = df.loc[mask,"apn_raw"].dropna().iloc[0] if "apn_raw" in df.columns and mask.any() else None
                    conn.execute(
                        "INSERT OR IGNORE INTO dim_product (name,sub_dept,department,sell_unit,apn) VALUES (?,?,?,?,?)",
                        (nm, sd, dept, "each", clean_apn(apn_raw)))
                for nm, pid in conn.execute(
                    f"SELECT name,product_id FROM dim_product WHERE name IN ({','.join('?'*len(new_names))})",
                    list(new_names)):
                    pid_map[nm] = pid

            df["product_id"] = df["Name"].map(pid_map)
            df = df.dropna(subset=["product_id"])
            df["product_id"] = df["product_id"].astype(int)

            if "sub_dept" in df.columns:
                bad = df["sub_dept"].isna() | df["sub_dept"].astype(str).str.lower().isin({"nan","none",""})
                df.loc[bad, "sub_dept"] = None
            else:
                df["sub_dept"] = None

            if "department" not in df.columns:
                df["department"] = None

            for col in ["sales_inc_gst","cost_ex_gst","cost_inc_gst","lines","quantity","sales_ex_gst"]:
                if col not in df.columns:
                    df[col] = None
                else:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df["date_imported"] = imported_at
            df["source_file"]   = csv_path.name

            cols = ["Date","product_id","department","sub_dept",
                    "sales_inc_gst","cost_ex_gst","cost_inc_gst",
                    "lines","quantity","sales_ex_gst",
                    "date_imported","source_file"]
            rows = list(df[cols].itertuples(index=False, name=None))

            cur = conn.executemany(
                "INSERT OR IGNORE INTO fact_sales "
                "(date_id,product_id,department,sub_dept,"
                "sales_inc_gst,cost_ex_gst,cost_inc_gst,"
                "lines,quantity,sales_ex_gst,"
                "date_imported,source_file) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                rows)
            ins = cur.rowcount if cur.rowcount >= 0 else len(rows)
            total_inserted += ins
            total_skipped  += len(rows) - ins
            conn.commit()

        except Exception as e:
            print(f"    [WARN] fact_sales: {csv_path.name}: {e}")

    deleted = conn.execute(
        "DELETE FROM fact_sales "
        "WHERE date_id IN (SELECT date_id FROM dim_date WHERE is_trading = 0)").rowcount
    if deleted:
        print(f"    fact_sales: removed {deleted} rows on non-trading days")

    return total_inserted, total_skipped


def load_fact_invoice(conn, pid_map, sup_map):
    if not PRICE_HIST_CSV.exists(): return 0
    df = pd.read_csv(PRICE_HIST_CSV, encoding="utf-8-sig")
    rows = []
    for _, r in df.iterrows():
        pos_name = norm(str(r.get("pos_name","")))
        pid = pid_map.get(pos_name)
        if pid is None: continue
        dt = str(r.get("date","")).strip()
        if "/" in dt:
            parts = dt.split("/")
            dt = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        source = str(r.get("source","")).strip()
        sid = None
        for sn, si in sup_map.items():
            if sn.lower() in source.lower():
                sid = si; break
        rows.append((dt[:10], str(r.get("invoice_no","")).strip(), pid, sid,
                     safe_float(r.get("cost_per_unit")), safe_float(r.get("sell_price")),
                     safe_float(r.get("gp_pct")), source, None, pos_name))
    cur = conn.executemany(
        "INSERT OR IGNORE INTO fact_invoice "
        "(date_id,invoice_no,product_id,supplier_id,cost_per_unit,sell_price,"
        "gp_pct,source,invoice_product_name,product_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows)
    return cur.rowcount if cur.rowcount >= 0 else len(rows)


def load_fact_stock(conn, pid_map):
    soh_files = sorted(
        list(OPERATIONAL.glob("SOH_*.xlsx")) + list(OPERATIONAL.glob("Stock_*.xlsx")))
    total = 0
    for soh_path in soh_files:
        fname = soh_path.stem
        snap_date = None
        m = re.search(r"(\d{2})(\d{2})(\d{4})", fname)
        if m:
            snap_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        else:
            m = re.search(r"(\d{1,2})\.(\d{2})\.(\d{2,4})", fname)
            if m:
                y = m.group(3)
                if len(y) == 2: y = "20" + y
                snap_date = f"{y}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
        if not snap_date:
            print(f"    [WARN] fact_stock: cannot parse date from {soh_path.name}")
            continue
        try:
            try:
                raw = pd.read_excel(soh_path, sheet_name="Page 1", header=5)
            except Exception:
                raw = pd.read_excel(soh_path, header=5)
            raw.columns = [re.sub(r"\s+"," ",str(c)).strip() for c in raw.columns]
            raw = raw.rename(columns={"Description":"Name","Stock On Hand":"Stock"})
            if "Name" not in raw.columns or "Stock" not in raw.columns:
                continue
            raw["Name"]  = raw["Name"].apply(lambda x: norm(str(x)))
            raw["Stock"] = pd.to_numeric(raw["Stock"], errors="coerce")
            raw = raw[raw["Name"].str.len() > 2].dropna(subset=["Stock"])
            params = []
            for _, row in raw.iterrows():
                pid = pid_map.get(row["Name"])
                if pid:
                    params.append((snap_date, pid, float(row["Stock"]), "each", "system", soh_path.name))
            if params:
                cur = conn.executemany(
                    "INSERT OR IGNORE INTO fact_stock "
                    "(date_id,product_id,stock,stock_unit,stock_type,source) VALUES (?,?,?,?,?,?)",
                    params)
                total += cur.rowcount if cur.rowcount >= 0 else len(params)
        except Exception as e:
            print(f"    [WARN] fact_stock: {soh_path.name}: {e}")
    return total


def load_ref_item_price(conn, pid_map):
    if not ITEM_PRICE_CSV.exists(): return 0
    df = pd.read_csv(ITEM_PRICE_CSV, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    col_map = {}
    for c in df.columns:
        lc = c.lower()
        if "sell price" in lc and "manual" in lc: col_map[c] = "sell_price_manual"
        elif "sell price" in lc: col_map[c] = "sell_price"
        elif "cost price" in lc: col_map[c] = "cost_price"
        elif lc == "name": col_map[c] = "name"
    df = df.rename(columns=col_map)
    rows = []
    for _, r in df.iterrows():
        nm  = norm(str(r.get("name","")))
        pid = pid_map.get(nm)
        if pid is None:
            conn.execute(
                "INSERT OR IGNORE INTO dim_product (name, sell_unit) VALUES (?,?)",
                (nm, "each"))
            pid = conn.execute(
                "SELECT product_id FROM dim_product WHERE name=?", (nm,)).fetchone()[0]
            pid_map[nm] = pid
        sp_m = safe_float(r.get("sell_price_manual"))
        sp   = safe_float(r.get("sell_price"))
        cp   = safe_float(r.get("cost_price"))
        psrc = "invoice" if (sp_m and sp and abs(sp_m - sp) > 0.01) else "manual"
        rows.append((pid, sp, cp, psrc))
    cur = conn.executemany(
        "INSERT OR REPLACE INTO ref_item_price (product_id,sell_price,cost_price,price_source) "
        "VALUES (?,?,?,?)", rows)
    return cur.rowcount if cur.rowcount >= 0 else len(rows)


def load_fact_dump(conn, pid_map):
    dump_files = sorted(DUMP_DIR.glob("*.xlsx")) if DUMP_DIR.exists() else []
    if not dump_files: return 0
    total = 0
    for dump_path in dump_files:
        try:
            raw = pd.read_excel(dump_path, header=None)
        except Exception as e:
            print(f"    [WARN] fact_dump: {dump_path.name}: {e}"); continue
        current_dept = None
        rows = []
        apn_lookup = {a: pid for a, pid in conn.execute(
            "SELECT apn, product_id FROM dim_product WHERE apn IS NOT NULL")}
        for _, row in raw.iterrows():
            val0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            if val0 in VALID_DEPARTMENTS:
                current_dept = val0; continue
            if val0 == "Foodland Wudinna" and current_dept:
                date_raw = row.iloc[2]
                if pd.isna(date_raw): continue
                try:
                    date_id = pd.to_datetime(str(date_raw), dayfirst=True).strftime("%Y-%m-%d")
                except: continue
                apn  = clean_apn(row.iloc[3])
                desc = str(row.iloc[7]).strip() if pd.notna(row.iloc[7]) else None
                pid  = apn_lookup.get(apn) if apn else None
                if pid is None and desc:
                    pid = pid_map.get(norm(desc))
                rows.append((date_id, pid, current_dept, apn, desc,
                             safe_float(row.iloc[12]), safe_float(row.iloc[13]),
                             safe_float(row.iloc[15]),
                             str(row.iloc[18]).strip() if pd.notna(row.iloc[18]) else None,
                             safe_float(row.iloc[20]), safe_float(row.iloc[21]),
                             dump_path.name))
        conn.execute("DELETE FROM fact_dump WHERE source_file=?", (dump_path.name,))
        if rows:
            conn.executemany(
                "INSERT INTO fact_dump "
                "(date_id,product_id,department,apn,description,"
                "qty,unit_cost_ex,unit_sell_ex,reason,total_cost_ex,total_sell_ex,source_file) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            total += len(rows)
    return total


def load_fact_markdown(conn, pid_map):
    md_files = sorted(MARKDOWN_DIR.glob("*.csv")) if MARKDOWN_DIR.exists() else []
    if not md_files: return 0
    apn_lookup = {a: pid for a, pid in conn.execute(
        "SELECT apn, product_id FROM dim_product WHERE apn IS NOT NULL")}
    total = 0
    for md_path in md_files:
        try:
            df = pd.read_csv(md_path, low_memory=False, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            if "Sales Date" in df.columns:
                df = df.rename(columns={"Sales Date":"Date"})
            if "Date" not in df.columns: continue
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df = df.dropna(subset=["Date","Name","Department Name"])
            df = df[df["Department Name"].isin(VALID_DEPARTMENTS)]
            conn.execute("DELETE FROM fact_markdown WHERE source_file=?", (md_path.name,))
            rows = []
            for _, r in df.iterrows():
                apn  = clean_apn(r.get("APN"))
                desc = norm(str(r.get("Name","")))
                pid  = apn_lookup.get(apn) if apn else None
                if pid is None: pid = pid_map.get(desc)
                dept = str(r.get("Department Name","")).strip()
                sd   = str(r.get("Sub Department Name","")).strip()
                if not sd or sd.lower() in ("nan","none",""): sd = None
                ts = safe_float(r.get("Sales Ex GST"))
                tc = safe_float(r.get("Cost Ex GST"))
                realised = round(ts - tc, 4) if (ts is not None and tc is not None) else None
                rows.append((str(r["Date"])[:10], pid, dept, apn, desc, sd,
                             safe_float(r.get("Lines")), safe_float(r.get("Potential Sales")),
                             ts, tc, safe_float(r.get("Discount")), realised, md_path.name))
            conn.executemany(
                "INSERT INTO fact_markdown "
                "(date_id,product_id,department,apn,description,sub_dept,"
                "lines,potential_sell,total_sell,total_cost,discount_given,realised_profit,source_file) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            total += len(rows)
        except Exception as e:
            print(f"    [WARN] fact_markdown: {md_path.name}: {e}")
    return total


def load_fact_waste_log(conn, pid_map):
    waste_log_path = WASTE_DIR / "FruitVeg_Waste_Log_v2.xlsx"
    if not waste_log_path.exists(): return 0
    try:
        df = pd.read_excel(waste_log_path, sheet_name="Weekly Entry", header=2)
    except Exception as e:
        print(f"    [WARN] fact_waste_log: {e}"); return 0
    df = df[pd.to_datetime(df["Date"], errors="coerce").notna()].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Item Name"].notna()]
    cost_map = {pid: cp for pid, cp in conn.execute(
        "SELECT product_id, cost_price FROM ref_item_price WHERE cost_price IS NOT NULL")}
    conn.execute("DELETE FROM fact_waste_log WHERE source_file=?", (waste_log_path.name,))
    rows = []
    for _, row in df.iterrows():
        item_name = str(row["Item Name"]).strip()
        pid  = pid_map.get(norm(item_name))
        qty  = safe_float(row.get("Qty"))
        cp   = cost_map.get(pid) if pid else None
        ac   = round(qty * cp, 4) if (qty and cp) else None
        lc   = safe_float(row.get("Waste/Markdown Cost $"))
        rows.append((row["Date"].strftime("%Y-%m-%d"), pid, item_name,
                     qty, str(row.get("Unit")).strip() if pd.notna(row.get("Unit")) else None,
                     safe_float(row.get("Price")),
                     str(row.get("Action")).strip() if pd.notna(row.get("Action")) else None,
                     safe_float(row.get("New Price")),
                     str(row.get("Reason")).strip() if pd.notna(row.get("Reason")) else None,
                     ac if ac is not None else lc,
                     "confirmed" if ac is not None else "estimated",
                     waste_log_path.name))
    if rows:
        conn.executemany(
            "INSERT INTO fact_waste_log "
            "(date_id,product_id,item_name,qty,unit,sell_price,action,"
            "new_price,reason,costed_cost,cost_source,source_file) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def integrity_checks(conn):
    print(f"\n  {SEP}")
    print("  Integrity checks\n")
    checks = [
        ("fact_sales orphan date_id",
         "SELECT COUNT(*) FROM fact_sales s LEFT JOIN dim_date d ON s.date_id=d.date_id WHERE d.date_id IS NULL"),
        ("fact_sales orphan product_id",
         "SELECT COUNT(*) FROM fact_sales s LEFT JOIN dim_product p ON s.product_id=p.product_id WHERE p.product_id IS NULL"),
        ("fact_markdown orphan date_id",
         "SELECT COUNT(*) FROM fact_markdown m LEFT JOIN dim_date d ON m.date_id=d.date_id WHERE d.date_id IS NULL"),
        ("fact_dump orphan date_id",
         "SELECT COUNT(*) FROM fact_dump fd LEFT JOIN dim_date d ON fd.date_id=d.date_id WHERE d.date_id IS NULL"),
        ("dim_product NULL department",
         "SELECT COUNT(*) FROM dim_product WHERE department IS NULL"),
        ("dim_product NULL sub_dept",
         "SELECT COUNT(*) FROM dim_product WHERE sub_dept IS NULL"),
        ("ref_item_price NULL sell_price",
         "SELECT COUNT(*) FROM ref_item_price WHERE sell_price IS NULL"),
    ]
    for label, sql in checks:
        n = conn.execute(sql).fetchone()[0]
        print(f"    {'OK' if n==0 else 'WARN'}  {label:<42}  {n:>6,}")


def main():
    print(f"\n  Foodland Wudinna -- Database Migration v4")
    print(f"  Full rebuild from source files")
    print(f"  {SEP}\n")

    db_tmp = Path(tempfile.mktemp(suffix=".db", prefix="foodland_v4_"))
    try:
        conn = sqlite3.connect(db_tmp)
        conn.executescript(DDL)
        conn.commit()
        print("  Schema created (tables + 12 indexes).\n")

        print(f"  {SEP}")
        print(f"  {'Step':<42}  {'Rows':>8}")
        print(f"  {SEP}")

        n = build_dim_date(conn); conn.commit()
        report("dim_date (2024-2029)", n)

        sup_map = build_dim_supplier(conn); conn.commit()
        report("dim_supplier", len(sup_map))

        pid_map = build_dim_product(conn); conn.commit()
        report("dim_product (initial)", len(pid_map))

        n = load_invoice_mapping(conn, pid_map, sup_map); conn.commit()
        report("ref_invoice_mapping", n)

        ins, skp = load_fact_sales(conn, pid_map); conn.commit()
        pid_map = {n: pid for n, pid in conn.execute("SELECT name,product_id FROM dim_product")}
        report("fact_sales (inserted)", ins)
        report("fact_sales (skipped)", skp)

        n = load_fact_invoice(conn, pid_map, sup_map); conn.commit()
        report("fact_invoice", n)

        n = load_ref_item_price(conn, pid_map); conn.commit()
        pid_map = {nm: pid for nm, pid in conn.execute("SELECT name,product_id FROM dim_product")}
        report("ref_item_price", n)

        n = load_fact_stock(conn, pid_map); conn.commit()
        report("fact_stock", n)

        n = load_fact_dump(conn, pid_map); conn.commit()
        report("fact_dump", n)

        n = load_fact_markdown(conn, pid_map); conn.commit()
        report("fact_markdown", n)

        n = load_fact_waste_log(conn, pid_map); conn.commit()
        report("fact_waste_log", n)

        n = conn.execute("SELECT COUNT(*) FROM dim_product").fetchone()[0]
        report("dim_product (final)", n)

        conn.executescript(VIEWS); conn.commit()
        print("\n  Views rebuilt: v_sales, v_item_price, v_price_history,")
        print("                v_stock_on_hand, v_item_reference, v_waste_summary")

        sr = conn.execute("SELECT MIN(date_id),MAX(date_id),COUNT(*) FROM fact_sales").fetchone()
        print(f"\n  Sales range:  {sr[0]}  to  {sr[1]}  ({sr[2]:,} rows)")

        for dept, days, rev in conn.execute(
            "SELECT department, COUNT(DISTINCT date_id), SUM(sales_ex_gst) "
            "FROM fact_sales GROUP BY department ORDER BY SUM(sales_ex_gst) DESC"):
            print(f"    {str(dept):<20}  {days:>4} days  ${rev:,.0f}")

        integrity_checks(conn)

        conn.execute("INSERT OR REPLACE INTO _meta VALUES (?,?)", ("schema_version", SCHEMA_VERSION))
        conn.execute("INSERT OR REPLACE INTO _meta VALUES (?,?)",
                     ("built_at", pd.Timestamp.now().isoformat()))
        conn.commit()
        conn.close()

        print(f"\n  {SEP}")
        print(f"  Copying to {DB_DEST.name} (chunked write for virtiofs) ...")
        _chunked_copy(db_tmp, DB_DEST)
        _verify_db(DB_DEST)
        size_kb = DB_DEST.stat().st_size / 1024
        print(f"  Copy verified. {DB_DEST.name}  ({size_kb:,.0f} KB)")
        print(f"\n  Migration v4 complete.\n  {SEP}\n")

    except Exception:
        print(f"\n  Migration failed. /tmp copy at: {db_tmp}")
        raise
    finally:
        db_tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
