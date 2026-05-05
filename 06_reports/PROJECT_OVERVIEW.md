# Fruit & Veg Forecasting Project — Feature Overview
**Foodland Wudinna, SA, Australia**
Last updated: April 2026

---

## Project Goal

Replace ad-hoc ordering with a data-driven pipeline that reduces waste, prevents stockouts, and tracks performance over time. The project is built entirely on POS export data — no third-party integrations required.

---

## Store Context

| | |
|---|---|
| Location | Wudinna SA 5652 |
| Trading hours | Mon–Fri 08:30–18:00, Sat 08:30–12:00 |
| Closed | Sundays and public holidays |
| Delivery schedule | Tuesday AM and Friday AM |
| Order days | Wednesday (→ Friday delivery), Friday (→ Tuesday delivery) |

---

## Features Built

### 1. Exploratory Data Analysis
**Files:** `02_analysis/Executive_EDA_Report.ipynb`, `06_reports/Executive_EDA_Report.html`

Full analysis of 308 trading days (2025) + Q1 2026. Key findings that shaped the project:

- REDUCED FV markdown rate increased **511.9% YoY** (1.35 → 8.24 lines/day) — primary driver of GP loss
- Projected full-year GP loss at 2026 markdown rate: ~$1,207
- Revenue swing of 36% across the year (July trough → November peak)
- Friday = 1.54× average weekday demand; Saturday is smallest day
- Top 3 items (Bananas, Strawberries, Lettuce) = ~17% of revenue
- 52% of items (147/281) are highly intermittent — cannot be volume-forecast reliably
- Margin trap items identified: Green Grapes, Baby Lebanese Cucumbers (price increase → volume drop → GP loss)

---

### 2. Demand Forecast Model
**Files:** `02_analysis/FruitVeg_Demand_Forecast.ipynb`, `03_model/demand_model.pkl`

LightGBM model trained on 2025–2026 sales history. Replaces manual estimation.

| Metric | Value |
|---|---|
| Model | LightGBM (MAE objective) |
| Active items | 175 |
| Features | 28 (dow avg, month, specials flag, lags, EWMA) |
| Backtest WMAPE | 38.7% ± 5.1% (6-cycle walk-forward) |
| Test WMAPE | 37.9% |
| EWMA baseline WMAPE | 52.9% |
| Bias | +0.5% (near-neutral) |

**Top predictive features:** item_dow_avg (dominant), month, cycle_on_special, lag features.

**Fallback:** Items not in the model (new products) use an EWMA calculation automatically.

**Retraining:** Run the notebook weekly after updating sales data. Model is retrained from scratch and saved to `03_model/demand_model.pkl`.

---

### 3. Order Sheet Generator
**Files:** `app.py`, `Launch Order App.bat`
**URL:** http://localhost:8501

Streamlit app that generates a printable Stock Count Sheet for each order cycle.

**Workflow:**
1. Select order cycle (Wed→Fri, Fri→Tue, or holiday alternatives)
2. Flag items on special this cycle
3. Upload SOH export from POS (or use the folder CSV fallback)
4. App runs forecast, consolidates multi-cut items, calculates order quantities
5. Download `StockCountSheet_YYYYMMDD.xlsx` → saved automatically to `04_ordering/`

**Key features:**
- Auto-detects public holidays from `dim_calendar` and warns of affected delivery days
- SOH filter: 1–300 units (values outside range treated as data errors)
- Forecast log: every generated sheet is appended to `03_model/forecast_log.csv` for accuracy tracking; re-running the same cycle overwrites those rows

**Product consolidation** — multi-barcode variants merged into a single order row (shown in purple):

| Group | Variants | Unit |
|---|---|---|
| Cabbage | Whole / Half / Quarter | whole heads |
| Cabbage Red | Quarter | whole heads |
| Cabbage Chinese | Whole / Half | whole heads |
| Cauliflower | Per Each / Half | whole heads |
| Celery | Large / Half | whole stalks |
| Watermelon | Seedless Per Kg / Sliced | kg |
| Rockmelon | Per Kg / Sliced | kg |

---

### 4. Performance Panel
**Files:** `panel.py`, `Launch Performance Panel.bat`
**URL:** http://localhost:8505

Streamlit dashboard for tracking the three performance pillars.

| Section | What it shows |
|---|---|
| Summary KPIs | Total waste cost, binned vs reduced, daily average, waste as % of revenue |
| Waste Trends | Weekly waste cost by action (stacked bar), breakdown by reason (pie) |
| Top Offenders | Items ranked by waste cost; waste rate = waste qty ÷ (sold + waste) |
| Sales & GP | Weekly revenue vs waste overlay, GP % trend, weekly summary table |
| Lost Sales | Stockout events, estimated lost revenue, top items, trend over time |
| Waste Log Detail | Full filterable log with cost recalculation |

**Waste cost calculation:** Uses cost price (Cost Ex GST ÷ Qty from sales CSV), not sell price. Using sell price overstates loss by ~37% GP margin.
- Binned items: `Qty × cost_per_unit`
- Reduced items: `Qty × max(cost_per_unit − new_price, 0)`

**Data source:** `05_waste/FruitVeg_Waste_Log_v2.xlsx` (Weekly Entry sheet)

**Industry benchmarks tracked:**

| Metric | Target |
|---|---|
| Waste as % of Revenue | < 5% |
| Waste Rate per item | < 10% |
| Stockout Rate | < 5% |
| GP % (F&V) | > 30% |

---

### 5. Waste Log
**File:** `05_waste/FruitVeg_Waste_Log_v2.xlsx`

Manual log for recording daily waste events. Each row = one item, one day.

**Columns:** Date | Day | Item Name | Qty | Unit | Price (cost, via VLOOKUP) | Action | New Price | Reason | Waste Cost | Notes

**Actions:** Binned, Reduced, Stir Fry, Donated
**Price column:** VLOOKUP against `item_price` sheet → pulls cost price (column 3)
**Waste Cost formula:** `=Qty × MAX(Price − New Price, 0)` — the MAX guard prevents negative values on markdowns sold above cost

**Reference prices:** `01_data/reference/item_price.csv` — Name | Sell Price (manual) | Sell Price (from sales CSV) | Cost Price (derived)

---

### 6. Stockout Detector
**Files:** `detect_stockouts.py`, `Launch Stockout Detector.bat`

Detects stockout events from a SOH export and estimates lost revenue. Drag and drop a SOH file onto the bat file to run.

**Genuine stockout criteria (all must be true):**
- SOH ≤ 0 and SOH > −500 (excludes POS bulk/kg data errors)
- AWS > 0 (item is actively selling, not discontinued)
- Last Sold within 30 days (confirms it was live)
- Last Sold < report date (confirms it ran out before the report was taken)

**Lost revenue calculation:**
- `daily_qty` = median from sales CSV last 8 weeks (falls back to SOH AWS ÷ 7)
- `lost_days` = store-open trading days from Last Sold to next delivery (exclusive)
- `lost_revenue` = `lost_days × daily_qty × avg_price`

**Output:** Appends to `05_waste/Stockout_Log.csv`. De-duplicates by `(report_date, item_name)` — re-running on the same SOH file is safe.

**Expected cadence:** Run after each order cycle when you pull the SOH report for stock counting.

---

### 7. Forecast Log
**File:** `03_model/forecast_log.csv`

Automatically written every time the Order Sheet Generator runs.

**Schema:** `order_date | order_type | delivery_date | item_name | subdept | is_consolidated | predicted_qty | order_qty`

**Purpose:** Enables future actuals-vs-forecast accuracy tracking in the Performance Panel. Once 4–6 cycles of data accumulate, WMAPE per cycle can be calculated directly from this log vs the sales CSV.

**De-duplication:** Rows with the same `(order_date, order_type)` are replaced on each run — testing the app never duplicates entries.

---

### 8. PowerBI Data Pipeline
**Folder:** `07_powerbi/`

Builder scripts that transform raw POS exports into star-schema CSVs for Power BI.

| Script | Output | Description |
|---|---|---|
| `build_dim_calendar.py` | `data/dim_calendar.csv` | Date spine with store hours, public holidays, is_store_open flag |
| `build_dim_item.py` | `data/dim_item.csv` | Item master with sub-department, ABC class, active flag |
| `build_fact_sales.py` | `data/fact_sales.csv` | Transactional sales grain |
| `build_fact_promotions.py` | `data/fact_promotions.csv` | Promotions/specials history |

`dim_calendar.csv` is also used by `app.py` and `detect_stockouts.py` for trading day calculations and delivery date logic.

---

## Folder Structure

```
foodland_wudinna/
├── 01_data/
│   ├── raw/                        Sales CSVs (2025, 2026)
│   ├── operational/                SOH exports, specials, supplier prices
│   └── reference/                  Item price list, item reference, sensitivity
├── 02_analysis/                    Jupyter notebooks (EDA, forecast, Easter)
│   └── charts/                     Saved chart exports
├── 03_model/                       Trained model pkl + forecast log
├── 04_ordering/                    Generated StockCountSheet files
├── 05_waste/                       Waste log, stockout log, weekly PDFs
├── 06_reports/                     Presentation, project plan, KPI framework
├── 07_powerbi/                     Builder scripts + star-schema CSVs
├── app.py                          Order Sheet Generator (port 8501)
├── panel.py                        Performance Panel (port 8505)
├── detect_stockouts.py             Stockout detector script
├── predict.py                      LightGBM inference module (used by app.py)
├── requirements.txt                Python dependencies
├── Launch Order App.bat            Start order sheet generator
├── Launch Performance Panel.bat    Start performance panel
└── Launch Stockout Detector.bat    Run stockout detection (drag SOH file onto this)
```

---

## Current Model Performance (April 2026)

| Metric | Value | Target |
|---|---|---|
| Forecast WMAPE (backtest) | 38.7% ± 5.1% | < 35% |
| Forecast bias | +0.5% | < ±5% |
| Waste as % of Revenue | ~1.3% (8 days data) | < 5% |
| Markdown lines/day | 8.24 (pre-model baseline) | < 5.0 |
| GP % | 36.6% | > 37% |

> Note: The waste and stockout KPIs will become meaningful after 8–12 weeks of consistent logging. The first 8 weeks serve as the post-model baseline.

---

## Next Phase

- [ ] Actuals-vs-forecast accuracy section in panel (requires ~6 cycles in `forecast_log.csv`)
- [ ] Automate SOH parsing into `stock_on_hand_v2.csv` from the weekly POS export
- [ ] Retrain model with autumn/winter 2026 data as it becomes available
- [ ] Price rollback trial on Margin Trap items (Green Grapes, Baby Lebanese Cucumbers)
- [ ] Resolve open-ring scanning (PLU assignment + cashier retraining)
