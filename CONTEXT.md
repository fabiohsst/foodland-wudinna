# Project Context — Foodland Wudinna Fruit & Veg
**Last updated: 12 April 2026 (specials tracking + W1/W2 split)**

This file is the single reference document for the project. It summarises every component, its purpose, its files, and how pieces connect. Consult it at the start of any session.

---

## Business Context

| | |
|---|---|
| Store | Foodland Wudinna, SA 5652, Australia |
| Department | Fruit & Vegetable (F&V) |
| Trading hours | Mon–Fri 08:30–18:00 · Sat 08:30–12:00 · Sun/Public Holidays: Closed |
| Order days | Wednesday (→ Friday AM delivery) · Friday (→ Tuesday AM delivery) |
| Delivery days | Tuesday AM · Friday AM |

**Core problem:** Ad-hoc manual ordering led to a 511.9% increase in markdown lines (1.35/day in 2025 → 8.24/day in 2026), overstocking perishables, stockouts on high-velocity items, and GP% trending below target. The project replaces gut-feel ordering with a data-driven pipeline.

---

## Folder Structure

```
foodland_wudinna/
├── 01_data/
│   ├── raw/                    POS sales exports (2025, 2026 CSVs)
│   ├── operational/            SOH exports, specials CSV, supplier prices
│   └── reference/              Item price list, item reference, price sensitivity
├── 02_analysis/                Jupyter notebooks: EDA, forecast model, Easter
│   └── charts/                 Saved chart images from notebooks
├── 03_model/                   Trained LightGBM pkl + forecast log CSV
├── 04_ordering/                Generated StockCountSheet Excel files per cycle
├── 05_waste/                   Waste log (Excel), stockout log (CSV), weekly PDFs
├── 06_reports/                 Presentations, project plan, KPI framework docs
├── 07_powerbi/                 Star-schema builder scripts + CSV output files
│   └── data/                   dim_calendar, dim_item, fact_sales, fact_promotions
├── dash/                       Streamlit dashboard module (5 sub-pages)
├── _archive/                   Deprecated scripts and source images
├── app.py                      Order Sheet Generator (port 8501)
├── panel.py                    Performance Panel (port 8505)
├── dashboard.py                Store Dashboard entry point (port 8506)
├── detect_stockouts.py         Stockout detection script (drag-and-drop)
├── predict.py                  LightGBM inference module
└── requirements.txt            streamlit, pandas, numpy, openpyxl, lightgbm, scikit-learn, plotly
```

---

## Section 1 — Exploratory Data Analysis (EDA)

### Files
- `02_analysis/Executive_EDA_Report.ipynb` — main EDA notebook (308 trading days, 2025 + Q1 2026)
- `02_analysis/Easter_2026_EDA_Forecast.ipynb` — Easter 2026 demand uplift analysis
- `02_analysis/eda.md` — cell-by-cell guide for the EDA notebook
- `06_reports/Executive_EDA_Report.html` — exported HTML report
- `02_analysis/charts/` — saved PNG exports from the notebooks

### What was analysed
- Sales trends: daily, weekly, monthly heatmap, day-of-week profiles
- Sub-department breakdown and Pareto analysis
- GP% distribution, negative-margin events, extreme-margin flags
- Year-over-year comparison (2025 vs 2026)
- Operational efficiency: scans (Lines) vs quantity, high-scan/low-revenue items
- Product type split: loose per-kg vs pre-packaged

### Key findings that shaped the project
| Finding | Impact |
|---|---|
| Markdown rate +511.9% YoY (1.35 → 8.24 lines/day) | Primary driver of GP loss; projected $1,207 full-year impact |
| Revenue swings ±36% across the year (July trough, November peak) | Model needs seasonal features |
| Friday = 1.54× average weekday demand | Friday cycle ordering is highest-stakes |
| 52% of items (147/281) are highly intermittent | Cannot be volume-forecast; EWMA fallback used |
| Top 3 items (Bananas, Strawberries, Lettuce) ≈ 17% of revenue | A-class items need accurate forecasts |
| Margin trap items: Green Grapes, Baby Lebanese Cucumbers | Price increase → volume drop → net GP loss |

### Easter 2026 uplift (from Easter_2026_EDA_Forecast.ipynb)
- Easter 2025 used as historical baseline for category uplift factors
- Output: `04_ordering/Easter_2026_Qty_Forecast.xlsx` and `04_ordering/easter_2026_item_forecast.csv`
- Uplift factors applied per sub-department to the standard cycle forecast

---

## Section 2 — Raw Data

### Source files
| File | Rows | Description |
|---|---|---|
| `01_data/raw/sales_fruit_2025.csv` | ~36,400 | Full 2025 POS transaction data |
| `01_data/raw/sales_fruit_2026.csv` | ~9,450 | 2026 YTD (updated weekly) |

### Schema (both files identical)
`Date · Store Name · Department Name · APN · Name · Sales Inc GST · Cost Ex GST · Cost Inc GST · GP % · GP $ · Lines · Online Sales Inc · Online Sales Ex · Quantity · Sales Ex GST · Store Sales Ex · Store Sales Inc`

**Key columns used in the model:**
- `Name` — normalised item name (primary join key across all files)
- `Quantity` — units sold (target variable for forecasting)
- `Date` — transaction date
- `Sales Ex GST` — revenue excluding GST
- `GP $` / `GP %` — gross profit
- `Cost Ex GST` — used to derive cost price per unit for waste calculations

### Data quality notes
- POS exports item names in ALL CAPS; normalisation (collapse whitespace, strip) is applied everywhere via `norm()` function
- Items sold loose by kg show erratic SOH values (e.g. −187,952); filtered using SOH > −500 guard
- `APN` (barcode) is sometimes absent for PLU-scanned items (open-ring scanning issue, flagged as open action item)

---

## Section 3 — Reference Data

### Files
| File | Contents |
|---|---|
| `01_data/reference/item_reference.csv` | Item master — PLU, APN, sub-department, active flag |
| `01_data/reference/item_price.csv` | Name · Sell Price (manual) · Sell Price (from sales) · Cost Price (derived) |
| `01_data/reference/item_price_sensitivity.csv` | Name · is_price_sensitive · item_avg_sell_price |
| `01_data/reference/sa_holidays_prophet.csv` | SA public holiday dates in Prophet format (ds · holiday) |
| `01_data/reference/prepacked_labelled.csv` | Items manually labelled as pre-packed vs loose |
| `01_data/reference/specials_reconstruction.csv` | Historical specials reconstructed from price anomaly detection |
| `01_data/reference/specials_mapping.csv` | Bulletin description → POS item name mapping (used by parse_specials_sheet.py) |

### Operational reference
| File | Contents |
|---|---|
| `01_data/operational/stock_on_hand_v2.csv` | Processed SOH — Name · Stock · Source (system/manual) |
| `01_data/operational/specials_this_week.csv` | Items flagged on special for current cycle (output of parse_specials_sheet.py) |
| `01_data/operational/supplier_prices_template.csv` | Template for weekly supplier price sheet |
| `01_data/operational/parse_specials_sheet.py` | CLI script to ingest weekly bulletin (image or XLSX) → specials_this_week.csv |

---

## Section 4 — Data Pipeline (PowerBI Star Schema)

### Purpose
Transform raw POS exports into a star schema for Power BI reporting. Also serves as the source for `dim_calendar.csv`, which is used by `app.py` and `detect_stockouts.py` for all trading day calculations.

### Builder scripts (`07_powerbi/`)
| Script | Output | Description |
|---|---|---|
| `build_dim_calendar.py` | `data/dim_calendar.csv` | Date spine 2025–2027 with store hours, SA public holidays, is_store_open, is_order_day, is_delivery_day, order_cycle |
| `build_dim_item.py` | `data/dim_item.csv` | Item master — PLU, APN, name, sub-department, ABC class, revenue_2025 |
| `build_fact_sales.py` | `data/fact_sales.csv` | Transaction grain — date_key, item_key, quantity, revenue, GP, cost |
| `build_fact_promotions.py` | `data/fact_promotions.csv` | Promotions history — event_type (Special/Markdown), GP loss vs baseline, cycle GP% |

### dim_calendar schema (critical — used by all scripts)
`date_key · date · year · quarter · month · month_name · week_of_year · day_of_week · day_name · is_weekend · is_public_holiday · holiday_name · is_store_open · is_order_day · is_delivery_day · order_cycle`

### ABC Classification logic (in dim_item)
- **A** = top 80% cumulative revenue
- **B** = next 15%
- **C** = bottom 5%

### Power BI DAX measures (`07_powerbi/PowerBI_DAX_Reference.md`)
Covers: Revenue, Revenue LY, YoY%, Rev per Trading Day, GP$, GP%, Markdown Events, GP Loss, Forecast WMAPE (pending fact_forecast table).
Pages defined: Sales Overview · Item Performance · Promotions & Markdowns · Model Accuracy (pending).

---

## Section 5 — Machine Learning Model

### Files
| File | Description |
|---|---|
| `02_analysis/FruitVeg_Demand_Forecast.ipynb` | Training notebook — feature engineering, walk-forward backtest, model export |
| `03_model/demand_model.pkl` | Trained model binary — contains model, feature_cols, item_stats, item_dow, active_items, alpha, season_map, public_holidays |
| `predict.py` | Inference module — `load_model()` + `predict_cycle()` |

### Model specification
| | |
|---|---|
| Algorithm | LightGBM (MAE objective) |
| Active items | 175 |
| Features | 28 |
| Backtest WMAPE | 38.7% ± 5.1% (6-cycle walk-forward) |
| Test WMAPE | 37.9% |
| EWMA baseline WMAPE | 52.9% |
| Forecast bias | +0.5% (near-neutral) |
| Retrain frequency | Weekly (Monday), full retrain from scratch |

### Feature set (28 features)
**Temporal:** `dow · month · day_of_month · days_since_wed · is_saturday · is_friday · is_monday · is_holiday · season`

**Item statistics (from training history):** `item_avg_qty · item_std_qty · item_max_qty · item_avg_lines · item_pct_zero · item_dow_avg`

**Same-weekday lags (6 lags):** `sdow_lag1` to `sdow_lag6` — most recent 6 occurrences of the same day-of-week

**Derived from lags:** `sdow_ma4 · sdow_ma6 · sdow_ewma · sdow_cv · sdow_trend`

**Promotional:** `cycle_on_special`

**Price:** `price_ratio · is_price_sensitive`

### Inference flow (predict.py)
1. Load model pkl via `load_model()` — normalises item names, converts public holidays to Timestamps
2. For each item × each cycle date: compute same-weekday lags from live sales data, build 28-feature vector
3. LightGBM predicts quantity; clipped at 0
4. **Fallback:** items not in the model (new products) use `ewma_forecast()` — exponentially weighted average of same-weekday history
5. **Price feature:** if `supplier_prices_YYYYMMDD.csv` exists for the cycle week, `price_ratio` reflects actual upcoming price vs historical average; otherwise uses recent sales average

### Retrain procedure
Run `FruitVeg_Demand_Forecast.ipynb` top to bottom after updating sales CSVs. Model is exported to `03_model/demand_model.pkl` automatically.

---

## Section 6 — Order Sheet Generator (app.py)

### Launch
`Launch Order App.bat` → `http://localhost:8501`

### What it does
Generates a `SCS_{Supplier}_{YYYYMMDD}.xlsx` stock count sheet for each order cycle and supplier. Combines demand forecast with current SOH to produce per-item order quantities. The supplier selection scopes the entire session — items, specials, and output.

### Supplier split
The F&V range is split across four suppliers. Each is selected from a dropdown at the top of Section 1. Items are matched by name prefix (case-insensitive).

| Supplier | Item name prefixes | Output |
|---|---|---|
| **Freshlink** | Everything not claimed below | Stock Count Sheet (standard process) |
| **Bowlsome** | `BOWLSOME…` · `COMM CO…` | Email order text + audit SCS |
| **Local Kitchen** | `L/C…` · `L/K…` · `LK …` | Email order text + audit SCS |
| **Simply Tasty** | `S/TASTY…` | Email order text + audit SCS |

**Freshlink** — full stock count sheet process, unchanged. Primary output is the Excel download.

**Bowlsome / Local Kitchen / Simply Tasty** — Section 5 generates a ready-to-copy email body (subject line, delivery date, cycle coverage, item × qty table, manual-count items listed separately, store sign-off). A secondary download button provides the SCS Excel for audit. Both are saved to `04_ordering/SCS_{Supplier}_{date}.xlsx`.

The prefix list is defined in the `SUPPLIER_PREFIXES` constant near the top of `app.py` — add new suppliers or adjust patterns there.

### Order cycles
| Cycle | Order day | Delivery | Coverage days |
|---|---|---|---|
| WED_FRI | Wednesday | Friday AM | Fri · Sat · Mon |
| FRI_TUE | Friday | Tuesday AM | Tue · Wed · Thu |
| HOL_TUE_WED | Tuesday (holiday variant) | Wednesday night | Thu onwards |
| HOL_THU_TUE | Thursday (holiday variant) | Tuesday night | Wed · Thu · Fri · Sat |

Holiday cycles are auto-detected if the standard delivery day falls on a SA public holiday.

### Pre-delivery depletion (SOH projection)
Between placing the order and the delivery arriving, the store keeps trading. The app forecasts sales for each pre-delivery trading day and subtracts this from the current SOH to get **SOH at Delivery**.

**Day weights applied:**
- Order day (today, after 12:00): **0.4** (40% of a normal day remaining)
- All other trading days (including Saturday): **1.0**

Saturday does not receive a separate hour-fraction weight. The model is trained on actual Saturday sales history, so its shorter trading hours (08:30–12:00) are already embedded in the forecast output. Applying an additional `3.5/9.5` multiplier would double-count the effect.

The pre-delivery forecast uses the same LightGBM/EWMA model as the cycle forecast.

### Product consolidation
Multi-barcode variants are merged into a single order row (shown in purple):

| Group | Variants | Order unit |
|---|---|---|
| Cabbage | Whole / Half / Quarter | whole heads |
| Cabbage Red | Quarter | whole heads |
| Cabbage Chinese | Whole / Half | whole heads |
| Cauliflower | Per Each / Half | whole heads |
| Celery | Large / Half | whole stalks |
| Watermelon | Seedless Per Kg / Sliced | kg |
| Rockmelon | Per Kg / Sliced | kg |

### SOH upload
- Accepts the raw POS SOH Excel export (auto-detects the header row by scanning for "GTIN" or "Description")
- Falls back to `01_data/operational/stock_on_hand_v2.csv` if no file uploaded
- SOH filter: 1–300 units (values outside range are treated as POS data errors)

### Specials — W1 / W2 split (FRI_TUE cycles)
Foodland specials bulletins run **Wednesday → Tuesday**. For the FRI_TUE cycle (Tue · Wed · Thu), Tuesday is the final day of the current bulletin (W1) and Wednesday+Thursday are the first days of the next bulletin (W2).

The app shows **two separate specials multiselects** when FRI_TUE is selected — one per bulletin week. The model's `cycle_on_special` feature is set per day to the correct week's list. Items on special are tagged in the output with **W1**, **W2**, or **W1+W2**.

For single-week cycles (WED_FRI, HOL variants), a single multiselect is shown; all specials are labelled W1.

### Specials ingestion tool (01_data/operational/parse_specials_sheet.py)
CLI script that reads a weekly bulletin image (JPEG/PNG) or catalogue file (XLSX) and resolves items to POS names using `specials_mapping.csv`. Currently requires manual confirmation at the terminal (OCR/LLM extraction scaffolded for a future iteration). Output goes to `specials_this_week.csv`.

Usage: `python 01_data/operational/parse_specials_sheet.py --bulletin path/to/bulletin.jpg`

### Output columns in StockCountSheet
`# · Item Name · Special · [Day forecasts] · Total Forecast · SOH Now · Fc to Deliv. · SOH at Del. · Order Qty · Notes`

| Column | Description |
|---|---|
| Special | Specials week indicator: blank (not on special) · W1 · W2 · W1+W2 |
| Day forecasts | One column per trading day in the cycle |
| Total Forecast | Sum of day forecasts |
| SOH Now | Current stock on hand (from POS upload) |
| Fc to Deliv. | Model forecast for each pre-delivery trading day, weighted (order day × 0.4, all others × 1.0) |
| SOH at Del. | SOH Now − Fc to Deliv. (projected stock when delivery arrives) |
| Order Qty | Total Forecast − SOH at Del. (floored at 0) |

- Blue rows = system-tracked (SOH pre-filled from POS)
- White/grey rows = manual count required
- Purple rows = consolidated multi-cut items

**File naming:** `SCS_{Supplier}_{YYYYMMDD}.xlsx` — saved to `04_ordering/` automatically on every run.

### Forecast log
Every run appends to `03_model/forecast_log.csv`. Re-running the same cycle overwrites those rows (deduplication by `order_date + order_type`).

**Schema:** `order_date · order_type · delivery_date · item_name · subdept · is_consolidated · predicted_qty · order_qty`

---

## Section 7 — Waste & Stockout Tracking

### Waste log
**File:** `05_waste/FruitVeg_Waste_Log_v2.xlsx` — Weekly Entry sheet

**Columns:** `Date · Day · Item Name · Qty · Unit · Price (cost, VLOOKUP) · Action · New Price · Reason · Waste Cost · Notes`

**Actions:** Binned · Reduced · Stir Fry · Donated

**Waste cost formula:** `Qty × MAX(Cost Price − New Price, 0)`
- Binned items: New Price = 0, so cost = full cost price
- Reduced items: recovers portion of cost; only the unrecovered gap counts as waste cost

**Important:** Waste cost uses **cost price** (not sell price). Using sell price overstates the loss by ~37% (the GP margin). Cost price = `Cost Ex GST ÷ Quantity` (median per item from sales CSV).

### Stockout detector
**File:** `detect_stockouts.py`
**Launch:** `Launch Stockout Detector.bat` (drag SOH Excel file onto it)

**Genuine stockout criteria (all must be true):**
- SOH ≤ 0 and SOH > −500 (excludes kg bulk POS errors)
- AWS > 0 (item is actively selling)
- Last Sold within 30 days
- Last Sold < report date

**Lost revenue estimate:**
- `daily_qty` = median from sales CSV (last 8 weeks); falls back to SOH AWS ÷ 7
- `lost_days` = store-open trading days from Last Sold to next delivery (calendar-aware)
- `lost_revenue` = lost_days × daily_qty × avg_price

**Output:** `05_waste/Stockout_Log.csv`
**Schema:** `report_date · item_name · soh · last_sold · next_delivery · lost_days · daily_qty · avg_price · lost_revenue`

---

## Section 8 — Performance Panel (panel.py)

### Launch
`Launch Performance Panel.bat` → `http://localhost:8505`

### Sections
| Section | What it shows |
|---|---|
| Summary KPIs | Total waste cost · binned vs reduced split · daily average · waste as % of revenue |
| Waste Trends | Weekly stacked bar (by action) · waste by reason (pie) |
| Top Offenders | Items ranked by waste cost; waste rate = waste qty ÷ (sold qty + waste qty) |
| Sales & GP | Weekly revenue vs waste overlay · GP% trend (37% target) · weekly summary table |
| Lost Sales | Stockout events · est. lost revenue · top items · trend over time (requires Stockout_Log.csv) |
| Waste Log Detail | Full filterable log with recalculated waste cost |

### Industry benchmarks (tracked in panel)
| Metric | Target | Industry average |
|---|---|---|
| Waste as % of Revenue | < 5% | 8–12% |
| Waste Rate per item | < 10% | 15–25% |
| Markdown lines/day | < 5.0 | n/a |
| Stockout rate | < 5% | 9–11% |
| GP % | > 37% | 30–35% |
| Forecast WMAPE | < 35% | n/a |

---

## Section 9 — Store Dashboard (dashboard.py + dash/)

### Launch
`Launch Dashboard.bat` → `http://localhost:8506`

### Structure
Entry point `dashboard.py` provides a top-bar button navigation linking to 5 sub-pages in `dash/`:

| Page | File | Status | Description |
|---|---|---|---|
| 📈 Store Pulse | `dash/pulse.py` | Active | 5 KPI cards · weekly revenue bar · GP% line · DoW average · sub-dept pie · trading calendar |
| 🛒 Category Intelligence | `dash/category.py` | Active | Sub-dept KPIs · weekly stacked bar · GP% by sub-dept · Top N items · Bottom 20 · ABC classification · YoY movers |
| ♻️ Waste & Operations | `dash/waste.py` | Active | Waste KPIs · weekly stacked bar · reason pie · top offenders table · stockout summary |
| 🏷️ Promotions | `dash/promotions.py` | Phase 2 (auto-activates with 3+ specials cycles) | Volume lift · GP delta vs baseline |
| 🎯 Ordering Accuracy | `dash/ordering.py` | Phase 3 (auto-activates with 4+ forecast cycles) | WMAPE per cycle · bias · per-item accuracy table |

### Shared utilities (`dash/common.py`)
- `ROOT` path and all file path constants
- Color palette: `C` dict (primary/success/warning/danger) + `SUBDEPT_COLORS`
- `norm()` — name normalisation
- `load_sales()`, `load_calendar()`, `load_waste()`, `load_stockout()`

---

## Section 10 — Key Design Decisions

| Decision | Rationale |
|---|---|
| Cost price for waste cost (not sell price) | Sell price overstates loss by ~37% GP margin. Cost = actual cash outlay. |
| Pre-delivery depletion uses forecast (not flat rate) | Each item has a different sales velocity; using its own model forecast is more accurate than a daily average |
| Order day weight = 0.4 | Orders go out after 12:00; roughly 40% of normal day's sales remain |
| Saturday weight = 1.0 (no extra multiplier) | The model is trained on actual Saturday sales history; shorter hours are already embedded in predictions via `is_saturday` and `item_dow_avg`. Applying `3.5/9.5` separately would double-count the effect. |
| FRI_TUE specials split into W1 / W2 | The cycle spans two specials bulletins (Tue = W1 end, Wed–Thu = W2 start). Specials must be applied to the correct days to keep `cycle_on_special` accurate. |
| SOH filter 1–300 | Values outside range are POS inaccuracies (confirmed from bulk kg items and system drift) |
| Active item filter: last 2 weeks OR on special | Prevents seasonal/discontinued items polluting the order sheet |
| EWMA fallback for new items | Items not in the trained model still get a reasonable estimate from recent same-weekday history |
| Forecast log deduplication by (order_date, order_type) | Re-running app for testing never creates duplicate log entries |
| No pre-model baseline recorded | First 8–12 weeks of post-go-live tracked data serve as the internal baseline |

---

## Section 11 — Current Performance (April 2026)

| Metric | Value | Target | Status |
|---|---|---|---|
| Forecast WMAPE (backtest) | 38.7% ± 5.1% | < 35% | ⚠️ Close — retrain with autumn data |
| Forecast bias | +0.5% | < ±5% | ✅ Near-neutral |
| EWMA baseline WMAPE | 52.9% | — | Model outperforms by ~15pp |
| Waste as % of Revenue | ~1.3% (8 days data) | < 5% | ✅ (early data) |
| Markdown lines/day | 8.24 (pre-model baseline) | < 5.0 | ⏳ Measuring |
| GP % | 36.6% | > 37% | ⚠️ Just below target |

---

## Section 12 — Price Management Module

### Overview

Automates sell price updates from supplier delivery invoices. The goal is to eliminate manual price checking after each delivery by computing cost-based suggested prices, flagging significant changes, and requiring human approval only for flagged items.

### Directory Structure

```
pricing/
├── invoices/                   # Raw invoice CSVs (one file per delivery)
│   └── freshlink_20260407.csv  # Freshlink Invoice #8283 (07/04/2026)
├── reviews/                    # Generated review spreadsheets (open → approve → apply)
│   └── price_review_07042026.xlsx
└── generate_price_updates.py   # Main script (generate + apply)

01_data/reference/
├── invoice_item_mapping.csv    # Maps invoice descriptions → POS item names
└── price_history.csv           # Cost/sell history by invoice date (appended per run)
```

### Invoice Item Mapping (`invoice_item_mapping.csv`)

Maps supplier invoice line descriptions to POS item names and handles unit conversion.

| Column | Description |
|---|---|
| `invoice_description` | Exact description from the invoice CSV |
| `pos_name` | Matching POS item name (from `item_price.csv`) |
| `units_per_invoice` | Units per invoice quantity (e.g. 12 for a 12kg CTN; 90 for a 90's kiwifruit box) |
| `sell_unit` | `kg` or `each` |
| `supplier` | Supplier name (e.g. Freshlink) |
| `verified` | `true` = POS name confirmed; `false` = needs checking |
| `notes` | Any caveats (e.g. "1 whole red cabbage = 4 quarters in POS") |

Key mapping notes:
- Items invoiced per carton (e.g. "APPLES - PINK LADY - 12 KG CTN") divide by `units_per_invoice` to get cost per kg/each
- "WATERMELON - SEEDLESS - KG" has `units_per_invoice=1` (already invoiced per kg)
- "CABBAGE - RED" has `units_per_invoice=4` (sold as quarters in POS)
- Multiple herbs map to "FRESH HERBS" (`verified=false`) — verify if separate POS items exist
- Duplicate POS items (two invoice lines → same POS item): lower cost wins; noted in review

### Pricing Rules

| Rule | Value |
|---|---|
| GP target | 40% (`sell = cost / 0.60`) |
| Rounding | Round UP to next price ending in 9 (e.g. $0.23 → $0.29, $2.00 → $2.09) |
| Flag threshold | Cost change ≥ 15% OR sell price change ≥ 15% vs previous invoice |
| On-special items | Never modified — skipped automatically (cross-ref `specials_this_week.csv`) |
| Unverified mappings | Automatically flagged for review regardless of price change |
| Auto-approve | Only if: no flag, verified=true, not on special |

### Workflow

**Step 1 — Generate review sheet:**
```
python pricing/generate_price_updates.py --invoice pricing/invoices/freshlink_YYYYMMDD.csv
```
Output: `pricing/reviews/price_review_DDMMYYYY.xlsx`
- Green rows = auto-approved
- Red rows = flagged (review required)
- Blue rows = on special (skipped)

**Step 2 — Review & approve:**
Open the Excel file. For each red row: check Flag/Notes columns, adjust Approve to Y/N as appropriate.

**Step 3 — Apply approved prices:**
```
python pricing/generate_price_updates.py --apply pricing/reviews/price_review_DDMMYYYY.xlsx
```
- Creates timestamped backup: `item_price.bak_YYYYMMDD_HHMMSS.csv`
- Updates Sell Price and Cost Price in `item_price.csv`
- Appends results to `price_history.csv`

### Price History (`price_history.csv`)

Columns: `date`, `invoice_no`, `pos_name`, `cost_per_unit`, `sell_price`, `gp_pct`, `source`

Bootstrapped from `item_price.csv` baseline (236 items, dated 2026-04-07, `source=item_price_baseline`). Each subsequent invoice run appends rows with `source=invoice_XXXXX`. The most recent non-baseline row is used as the "previous cost" reference for change detection. Running the same invoice twice is idempotent (prior rows for that invoice_no are replaced).

### Adding New Invoice Descriptions

When a new invoice line isn't found in `invoice_item_mapping.csv`, it appears in the "Unmatched" section of the review sheet. To add it:
1. Find the correct POS item name in `item_price.csv`
2. Determine `units_per_invoice` and `sell_unit`
3. Add a row to `invoice_item_mapping.csv` with `verified=false` initially
4. Re-run the script

### Future Phase — GAP POS Integration

The apply step currently writes to `item_price.csv` only (local file). The next phase is to push approved prices directly to the GAP POS system, eliminating the manual step of re-entering prices at the terminal. Requires investigation of whether GAP supports CSV import, an API, or another programmatic update mechanism.

---

## Section 13 — Open Actions & Next Phase

| Item | Priority | Notes |
|---|---|---|
| Retrain model with autumn/winter 2026 data | High | WMAPE currently 38.7% — seasonal data will help |
| Actuals-vs-forecast accuracy in panel | High | Requires ~6 cycles in `forecast_log.csv` |
| Automate SOH parsing into `stock_on_hand_v2.csv` | Medium | Currently manual via `parse_soh_export.py` |
| Add OCR/LLM extraction to parse_specials_sheet.py | Medium | Currently manual CLI confirmation; automate image → POS name pipeline |
| Verify unconfirmed entries in specials_mapping.csv | Medium | ~10 items marked `verified=false` (Kestrel, Peculiar Pick variants, Mexican Burrito) |
| Verify unconfirmed entries in invoice_item_mapping.csv | Medium | ~20 items marked `verified=false`; herbs, grape variants, some tomato lines |
| Price rollback trial on margin trap items | Medium | Green Grapes, Baby Lebanese Cucumbers |
| GAP POS integration for price updates | Medium | Research GAP API / CSV import format; automate apply step to push prices to POS |
| Resolve open-ring scanning (PLU assignment) | Medium | Some items have no APN; cashier retraining needed |
| Add `fact_forecast.csv` to Power BI | Low | Unlocks Model Accuracy page (DAX measures already written) |
| Promotions dashboard (Phase 2) | Low | Auto-activates once 3+ specials cycles accumulate |
| Ordering Accuracy dashboard (Phase 3) | Low | Auto-activates once 4+ forecast cycles accumulate |

---

## Section 14 — Port Reference

| App | Port | Launch file |
|---|---|---|
| Order Sheet Generator | 8501 | `Launch Order App.bat` |
| Performance Panel | 8505 | `Launch Performance Panel.bat` — Sales & GP, Stockout only |
| Store Dashboard | 8506 | `Launch Dashboard.bat` |
| Waste Dashboard | 8507 | `Launch Waste Dashboard.bat` — Daily / weekly waste view |
| Stockout Detector | — (script) | `Launch Stockout Detector.bat` (drag SOH file) |
