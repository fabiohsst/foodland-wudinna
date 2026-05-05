# Foodland Wudinna — Database Audit Report
**Schema version audited:** v3 (post migrate_v3.py)  
**Audit date:** 2026-04-29  
**Auditor:** Data Scientist / Claude Cowork  

---

## 0. Executive Summary

The current database has one critical infrastructure problem and ten structural issues that, left unaddressed, will degrade reliability and make future analytics work harder than it needs to be. The good news: all source data exists in raw CSVs, so the DB can be fully rebuilt and improved without any data loss.

**Priority rank:**

| # | Issue | Severity |
|---|-------|----------|
| 1 | Database file is truncated (corrupt) | 🔴 Critical |
| 2 | Zero indexes on any table | 🔴 High |
| 3 | Waste data split across three incompatible tables | 🟠 High |
| 4 | Calculated columns stored in fact_sales | 🟡 Medium |
| 5 | Redundant columns duplicated from dim_product into facts | 🟡 Medium |
| 6 | FK enforcement never enabled at runtime | 🟡 Medium |
| 7 | Specials and promotions live outside the DB entirely | 🟡 Medium |
| 8 | Parallel Power BI CSV pipeline disconnected from DB | 🟡 Medium |
| 9 | Silent ghost-product creation during import | 🟡 Medium |
| 10 | fact_stock has no unit column | 🟢 Low |
| 11 | Online-sales columns always zero for a physical-only store | 🟢 Low |

---

## 1. Critical — Database File Corruption

**Finding:** The SQLite file header declares 8,713 pages (35.7 MB expected) but the file on disk is 22.2 MB (5,428 pages). The final ~13.5 MB are missing.

**Impact:** The B-tree pages for `dim_product` and `fact_sales` — the two most-queried tables — fall in the missing region. Both tables are currently unreadable. Every app that calls `load_sales()` or references a product join is failing silently or returning empty data.

**Root cause:** OneDrive / virtiofs truncation. The `_write_conn()` pattern in `db.py` (copy to `/tmp` → write → copy back) is sound, but if a large write is interrupted mid-copy-back (OneDrive sync conflict, sleep, network drop), the destination file gets truncated. The DB header is written first, so the page count is already committed to the old value before the data arrives.

**Resolution — rebuild from source:**
```bash
python migrate_v3.py --force
```
All source CSVs are intact under `01_data/raw/`. A full rebuild takes < 2 minutes and is safe to re-run. After rebuild, add a post-write integrity check to `db.py` (see §10).

**Prevention going forward:** After every `shutil.copy2(tmp, DB)` in `_write_conn()`, add a quick page-count sanity check:

```python
def _verify_db(path: Path) -> None:
    import struct
    with open(path, 'rb') as f:
        header = f.read(32)
    if len(header) < 32:
        raise RuntimeError("DB write failed: file too small after copy")
    page_size  = struct.unpack('>H', header[16:18])[0]
    hdr_pages  = struct.unpack('>I', header[28:32])[0]
    actual_pages = path.stat().st_size // page_size
    if actual_pages < hdr_pages * 0.95:   # >5% page loss = abort
        raise RuntimeError(
            f"DB truncation detected: header={hdr_pages} pages, "
            f"actual={actual_pages}. Aborting — /tmp copy preserved."
        )
```

---

## 2. No Indexes

**Finding:** `sqlite_master` contains zero user-created indexes. Every query against every fact table is a full table scan.

**Impact:** Grows linearly with data volume. A full year of FV + Dairy + Meat sales at current load rate will hit ~15,000 rows in `fact_sales`. Date-range queries like those in `panel.py` and `app.py` scan every single row. As data grows to cover 2024–2026+ this becomes the primary performance bottleneck.

**What to add (migrate_v4.py):**

```sql
-- fact_sales: date range queries (dominant access pattern)
CREATE INDEX IF NOT EXISTS idx_fact_sales_date       ON fact_sales(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_sales_product    ON fact_sales(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_sales_dept_date  ON fact_sales(department, date_id);

-- fact_markdown / fact_dump / fact_waste_log: waste dashboard queries
CREATE INDEX IF NOT EXISTS idx_fact_markdown_date    ON fact_markdown(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_markdown_product ON fact_markdown(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_dump_date        ON fact_dump(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_waste_date       ON fact_waste_log(date_id);

-- fact_invoice: price history lookups
CREATE INDEX IF NOT EXISTS idx_fact_invoice_product  ON fact_invoice(product_id);
CREATE INDEX IF NOT EXISTS idx_fact_invoice_date     ON fact_invoice(date_id);

-- dim_product: name lookup (used in all import scripts)
CREATE INDEX IF NOT EXISTS idx_dim_product_name      ON dim_product(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_dim_product_apn       ON dim_product(apn);
```

---

## 3. Waste Data Fragmentation

**Finding:** Three separate tables track product waste/markdown with incompatible schemas:

| Table | Source | Qty field | Cost basis | Date granularity |
|-------|--------|-----------|-----------|-----------------|
| `fact_dump` | GAP POS Dump Export (XLSX) | `qty` (units) | `unit_cost_ex` | individual events |
| `fact_markdown` | GAP POS Markdown CSV | `lines` (not qty) | `total_cost` | individual transactions |
| `fact_waste_log` | Manual spreadsheet | `qty` (units) | `costed_cost` (merged field) | individual entries |

The `v_waste_summary` view unions all three, but the semantic mismatch remains: `fact_markdown.lines` is transaction count, not units. Aggregating "total units wasted" across all three sources produces incorrect numbers.

**Additionally:**
- `fact_markdown` covers Dairy and Meat in addition to F&V; `fact_waste_log` covers F&V only
- `fact_dump` and `fact_waste_log` both record binning events for F&V — they may double-count the same disposal depending on what the GAP operator logged vs what staff recorded manually
- `fact_markdown` has `sub_dept` but `fact_dump` does not (dropped `item_no` in v3 which could have helped)

**Proposed consolidation — `fact_waste` (v4):**

```sql
CREATE TABLE fact_waste (
    waste_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id        TEXT    NOT NULL REFERENCES dim_date(date_id),
    product_id     INTEGER REFERENCES dim_product(product_id),
    waste_type     TEXT    NOT NULL,   -- 'dump' | 'markdown' | 'store_use'
    source         TEXT    NOT NULL,   -- 'gap_dump' | 'gap_markdown' | 'manual_log'
    department     TEXT,
    qty            REAL,               -- always in sell_units; NULL if unknown
    unit_cost      REAL,               -- cost per unit at time of waste
    total_cost     REAL,               -- qty × unit_cost
    potential_sell REAL,               -- what it would have sold for
    actual_sell    REAL,               -- what it sold for (markdown only)
    discount_given REAL,               -- markdown discount
    reason         TEXT,
    source_file    TEXT    NOT NULL
);
```

This requires a one-time migration to remap:
- `fact_dump` rows → `waste_type='dump'`, `source='gap_dump'`
- `fact_markdown` rows → `waste_type='markdown'`, `source='gap_markdown'`, `qty` = NULL (lines ≠ qty)
- `fact_waste_log` rows → mapped per `action` value

Keep the three source tables as staging tables or archive them. `v_waste_summary` becomes a straight SELECT from `fact_waste`.

---

## 4. Stored Calculated Columns in fact_sales

**Finding:** `fact_sales` stores columns that are fully derivable from others:

| Column | Derivation |
|--------|-----------|
| `gp_dollars` | `sales_ex_gst - cost_ex_gst` |
| `gp_pct` | `gp_dollars / NULLIF(sales_ex_gst, 0)` |
| `sales_inc_gst` | `sales_ex_gst * 1.1` |
| `cost_inc_gst` | `cost_ex_gst * 1.1` |

These are read directly from the POS export and stored as-is, which is fine for source fidelity. The issue is that they create false confidence in the data: if the POS export has a rounding error in `gp_pct`, the stored value will differ from what you'd compute from the raw figures. Panel queries that compute GP% independently from `sales_ex_gst` and `cost_ex_gst` will disagree with the stored `gp_pct`.

**Recommendation:** Keep `sales_ex_gst` and `cost_ex_gst` as the canonical source-of-truth columns. In v4, add a comment or remove `gp_dollars`, `gp_pct`, `sales_inc_gst`, and `cost_inc_gst`. If apps need them, expose them through views (they're already in `v_sales`). This reduces fact_sales width by 4 columns and removes the inconsistency risk.

---

## 5. Redundant Columns Duplicated from dim_product into Fact Tables

**Finding:** Several columns in fact tables duplicate what's already in `dim_product`:

| Fact table | Column | dim_product equivalent |
|-----------|--------|----------------------|
| `fact_sales` | `department` | `dim_product.department` |
| `fact_sales` | `sub_dept` | `dim_product.sub_dept` |
| `fact_sales` | `apn` | `dim_product.apn` |
| `fact_sales` | `store_name` | (always "Foodland Wudinna" — single store) |
| `fact_markdown` | `department` | `dim_product.department` |
| `fact_markdown` | `sub_dept` | `dim_product.sub_dept` |
| `fact_markdown` | `description` | `dim_product.name` (when matched) |
| `fact_dump` | `description` | `dim_product.name` (when matched) |
| `fact_invoice` | `product_name` | `dim_product.name` |

The denormalization in fact tables isn't inherently wrong in a star schema — some query speed benefit. But the cost is:
- Any dim_product update (name correction, sub_dept change) doesn't cascade
- `store_name` wastes ~20 bytes per row for a single-value column
- `description` columns in fact_dump/fact_markdown are the raw POS text, which creates a shadow product catalogue

**Recommendation for v4:**
- Drop `store_name` from `fact_sales` (add `dim_store` if multiple stores ever join)
- Drop `department` and `sub_dept` from `fact_sales` and `fact_markdown` — retrieve from `dim_product` via join
- Keep `apn` in `fact_sales` as it was the source barcode scanned at time of sale (not a dupe — it's an event attribute)
- Keep `description` in `fact_dump` and `fact_markdown` for unmatched rows (where `product_id` is NULL)
- Drop `product_name` from `fact_invoice` — it's a denorm that will go stale

---

## 6. FK Enforcement Never Enabled at Runtime

**Finding:** All fact tables declare `REFERENCES dim_product(product_id)` and `REFERENCES dim_date(date_id)` in their DDL. But `db.py` never calls `PRAGMA foreign_keys=ON` on any connection — read or write. SQLite's default is FK enforcement off.

**Impact:** Orphan rows can be inserted without error. Specifically:
- `import_waste.py` inserts `fact_dump`/`fact_markdown` rows with `date_id` values not in `dim_date` (e.g. dates beyond the dim_date range built during migration)
- Any product FK mismatch fails silently — the row is inserted with `product_id = NULL` rather than rejected

**Fix:** Add to `_write_conn()` in `db.py`:
```python
conn.execute("PRAGMA foreign_keys=ON")
```
Also extend `dim_date` in `migrate_v3.py` to cover at least 3 years ahead of the current date (≈ 2029), so future import dates don't create orphan date_id values.

---

## 7. Specials and Promotions Exist Only as Flat Files

**Finding:** The promotions/specials workflow operates entirely outside the database:
- `01_data/operational/specials_this_week.csv` — current week's specials, manually updated
- `01_data/reference/specials_mapping.csv` — historical specials reconstruction
- `07_powerbi/data/fact_promotions.csv` — promotions built by `build_fact_promotions.py` for Power BI

The demand forecast model in `predict.py` uses a `cycle_on_special` feature (third most important) but reads this from CSV, not the DB. This means:
- Specials are never versioned or audited
- Historical specials data is in a CSV that may or may not be complete
- The Power BI promotions table exists but the equivalent DB table does not

**Proposed table — `fact_promotion`:**

```sql
CREATE TABLE fact_promotion (
    promo_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL REFERENCES dim_product(product_id),
    start_date     TEXT    NOT NULL REFERENCES dim_date(date_id),
    end_date       TEXT    NOT NULL REFERENCES dim_date(date_id),
    promo_price    REAL,
    promo_type     TEXT,   -- 'catalogue' | 'clearance' | 'weekly'
    source         TEXT,   -- 'specials_sheet' | 'freshlink_bulletin' | 'manual'
    source_file    TEXT,
    UNIQUE(product_id, start_date)
);
```

`parse_specials_sheet.py` and `parse_price_guide.py` already parse the raw inputs — they just need to write to this table instead of (or in addition to) CSVs.

---

## 8. Parallel Power BI CSV Pipeline

**Finding:** The `07_powerbi/` directory contains an entirely separate flat-file pipeline (`build_dim_calendar.py`, `build_dim_item.py`, `build_fact_sales.py`, `build_fact_promotions.py`) that reads from `01_data/raw/` and writes CSVs for Power BI. This pipeline:
- Covers F&V only (not Dairy or Meat)
- Is not fed from the SQLite DB
- Produces `fact_promotions` which has no equivalent in the DB
- Has its own product dimension (`dim_item.csv`) that may diverge from `dim_product`

**Risk:** Two independent transformations of the same source data will eventually produce different numbers for the same metric. When the Power BI dashboard disagrees with the Streamlit apps, there's no single source of truth to arbitrate.

**Recommendation:** Replace the Power BI CSV pipeline with views or query exports from `foodland_data.db`. Power BI can connect directly to SQLite via ODBC, or the CSVs can be generated by querying the DB (making the DB the single source of truth). This is a lower priority change but should happen before the Power BI dataset grows significantly.

---

## 9. Silent Ghost-Product Creation During Import

**Finding:** Both `import_sales_rows()` and `upsert_item_prices()` in `db.py` silently insert new `dim_product` rows for any name not found in the current product list:

```python
# From db.py — called on every sales import
conn.execute(
    "INSERT OR IGNORE INTO dim_product (name, sell_unit) VALUES (?,?)",
    (norm_name, "each"),
)
```

**Impact:** A typo in a POS export creates a permanent ghost product (e.g. "BROCOLLNI" alongside "BROCCOLINI"). Ghost products get `product_id` values, accumulate sales rows, and pollute forecasting. The `dim_product.active` flag exists to handle this but is never set to `0` by any script.

**Fix:** Log unmatched product names to a separate staging table (`stg_unmatched_products`) instead of auto-inserting into `dim_product`. A manual review step approves or maps them. This mirrors how `ref_invoice_mapping` handles unmatched invoice descriptions.

---

## 10. fact_stock Missing Unit Context

**Finding:** `fact_stock` stores a numeric `stock` value with no unit column. The SOH exports from GAP POS can be in units, kg, or cases depending on the product, but this information is lost.

```sql
-- Current
CREATE TABLE fact_stock (
    stock_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id     TEXT NOT NULL,
    product_id  INTEGER NOT NULL,
    stock       REAL,       -- units? kg? cases? unknown
    source      TEXT
);
```

**Fix:** Add `stock_unit TEXT` (defaulting to `dim_product.sell_unit`) and `stock_type TEXT` for `'physical_count' | 'system_count'`. Also: the `source` free-text field should reference an import source file consistently, not a human-readable string.

---

## 11. Redundant Online Sales Columns in fact_sales

**Finding:** `fact_sales` contains four columns for store vs online sales split: `store_sales_ex`, `store_sales_inc`, `online_sales_ex`, `online_sales_inc`. Foodland Wudinna is a physical-only store. These columns are either zero or equal to the main totals. They were included because the GAP export format has these columns, but they add no analytical value for a single-location physical store.

**Fix:** Drop all four columns in v4. If an online channel ever opens, they can be re-added. Removing them reduces fact_sales width by 4 columns (~15% slimmer).

---

## 12. Other Observations

**_meta table is empty.** The `_meta` table created by `migrate_v3.py` has no rows — the schema version flag `v3` was never written. Either the migration was partially run or the final `_write_conn()` block failed after the DB was already truncated. When the DB is rebuilt, verify `_meta` contains `('schema_version', 'v3')`.

**dim_date covers only 850 days (~2.3 years).** The migration script builds dim_date from `min(sales.date)` to `max(sales.date) + 365 days`. With multi-year data now loaded (2025 Dairy/Meat + 2026 FV), this may clip future ordering dates. Extend to cover `today + 2 years` during rebuild.

**dim_supplier has 1 row** and the `supplier_id` FK in `fact_invoice` is almost never populated (supplier was inferred from free-text in the `source` field). Either fully populate it or simplify `fact_invoice` by making supplier a TEXT field until more suppliers are added.

**ref_item_price.price_source logic is approximate.** The v3 migration set `price_source = 'invoice'` for rows where `sell_price_manual != sell_price`, but this heuristic misclassifies manual overrides that happen to match an invoice price. The correct approach is to set `price_source` at write time in `generate_price_updates.py --apply` (invoice) and `upsert_item_prices()` (manual).

---

## 13. Proposed v4 Schema Changes

### Summary of changes

| Change | Tables affected | Priority |
|--------|----------------|----------|
| Add 10 indexes | all fact tables, dim_product | 🔴 Do first |
| Add `_verify_db()` to `_write_conn()` | `db.py` | 🔴 Do first |
| Extend `dim_date` to today + 2 years | `dim_date` | 🔴 Do with rebuild |
| Merge fact_dump + fact_markdown + fact_waste_log → `fact_waste` | 3 tables | 🟠 Phase 2 |
| Add `fact_promotion` table | new | 🟡 Phase 2 |
| Drop `store_name` from `fact_sales` | `fact_sales` | 🟡 Phase 3 |
| Drop `department`, `sub_dept` from `fact_sales` | `fact_sales` | 🟡 Phase 3 |
| Drop `gp_pct`, `gp_dollars`, `sales_inc_gst`, `cost_inc_gst` | `fact_sales` | 🟡 Phase 3 |
| Drop `store_sales_*`, `online_sales_*` | `fact_sales` | 🟡 Phase 3 |
| Drop `product_name` from `fact_invoice` | `fact_invoice` | 🟡 Phase 3 |
| Add `stock_unit`, `stock_type` to `fact_stock` | `fact_stock` | 🟢 Phase 3 |
| Enable FK enforcement in `_write_conn()` | `db.py` | 🟡 Phase 2 |
| Redirect ghost products to `stg_unmatched_products` | `db.py` | 🟡 Phase 2 |
| Replace Power BI CSV pipeline with DB views | `07_powerbi/` | 🟡 Phase 3 |

### Phase 1 — Immediate (do before anything else)
1. Rebuild the database: `python migrate_v3.py --force` 
2. Verify `_meta` row is present and row counts are correct
3. Run `python check_db.py` to confirm data currency
4. Add `_verify_db()` to `db.py`
5. Add the 10 indexes listed in §2

### Phase 2 — Next sprint
6. Consolidate waste tables into `fact_waste`
7. Add `fact_promotion` and wire up `parse_specials_sheet.py` to write to it
8. Enable FK enforcement in write connections
9. Replace ghost-product auto-insert with `stg_unmatched_products` staging

### Phase 3 — Clean-up (can batch with a v4 migration script)
10. Slim down `fact_sales` (drop calculated and redundant columns)
11. Update all apps and `v_sales` view to derive GP% and GST amounts in SQL
12. Consolidate the Power BI pipeline to read from the DB
13. Add `stock_unit` / `stock_type` to `fact_stock`

---

## 14. Reference: Current Schema State (v3, as read from corrupt file)

For completeness — columns confirmed from `PRAGMA table_info()` on the recoverable portion of the DB.

| Table | Columns (post-v3) |
|-------|------------------|
| `dim_product` | product_id, name, sub_dept, sell_unit, apn, active, created_at, department |
| `dim_date` | date_id, year, month, month_name, week_num, day_of_week, day_name, is_weekend, is_holiday, holiday_name, is_trading |
| `dim_supplier` | supplier_id, name, delivery_days |
| `fact_sales` | sale_id, date_id, product_id, store_name, department, apn, sales_inc_gst, cost_ex_gst, cost_inc_gst, gp_pct, gp_dollars, lines, quantity, sales_ex_gst, store_sales_ex, store_sales_inc, online_sales_ex, online_sales_inc, date_imported, source_file, sub_dept |
| `fact_invoice` | invoice_id, date_id, invoice_no, product_id, supplier_id, cost_per_unit, sell_price, gp_pct, source, invoice_product_name, product_name |
| `fact_stock` | stock_id, date_id, product_id, stock, source |
| `fact_dump` | dump_id, date_id, product_id, department, apn, description, qty, unit_cost_ex, unit_sell_ex, reason, total_cost_ex, total_sell_ex, source_file |
| `fact_markdown` | markdown_id, date_id, product_id, department, apn, description, sub_dept, lines, potential_sell, total_sell, total_cost, discount_given, realised_profit, source_file |
| `fact_waste_log` | log_id, date_id, product_id, item_name, qty, unit, sell_price, action, new_price, reason, costed_cost, cost_source, source_file |
| `ref_item_price` | product_id, sell_price, cost_price, updated_at, price_source |
| `ref_invoice_mapping` | mapping_id, invoice_description, product_id, units_per_invoice, sell_unit, supplier_id, verified, notes |
| `_meta` | key, value |

**Views:** v_sales, v_item_price, v_item_reference, v_price_history, v_stock_on_hand, v_waste_summary

---

*End of report.*
