"""
import_waste.py — Import GAP POS dump and markdown exports into foodland_data.db.

Tables populated:
  fact_dump      — one row per dump transaction (full write-off)
  fact_markdown  — one row per markdown line (discounted sale, date-based)
  fact_waste_log — manual FV waste log

Usage:
  python import_waste.py
  python import_waste.py --dump "path/to/Dump.xlsx"
  python import_waste.py --markdown-csv "path/to/MD_YTD_28.04.26.csv"

The new markdown source is a CSV with individual transaction dates (Sales Date).
The old Excel-based period-aggregate format is no longer the primary source.

The script is idempotent: existing rows for the same source_file are deleted and
reloaded, so re-running after receiving a fresh export is safe.

Schema created automatically if tables do not exist.
"""

import argparse
import re
import sqlite3
import shutil
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DB   = ROOT / "foodland_data.db"

DUMP_DEFAULT         = ROOT / "01_data/raw/Dump/Dump Stock Report (3).xlsx"
MARKDOWN_CSV_DEFAULT = ROOT / "01_data/raw/MD_YTD_28.04.26.csv"
WASTE_LOG_DEFAULT    = ROOT / "05_waste/FruitVeg_Waste_Log_v2.xlsx"

DEPARTMENTS = {"DAIRY", "MEAT", "FRUIT & VEG"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def norm_apn(val) -> str | None:
    """Normalise an APN/barcode to a plain integer string (no decimal point)."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        return None


def _read_conn() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB}?immutable=1", uri=True)


def _write_conn_ctx():
    """Copy DB to /tmp, yield connection, copy back on success."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        tmp = Path(tempfile.mktemp(suffix=".db", prefix="foodland_waste_"))
        try:
            shutil.copy2(DB, tmp)
            conn = sqlite3.connect(tmp)
            conn.execute("PRAGMA journal_mode=DELETE")
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


# ── DDL ───────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS fact_waste_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id      TEXT,
    product_id   INTEGER,
    item_name    TEXT,
    qty          REAL,
    unit         TEXT,
    sell_price   REAL,
    action       TEXT,
    new_price    REAL,
    reason       TEXT,
    costed_cost  REAL,
    cost_source  TEXT,
    source_file  TEXT
);

CREATE TABLE IF NOT EXISTS fact_dump (
    dump_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id       TEXT,           -- ISO date of the dump event (FK dim_date)
    product_id    INTEGER,        -- FK dim_product (NULL if unmatched)
    department    TEXT,
    apn           TEXT,
    item_no       TEXT,
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
    date_id         TEXT    NOT NULL,   -- YYYY-MM-DD (individual transaction date)
    product_id      INTEGER,            -- FK dim_product (NULL if unmatched)
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

CREATE VIEW IF NOT EXISTS v_waste_summary AS
-- Combined dump + markdown waste per product, all departments
SELECT
    'dump'              AS waste_type,
    fd.date_id          AS event_date,
    NULL                AS period_start,
    NULL                AS period_end,
    fd.product_id,
    dp.name             AS description,
    dp.sub_dept,
    fd.department,
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
    NULL                AS event_date,
    fm.period_start,
    fm.period_end,
    fm.product_id,
    dp.name             AS description,
    dp.sub_dept,
    fm.department,
    fm.qty,
    -- markdown "waste cost" = revenue lost below cost (realised_profit clipped at 0)
    CASE WHEN fm.realised_profit < 0 THEN ABS(fm.realised_profit) ELSE 0 END AS waste_cost,
    fm.discount_given,
    fm.realised_profit,
    NULL                AS reason,
    fm.source_file
FROM fact_markdown fm
LEFT JOIN dim_product dp ON fm.product_id = dp.product_id;
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


# ── Product lookup ────────────────────────────────────────────────────────────

def build_apn_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {normalised_apn: product_id} from dim_product.apn."""
    rows = conn.execute("SELECT apn, product_id FROM dim_product WHERE apn IS NOT NULL").fetchall()
    result = {}
    for apn_raw, pid in rows:
        key = norm_apn(apn_raw)
        if key:
            result[key] = pid
    return result


def build_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {normalised_name: product_id} from dim_product for fallback matching."""
    rows = conn.execute("SELECT name, product_id FROM dim_product").fetchall()
    return {re.sub(r'\s+', ' ', str(n).upper().strip()): pid for n, pid in rows}


def resolve_product_id(apn: str | None, description: str | None,
                       apn_map: dict, name_map: dict) -> int | None:
    """Try APN first, then normalised description."""
    if apn:
        pid = apn_map.get(apn)
        if pid:
            return pid
    if description:
        norm_desc = re.sub(r'\s+', ' ', str(description).upper().strip())
        return name_map.get(norm_desc)
    return None


# ── Parse dump file ───────────────────────────────────────────────────────────

def parse_dump(path: Path) -> tuple[str, str, list[dict]]:
    """
    Parse a GAP POS Dump Stock Summary Report Excel file.

    Returns (period_start_iso, period_end_iso, list_of_row_dicts).

    Column positions (0-based) after reading with header=None:
      0=Store  2=Date  3=APN  5=Item No  7=Description  12=Qty
      13=Unit Cost ex  15=Unit Sell ex  18=Reason  20=Total Cost ex  21=Total Sell ex
    """
    raw = pd.read_excel(path, header=None)

    # Extract date range from row 2, col 11
    period_start = period_end = None
    date_cell = str(raw.iloc[2, 11]) if pd.notna(raw.iloc[2, 11]) else ""
    # Format: "Thursday 01 Jan 2026 to Thursday 23 Apr 2026"
    date_match = re.findall(r"\d{2}\s+\w{3}\s+\d{4}", date_cell)
    if len(date_match) >= 2:
        period_start = pd.to_datetime(date_match[0], dayfirst=True).strftime("%Y-%m-%d")
        period_end   = pd.to_datetime(date_match[1], dayfirst=True).strftime("%Y-%m-%d")

    rows = []
    current_dept = None

    for _, row in raw.iterrows():
        val0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""

        # Department separator row
        if val0 in DEPARTMENTS:
            current_dept = val0
            continue

        # Data row
        if val0 == "Foodland Wudinna" and current_dept is not None:
            date_raw = row.iloc[2]
            apn_raw  = row.iloc[3]

            # Skip if no date (malformed row)
            if pd.isna(date_raw):
                continue

            try:
                date_id = pd.to_datetime(str(date_raw), dayfirst=True).strftime("%Y-%m-%d")
            except Exception:
                continue

            apn = norm_apn(apn_raw)

            def _float(v):
                try:
                    return float(v) if pd.notna(v) else None
                except (ValueError, TypeError):
                    return None

            rows.append({
                "date_id":      date_id,
                "department":   current_dept,
                "apn":          apn,
                "item_no":      str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else None,
                "description":  str(row.iloc[7]).strip() if pd.notna(row.iloc[7]) else None,
                "qty":          _float(row.iloc[12]),
                "unit_cost_ex": _float(row.iloc[13]),
                "unit_sell_ex": _float(row.iloc[15]),
                "reason":       str(row.iloc[18]).strip() if pd.notna(row.iloc[18]) else None,
                "total_cost_ex":_float(row.iloc[20]),
                "total_sell_ex":_float(row.iloc[21]),
            })

    return period_start, period_end, rows


# ── Parse markdown CSV (new date-based format) ───────────────────────────────

def parse_markdown_csv(path: Path) -> list[dict]:
    """
    Parse the new GAP POS Markdown CSV export (individual transaction dates).

    Columns expected: Sales Date, Store Name, Department Name, APN, Name,
    Sub Department Name, Cost Ex GST, Cost Inc GST, Discount, Impact,
    Lines, Potential Sales, Sales Ex GST, Sales Inc GST

    Returns a list of row dicts with date_id and derived realised_profit.
    """
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()

    if "Sales Date" in df.columns:
        df = df.rename(columns={"Sales Date": "Date"})
    if "Date" not in df.columns:
        raise ValueError(f"Expected 'Sales Date' column — found: {list(df.columns)}")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["Date", "Name", "Department Name"])
    df = df[df["Department Name"].isin(DEPARTMENTS)]

    def _float(v):
        try:
            return float(v) if pd.notna(v) else None
        except (ValueError, TypeError):
            return None

    rows = []
    for _, r in df.iterrows():
        apn  = norm_apn(r.get("APN"))
        name = re.sub(r"\s+", " ", str(r["Name"]).upper().strip())
        cost = _float(r.get("Cost Ex GST"))
        sell = _float(r.get("Sales Ex GST"))
        disc = _float(r.get("Discount"))
        pot  = _float(r.get("Potential Sales"))
        realised = round(sell - cost, 4) if (sell is not None and cost is not None) else None
        sub_dept = str(r.get("Sub Department Name", "")).strip() or None

        rows.append({
            "date_id":       r["Date"],
            "department":    r["Department Name"].strip(),
            "apn":           apn,
            "description":   name,
            "sub_dept":      sub_dept,
            "lines":         _float(r.get("Lines")),
            "potential_sell":pot,
            "total_sell":    sell,
            "total_cost":    cost,
            "discount_given":disc,
            "realised_profit":realised,
        })

    return rows


# ── Load into DB ──────────────────────────────────────────────────────────────

def load_dump(rows: list[dict], apn_map: dict, name_map: dict, period_start: str,
              source_file: str, conn: sqlite3.Connection) -> int:
    # Remove existing rows for this date range — idempotent regardless of filename.
    # Dump reports always cover a single period; deleting by date range prevents
    # duplicates when the same data is exported again under a different filename.
    if rows:
        dates = [r["date_id"] for r in rows if r.get("date_id")]
        if dates:
            date_min, date_max = min(dates), max(dates)
            conn.execute(
                "DELETE FROM fact_dump WHERE date_id BETWEEN ? AND ?",
                (date_min, date_max),
            )
        else:
            conn.execute("DELETE FROM fact_dump WHERE source_file = ?", (source_file,))

    params = []
    for r in rows:
        pid = resolve_product_id(r["apn"], r["description"], apn_map, name_map)
        params.append((
            r["date_id"],
            pid,
            r["department"],
            r["apn"],
            r["description"],
            r["qty"],
            r["unit_cost_ex"],
            r["unit_sell_ex"],
            r["reason"],
            r["total_cost_ex"],
            r["total_sell_ex"],
            source_file,
        ))

    conn.executemany(
        """INSERT OR IGNORE INTO fact_dump
           (date_id, product_id, department, apn, description,
            qty, unit_cost_ex, unit_sell_ex, reason, total_cost_ex, total_sell_ex,
            source_file)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        params,
    )
    return len(params)


def load_markdown_rows(rows: list[dict], apn_map: dict, name_map: dict,
                       source_file: str, conn: sqlite3.Connection) -> int:
    """Insert markdown rows. Idempotent — deletes the covered date range before inserting,
    so re-uploading data under a different filename never creates duplicates."""
    if rows:
        dates = [r["date_id"] for r in rows if r.get("date_id")]
        if dates:
            date_min, date_max = min(dates), max(dates)
            conn.execute(
                "DELETE FROM fact_markdown WHERE date_id BETWEEN ? AND ?",
                (date_min, date_max),
            )
        else:
            conn.execute("DELETE FROM fact_markdown WHERE source_file = ?", (source_file,))

    params = []
    for r in rows:
        pid = resolve_product_id(r["apn"], r["description"], apn_map, name_map)
        params.append((
            r["date_id"],
            pid,
            r["department"],
            r["apn"],
            r["description"],
            r["sub_dept"],
            r["lines"],
            r["potential_sell"],
            r["total_sell"],
            r["total_cost"],
            r["discount_given"],
            r["realised_profit"],
            source_file,
        ))

    conn.executemany(
        """INSERT OR IGNORE INTO fact_markdown
           (date_id, product_id, department, apn, description, sub_dept,
            lines, potential_sell, total_sell, total_cost,
            discount_given, realised_profit, source_file)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        params,
    )
    return len(params)


# ── Parse waste log ───────────────────────────────────────────────────────────

def parse_waste_log(path: Path) -> list[dict]:
    """
    Parse the FruitVeg_Waste_Log_v2.xlsx Weekly Entry sheet.

    Header is at row index 2. Returns a list of row dicts.
    costed_cost is computed in load_waste_log_rows() via ref_item_price lookup.
    """
    import warnings
    warnings.filterwarnings("ignore")

    df = pd.read_excel(path, sheet_name="Weekly Entry", header=2)
    df = df[pd.to_datetime(df["Date"], errors="coerce").notna()].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Item Name"].notna()].copy()

    rows = []
    for _, row in df.iterrows():
        def _float(v):
            try:
                return float(v) if pd.notna(v) else None
            except (ValueError, TypeError):
                return None

        rows.append({
            "date_id":    row["Date"].strftime("%Y-%m-%d"),
            "item_name":  str(row["Item Name"]).strip(),
            "qty":        _float(row["Qty"]),
            "unit":       str(row["Unit"]).strip() if pd.notna(row["Unit"]) else None,
            "sell_price": _float(row["Price"]),
            "action":     str(row["Action"]).strip() if pd.notna(row["Action"]) else None,
            "new_price":  _float(row["New Price"]),
            "reason":     str(row["Reason"]).strip() if pd.notna(row["Reason"]) else None,
        })
    return rows


def load_waste_log_rows(rows: list[dict], name_map: dict, cost_map: dict,
                        source_file: str, conn: sqlite3.Connection) -> int:
    """
    Insert waste log rows into fact_waste_log.
    Matches product_id via normalised name, computes costed_cost (qty × cost_price)
    from ref_item_price. cost_source = 'confirmed' if matched, NULL if not.
    """
    conn.execute("DELETE FROM fact_waste_log WHERE source_file = ?", (source_file,))

    params = []
    for r in rows:
        norm_name = re.sub(r"\s+", " ", str(r["item_name"]).upper().strip())
        pid = name_map.get(norm_name)
        cost_price = cost_map.get(pid) if pid else None
        costed_cost = round(r["qty"] * cost_price, 4) if (r["qty"] and cost_price) else None
        cost_source = "confirmed" if costed_cost is not None else None

        params.append((
            r["date_id"],
            pid,
            r["item_name"],
            r["qty"],
            r["unit"],
            r["sell_price"],
            r["action"],
            r["new_price"],
            r["reason"],
            costed_cost,
            cost_source,
            source_file,
        ))

    conn.executemany(
        """INSERT INTO fact_waste_log
           (date_id, product_id, item_name, qty, unit, sell_price, action,
            new_price, reason, costed_cost, cost_source, source_file)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        params,
    )
    return len(params)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import GAP POS waste reports into foodland_data.db")
    parser.add_argument("--dump",         default=str(DUMP_DEFAULT),         help="Path to Dump Stock Report xlsx")
    parser.add_argument("--markdown-csv", default=str(MARKDOWN_CSV_DEFAULT), help="Path to Markdown CSV (date-based export)")
    parser.add_argument("--waste-log",    default=str(WASTE_LOG_DEFAULT),     help="Path to FruitVeg Waste Log xlsx")
    args = parser.parse_args()

    dump_path      = Path(args.dump)
    md_csv_path    = Path(args.markdown_csv)
    waste_log_path = Path(args.waste_log)

    if not dump_path.exists():
        print(f"[SKIP] Dump file not found: {dump_path}")
    if not md_csv_path.exists():
        print(f"[SKIP] Markdown CSV not found: {md_csv_path}")
    if not waste_log_path.exists():
        print(f"[SKIP] Waste log not found: {waste_log_path}")
    if not any(p.exists() for p in [dump_path, md_csv_path, waste_log_path]):
        return

    with _write_conn_ctx() as conn:
        # 1. Ensure tables exist
        ensure_schema(conn)
        print("[OK] Schema verified.")

        # 2. Build product lookup maps
        apn_map  = build_apn_map(conn)
        name_map = build_name_map(conn)
        cost_map = {r[0]: r[1] for r in conn.execute(
            "SELECT product_id, cost_price FROM ref_item_price WHERE cost_price IS NOT NULL"
        )}
        print(f"[OK] Product lookup: {len(apn_map)} APN entries, {len(name_map)} name entries.")

        # 3. Import dump
        if dump_path.exists():
            print(f"\nParsing dump: {dump_path.name}")
            p_start, p_end, dump_rows = parse_dump(dump_path)
            print(f"  Period:  {p_start} → {p_end}")
            print(f"  Rows:    {len(dump_rows)}")
            matched = sum(1 for r in dump_rows
                          if resolve_product_id(r["apn"], r["description"], apn_map, name_map))
            print(f"  Matched: {matched}/{len(dump_rows)} rows linked to dim_product")
            n = load_dump(dump_rows, apn_map, name_map, p_start, dump_path.name, conn)
            print(f"  Loaded:  {n} rows into fact_dump")

        # 4. Import markdown CSV (date-based)
        if md_csv_path.exists():
            print(f"\nParsing markdown CSV: {md_csv_path.name}")
            md_rows = parse_markdown_csv(md_csv_path)
            dates = [r["date_id"] for r in md_rows]
            print(f"  Period:  {min(dates)} → {max(dates)}")
            print(f"  Rows:    {len(md_rows)}")
            depts = {}
            for r in md_rows:
                depts[r["department"]] = depts.get(r["department"], 0) + 1
            for dept, cnt in sorted(depts.items()):
                print(f"    {dept}: {cnt} rows")
            matched = sum(1 for r in md_rows
                          if resolve_product_id(r["apn"], r["description"], apn_map, name_map))
            print(f"  Matched: {matched}/{len(md_rows)} rows linked to dim_product")
            n = load_markdown_rows(md_rows, apn_map, name_map, md_csv_path.name, conn)
            print(f"  Loaded:  {n} rows into fact_markdown")

        # 5. Import waste log
        if waste_log_path.exists():
            print(f"\nParsing waste log: {waste_log_path.name}")
            wl_rows = parse_waste_log(waste_log_path)
            dates = [r["date_id"] for r in wl_rows]
            print(f"  Period:  {min(dates)} → {max(dates)}")
            print(f"  Rows:    {len(wl_rows)}")
            matched = sum(1 for r in wl_rows
                          if name_map.get(re.sub(r'\s+', ' ', r['item_name'].upper().strip())))
            print(f"  Matched: {matched}/{len(wl_rows)} rows linked to dim_product")
            n = load_waste_log_rows(wl_rows, name_map, cost_map, waste_log_path.name, conn)
            print(f"  Loaded:  {n} rows into fact_waste_log")

        print("\n[DONE] foodland_data.db updated.")


if __name__ == "__main__":
    main()
