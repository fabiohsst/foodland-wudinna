# Foodland Wudinna — Project Context

## Store Operations
- **Location:** Wudinna, SA, Australia (independent Foodland)
- **Trading hours:** Mon–Fri 08:30–18:00 · Sat 08:30–12:00 · Sun/Holidays closed
- **Deliveries:** Tuesday morning (ordered Friday) · Friday morning (ordered Wednesday)
- **Order schedule:** Friday order covers Tue+Wed+Thu · Wednesday order covers Fri+Sat+Mon
- **Department in focus:** Fruit & Vegetable

---

## Working Principles
- You are acting as a senior Data Scientist/Analyst and mentor.
- All analysis must be concise and double-checked before presenting conclusions.
- Language must be professional but straightforward — no buzzwords.
- Always keep store hours and delivery schedule in mind when interpreting demand patterns.

---

## Data Infrastructure

### Database — `foodland_data.db` (SQLite, project root)
Star schema migrated April 2026 via `migrate_v2.py`. All apps read/write through `db.py`.

**Fact tables**
| Table | Description |
|---|---|
| `fact_sales` | One row per item per trading day. Source: POS exports. |
| `fact_invoice` | One row per invoice line. Source: Freshlink PDFs/CSVs. |
| `fact_stock` | Point-in-time stock-on-hand snapshots. |
| `fact_dump` | One row per dump transaction (full write-off). Source: GAP POS Dump Stock Report. Loaded by `import_waste.py`. |
| `fact_markdown` | One row per markdown line (period-aggregate discounted sale). Source: GAP POS Markdown Report. Loaded by `import_waste.py`. |

**Dimension & reference tables**
| Table | Description |
|---|---|
| `dim_product` | Master product list. FK anchor for all facts. |
| `dim_date` | Calendar table with SA public holidays and trading-day flags. |
| `dim_supplier` | Supplier list (Freshlink primary). |
| `ref_item_price` | Current sell/cost prices per product. |
| `ref_invoice_mapping` | Invoice description → POS item name + unit conversion. 114 verified entries. |

**Views**
| View | Description |
|---|---|
| `v_sales` | Compatibility view over fact_sales + dim_product. |
| `v_item_price` | Compatibility view over ref_item_price + dim_product. |
| `v_price_history` | Compatibility view over fact_invoice + dim_product. |
| `v_stock_on_hand` | Compatibility view over fact_stock + dim_product. |
| `v_item_reference` | Compatibility view over dim_product (PLU → name). |
| `v_waste_summary` | Combined dump + markdown waste rows, all departments, joined to dim_product. |

### virtiofs / OneDrive write constraint
The DB file sits on a Windows OneDrive mount exposed via virtiofs. SQLite cannot create journal/lock files there.
- **Reads:** use `immutable=1` URI flag in all read connections.
- **Writes:** build in `/tmp` via `_write_conn()` context manager in `db.py`, then `shutil.copy2()` back to mount.
- **Never** call `executescript()` on a virtiofs-backed connection.

### SQL Reference
`sql_reference.html` — standalone file with 14 common business queries across 5 tabs. Open in any browser.

---

## Scripts & Applications

| File | Purpose | Launch |
|---|---|---|
| `db.py` | Shared SQLite read/write module. Used by all apps. | — |
| `import_sales.py` | Import new POS export CSVs into `fact_sales`. Archives processed files. | `Launch Import Sales.bat` |
| `import_waste.py` | Import GAP POS Dump and Markdown xlsx exports into `fact_dump` / `fact_markdown`. Idempotent — re-run when new exports arrive. | `python import_waste.py` |
| `migrate_v2.py` | One-time star schema migration. Safe to re-run if DB is lost. | — |
| `check_db.py` | DB health check — row counts, date ranges, trading day currency. | `python check_db.py` |
| `app.py` | Main ordering app — demand forecast, specials, stock-on-hand. | `Launch Order App.bat` (port 8501) |
| `panel.py` | Performance dashboard — waste KPIs, model accuracy, GP%. | `Launch Performance Panel.bat` (port 8505) |
| `dashboard.py` | Sales overview dashboard. | `Launch Dashboard.bat` (port 8502) |
| `waste_dashboard.py` | Waste tracking dashboard. | `Launch Waste Dashboard.bat` (port 8503) |
| `detect_stockouts.py` | Stockout detection from sales gaps. | `Launch Stockout Detector.bat` |
| `parse_price_guide.py` | Parse Freshlink price guide PDFs. | `Launch Parse Price Guide.bat` |
| `suggest_pg_mappings.py` | LLM-assisted mapping suggestion for unmapped invoice lines. | `Launch Suggest PG Mappings.bat` |
| `pricing_panel.py` | Streamlit pricing review panel (file upload → review → apply). | `Launch Price Update Panel.bat` (port 8508) — **file uploader bug unresolved, see below** |
| `predict.py` | LightGBM demand forecast model. Called by app.py. | — |

### Pricing subdirectory (`pricing/`)
| File | Purpose |
|---|---|
| `generate_price_updates.py` | Core pricing engine. Parse invoice → suggest sell prices → write to DB. |
| `invoices/` | Raw Freshlink invoice files (PDF or CSV). |
| `reviews/` | Generated Excel review sheets (--invoice run). |
| `Launch Price Update.bat` | Drag-and-drop invoice launcher. |

---

## Pricing Automation Workflow

### How it works
1. Receive Freshlink invoice (PDF or CSV).
2. Run `generate_price_updates.py --invoice <file>` (or drag onto BAT file).
3. Script parses invoice → matches each line to a POS item via `ref_invoice_mapping` → calculates suggested sell price at **40% GP target**, rounded up to X.X9.
4. Generates Excel review sheet in `pricing/reviews/`.
5. Review: set Approve = Y for accepted changes, override Suggested Sell if needed.
6. Run with `--apply <review_file>` → writes approved prices to `ref_item_price` and `fact_invoice`.

### Pricing formula
`Suggested Sell = Cost per Unit ÷ (1 − 0.40)`, rounded up to nearest X.X9 cents.

### Flag thresholds
Items are flagged for manual review if: cost change ≥ ±15% OR sell price change ≥ ±15% OR item is on special.

### Invoice mapping (`ref_invoice_mapping`)
114 verified entries mapping Freshlink invoice descriptions → POS item names + units/invoice conversion.
- CSV fallback: `01_data/reference/invoice_item_mapping.csv`
- Any unmatched invoice lines are reported separately in the review sheet.

### Known issue — pricing_panel.py (Streamlit)
The Streamlit panel (`pricing_panel.py`) has a persistent issue where the file uploader widget returns `None` after the upload completes, preventing processing. Root cause confirmed: Streamlit's `file_uploader` has a known bug where the uploaded object is `None` on reruns triggered by the upload completion event itself, even with `on_change` callbacks and `getvalue()`. All other Streamlit panels in the project work correctly — the issue appears specific to certain Streamlit versions interacting with the upload → session_state → display pattern.

**Current workaround:** Use the CLI + Excel workflow (`generate_price_updates.py` + BAT file) which is fully functional and produces the same outcome.

---

## Demand Forecast Model

- **Algorithm:** LightGBM (MAE objective), 175 active items, 28 features
- **Performance:** Backtest WMAPE 38.7% ± 5.1% · Test WMAPE 37.9% · Bias +0.5%
- **Baseline beaten:** EWMA baseline WMAPE 52.9%
- **Top features:** item_dow_avg (dominant), month, cycle_on_special, lagged same-day-of-week sales
- **52% of items (147/281) are highly intermittent** — managed with minimum-stock rules, not volume forecasts

### Weekly workflow
1. Export POS → drag onto `Launch Import Sales.bat`
2. Create `specials_this_week.csv` and `stock_on_hand_v2.csv`
3. Open ordering app (`Launch Order App.bat`) → forecast auto-generates order list

---

## Key Business Findings (as of Q1 2026)

- **Waste crisis:** REDUCED FV markdown lines/day up 511.9% YoY (1.35 → 8.24/day). Target: <5.0/day.
- **GP margin stable:** 37.3% (2025) → 37.8% (2026). Pricing model is sound.
- **Revenue/day down 6.4% YoY** — demand softness, not pricing.
- **Margin trap items:** Green Grapes, Baby Lebanese Cucumbers — price increases caused volume drops. Trial rollback recommended.
- **Open-ring scanning:** ~2.1 lines/day without PLU — contaminates item-level data. Needs fixing.
- **Rising stars (new A-class 2026):** Broccolini, Cauliflower, Cherries, Nectarines, Pumpkin, Sliced Watermelon, Stirfry Mixed Veg.

---

## Performance Targets

| Metric | Target | Current (Apr 2026) |
|---|---|---|
| Waste as % of Revenue | < 5% | ~1.3% (8 days tracked) |
| Markdown lines/day | < 5.0 | ~8.24 |
| GP% | > 37% | 36.6% |
| Forecast WMAPE | < 35% | 38.7% |
| Stockout rate | < 5% | Not yet tracked |

---

## Next Phase — GAP POS Price Integration (Planned)

### Goal
Automatically push approved price changes from our system directly into the GAP EM POS, eliminating the manual re-entry step after the pricing review.

### What we know about GAP EM POS
- **Vendor:** GaP Solutions (Adelaide, SA) — Australian-owned POS software, 27+ years, used by Drakes, Supabarn, Spudshed.
- **Backend:** MySQL (on Oracle Cloud Infrastructure / EM Cloud™).
- **Integration product:** EM Integration — described as supporting "warehouse host files for up-to-date pricing and specials." This is the primary integration mechanism used by wholesalers (e.g. Metcash/IGA) to push price updates into the system.
- **Confirmed capability:** GaP has built automated price push integrations before (SA Fuel Pricing Scheme uses direct API submission from EM POS).
- **No public API documented.**

### Integration paths (in order of feasibility)

| Path | Description | Effort | Requires |
|---|---|---|---|
| **Host file import** | Drop a structured CSV/file in the format EM Integration expects. GaP processes it and updates prices. | Low (once format is known) | GaP Solutions support call to get file spec |
| **Reverse-engineer export format** | Our sales exports from GAP reveal the data format. Use same format in reverse as import. | Medium | Compare export columns to price update requirements |
| **Direct MySQL write** | Write approved prices directly to the EM Cloud MySQL DB. | Low (code-wise) | DB credentials from GaP — unlikely without formal agreement |
| **UI automation** | Use pyautogui to drive the GAP interface. | High, fragile | Nothing external |

### Recommended first step
Call GaP Solutions support and ask:
1. *"Does EM Integration support importing a price update file? What format does it expect?"*
2. *"Can we get the column specification for a host file price import?"*

### What's already in place
- `ref_item_price` has current sell + cost prices per PLU/product.
- `fact_invoice` logs every approved invoice price change with date and source.
- `generate_price_updates.py` already writes approved prices to the DB. Adding a GAP export step at the `--apply` stage is a small addition once the file format is known.
- The data needed (PLU, product name, sell price) is all present and clean.

### Deferred decision
Price sensitivity GP% tiers — revisit flat 40% GP% target using `item_price_sensitivity.csv` once GAP integration is live and price changes can be applied efficiently.

---

## Reference Files

| File | Description |
|---|---|
| `01_data/reference/item_price.csv` | Current sell/cost prices (CSV backup of ref_item_price) |
| `01_data/reference/invoice_item_mapping.csv` | Invoice description → POS item mapping (CSV backup) |
| `01_data/reference/item_price_sensitivity.csv` | Price elasticity data — deferred to post-integration phase |
| `01_data/reference/specials_mapping.csv` | Freshlink specials bulletin → POS item mapping |
| `06_reports/Performance_Dashboard_Reference.md` | Full KPI reference for panel.py |
| `sql_reference.html` | Common SQL queries for DB Browser or direct analysis |
