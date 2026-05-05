"""
migrate_markdown_v2.py — Rebuild fact_markdown with a date-based schema.

The old fact_markdown stored period-aggregate data (period_start, period_end,
one row per item per report period).  The new GAP export provides individual
transaction dates, so we rebuild the table with a date_id column.

Changes
-------
• fact_markdown: drop period_start / period_end / item_no / weight_kg /
  avg_unit_kg_sell / avg_cost_kg_unit / gp_pct columns.
  Add date_id (individual transaction date) and sub_dept (from CSV directly).
• v_waste_summary: rebuild to use fact_markdown.date_id as event_date.

This script is safe to re-run — it just truncates fact_markdown and
recreates the schema if the column signature differs.

Usage:
    python migrate_markdown_v2.py
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
DB   = ROOT / "foodland_data.db"

NEW_MARKDOWN_DDL = """
CREATE TABLE fact_markdown (
    markdown_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id         TEXT    NOT NULL,     -- YYYY-MM-DD (individual transaction date)
    product_id      INTEGER,              -- FK dim_product (NULL if unmatched)
    department      TEXT,
    apn             TEXT,
    description     TEXT,
    sub_dept        TEXT,                 -- from CSV Sub Department Name
    lines           REAL,                 -- number of lines / qty
    potential_sell  REAL,                 -- full-price revenue (Potential Sales)
    total_sell      REAL,                 -- actual sell (Sales Ex GST)
    total_cost      REAL,                 -- cost of goods (Cost Ex GST)
    discount_given  REAL,                 -- potential_sell - total_sell
    realised_profit REAL,                 -- total_sell - total_cost (neg = sold below cost)
    source_file     TEXT
)
"""

NEW_VIEW_DDL = """
CREATE VIEW v_waste_summary AS
SELECT
    'dump'              AS waste_type,
    fd.date_id          AS event_date,
    fd.product_id,
    COALESCE(dp.name, fd.description) AS description,
    COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown') AS sub_dept,
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
    fm.date_id          AS event_date,
    fm.product_id,
    COALESCE(dp.name, fm.description) AS description,
    COALESCE(NULLIF(dp.sub_dept, 'None'), NULLIF(fm.sub_dept, 'None'), 'Unknown') AS sub_dept,
    fm.department,
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
    COALESCE(dp.name, wl.item_name) AS description,
    COALESCE(NULLIF(dp.sub_dept, 'None'), 'Unknown') AS sub_dept,
    'FRUIT & VEG'       AS department,
    wl.qty,
    COALESCE(wl.actual_cost, wl.log_cost) AS waste_cost,
    CASE WHEN wl.action = 'Reduced' THEN wl.log_cost END AS discount_given,
    NULL                AS realised_profit,
    wl.reason,
    wl.source_file
FROM fact_waste_log wl
LEFT JOIN dim_product dp ON wl.product_id = dp.product_id
"""


def migrate():
    tmp = Path(tempfile.mktemp(suffix=".db", prefix="foodland_mig_"))
    try:
        shutil.copy2(DB, tmp)
        conn = sqlite3.connect(tmp)
        conn.execute("PRAGMA journal_mode=DELETE")

        # Check current fact_markdown columns
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fact_markdown)")]
        already_migrated = "date_id" in cols and "period_start" not in cols

        if already_migrated:
            print("[OK] fact_markdown already on new schema — truncating only.")
            conn.execute("DELETE FROM fact_markdown")
        else:
            print("[MIGRATE] Rebuilding fact_markdown with date-based schema...")
            old_count = conn.execute("SELECT COUNT(*) FROM fact_markdown").fetchone()[0]
            print(f"  Old row count: {old_count}")
            conn.execute("DROP TABLE fact_markdown")
            conn.execute(NEW_MARKDOWN_DDL)
            print("  fact_markdown recreated.")

        # Rebuild v_waste_summary
        conn.execute("DROP VIEW IF EXISTS v_waste_summary")
        conn.execute(NEW_VIEW_DDL)
        print("[OK] v_waste_summary rebuilt.")

        conn.commit()
        conn.close()
        shutil.copy2(tmp, DB)
        print("[DONE] Migration complete.")

    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"[ERROR] {e}")
        raise
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    migrate()
