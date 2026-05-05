# Fruit & Veg — Performance Dashboard Reference
**Foodland Wudinna | Fruit & Vegetable Department**
Last updated: April 2026

---

## Purpose

This document is the single reference point for the model performance tracking initiative. It defines the KPIs we are measuring, the benchmarks we are comparing against, the data sources powering each metric, and the decisions that shaped the current setup.

The core question this dashboard answers: **Is the LightGBM demand forecast model reducing waste and preventing lost sales compared to ad-hoc ordering?**

---

## Context

The department implemented a LightGBM demand forecast model in early 2026 after a waste analysis revealed a 511.9% year-on-year increase in markdown lines (1.35/day in 2025 → 8.24/day in 2026). The model generates a recommended order quantity for each cycle, covering 175 active items across the full fruit and vegetable range.

Because a pre-model baseline was not formally recorded before go-live, the first 8–12 weeks of tracked data will serve as the baseline. Industry benchmarks fill in for comparison in the interim.

---

## Measurement Framework

Three pillars, each pulling in a different direction. The model's value is in finding the efficient point between them.

### Pillar 1 — Waste Reduction

Waste happens when more stock arrives than the cycle can sell. For fresh produce, unsold stock either gets reduced (margin lost) or binned (cost lost).

| KPI | Definition | Calculation | Data Source |
|---|---|---|---|
| **Total Waste Cost** | Actual cash lost to waste | Binned: Qty × Cost Price<br>Reduced: Qty × MAX(Cost − New Price, 0) | Waste Log v2 |
| **Daily Waste Average** | Smoothed waste rate | Total Waste Cost ÷ Trading Days | Waste Log v2 |
| **Waste as % of Revenue** | Waste relative to sales volume | Waste Cost ÷ Revenue | Waste Log + Sales CSV |
| **Waste Rate by Item** | Items over-ordered most | Waste Qty ÷ (Sold Qty + Waste Qty) | Waste Log + Sales CSV |
| **Binned vs Reduced Split** | Nature of waste | Binned Cost vs Reduced Margin Cost | Waste Log v2 |
| **Markdown Lines / Day** | Early warning signal | Count of Reduced lines per trading day | Waste Log v2 |

**Cost price note:** Waste cost is calculated using `Cost Ex GST ÷ Qty` (median per item) derived from the sales CSV, not the shelf sell price. This represents the actual cash outlay — the only money that was truly lost.

### Pillar 2 — Lost Sales (Stockout Prevention)

Stockouts happen when stock runs to zero before the next delivery. The model forecast becomes the best proxy for what would have been sold.

| KPI | Definition | Calculation | Data Source |
|---|---|---|---|
| **Stockout Events** | Count of items reaching zero stock before delivery | Manual log entry | Stockout_Log.csv |
| **Estimated Lost Revenue** | Revenue not captured due to empty shelf | Forecast Daily Qty × Days Out × Sell Price | Stockout_Log.csv + model |
| **Stockout Rate** | % of item-days where stock was zero | Stockout Item-Days ÷ Total Item-Days | Stockout_Log.csv |
| **Service Level** | Inverse of stockout rate | 1 − Stockout Rate | Derived |

**How to record a stockout:** When an item reaches zero stock before delivery day, add a row to `05_waste/Stockout_Log.csv` with:
`Date | Item Name | Days Out | Forecast Daily Qty | Price`

The forecast daily qty comes from the StockCountSheet for that cycle.

### Pillar 3 — Ordering Accuracy

How well the model recommendation matched reality.

| KPI | Definition | Calculation | Data Source |
|---|---|---|---|
| **Forecast WMAPE** | Weighted mean absolute % error | Per-cycle backtest in notebook | FruitVeg_Demand_Forecast.ipynb |
| **Forecast Bias** | Systematic over/under-forecasting | (Forecast − Actual) ÷ Actual | Notebook backtest |
| **Cycle Efficiency** | How much of what arrived was sold | Units Sold ÷ Units Ordered | Sales CSV + order records |
| **GP %** | Gross profit margin | GP $ ÷ Revenue | Sales CSV |

---

## Industry Benchmarks

Used as reference while own baseline is being established. Source: AFGC, ECR Europe fresh produce studies.

| Metric | Industry Average (independent F&V) | Best-in-Class | Our Target |
|---|---|---|---|
| Waste as % of Revenue | 8–12% | 3–5% | < 5% |
| Waste Rate per item | 15–25% | 5–8% | < 10% |
| Markdown Lines / Day | — | — | < 5.0 (from 8.24 baseline) |
| Stockout Rate (item-days) | 9–11% | 3–5% | < 5% |
| Service Level | 89–91% | 95–97% | > 95% |
| Cycle Efficiency | 0.70–0.80 | 0.88–0.92 | 0.85–0.92 |
| GP % (F&V) | 30–35% | 38–42% | > 37% (current: 36.6%) |
| Forecast WMAPE | n/a (no forecast) | 25–35% | < 35% |

**Current model performance (as of April 2026):**
- Backtest WMAPE: 38.7% ± 5.1% (6-cycle walk-forward)
- Test set WMAPE: 37.9%
- EWMA baseline WMAPE: 52.9% — model outperforms by ~15 percentage points
- Bias: +0.5% (near-neutral; slight over-forecast acceptable for perishables)

---

## Data Sources & Files

| Data | File | Update Frequency | Notes |
|---|---|---|---|
| Sales history | `01_data/raw/sales_fruit_2026.csv` | Weekly (Monday) | Export from POS |
| Waste entries | `05_waste/FruitVeg_Waste_Log_v2.xlsx` → Weekly Entry | Daily (paper) → Weekly (digital) | Cost price via VLOOKUP from item_price sheet |
| Item prices | `01_data/reference/item_price.csv` | As needed | Sell Price and Cost Price derived from sales CSV |
| Stockout log | `05_waste/Stockout_Log.csv` | Per cycle | Manual entry; activates Lost Sales section in panel |
| Order forecasts | `04_ordering/StockCountSheet_YYYYMMDD.xlsx` | Per cycle | Generated by app.py |
| Calendar | `07_powerbi/data/dim_calendar.csv` | Annually | Public holidays, store open days |

---

## Dashboard — panel.py

**Launch:** Double-click `Launch Performance Panel.bat` (runs on port 8505)

### Sections

| Section | What it shows | Requires |
|---|---|---|
| Summary KPIs | Total waste cost, binned vs reduced, daily average, waste % revenue | Waste Log |
| Waste Trends | Weekly stacked bar by action; waste by reason pie | Waste Log |
| Top Offenders | Items ranked by waste cost; waste rate per item | Waste Log + Sales CSV |
| Sales & GP | Weekly revenue vs waste overlay; GP% trend; weekly table | Sales CSV |
| Lost Sales | Stockout events and estimated lost revenue | Stockout_Log.csv |
| Waste Log Detail | Full filterable log | Waste Log |

### Cost Price Logic in Panel

The panel ignores the Price column from the waste log and recalculates waste cost using `Cost Ex GST ÷ Quantity` (median per item) from the sales CSV:
- **Binned:** `Qty × Cost Price`
- **Reduced:** `Qty × MAX(Cost Price − New Price, 0)`
  Zero when the markdown price still recovers cost; the margin impact appears in GP% instead.

---

## Waste Log — How Prices Work

The Weekly Entry sheet Price column automatically looks up **cost price** from the `item_price` sheet inside the workbook:

```
=IF(C{n}="", "", IFERROR(VLOOKUP(C{n}, item_price!$A:$C, 3, FALSE), 0))
```

The `item_price` sheet has three columns: **Name | Sell Price | Cost Price**.
Both prices are derived from the sales CSV and refreshed when item_price.csv is updated.

Waste Cost formula:
```
=IF(C{n}="", "", D{n} * MAX(F{n} - H{n}, 0))
```
Where D = Qty, F = Cost Price (from VLOOKUP), H = New Price (markdown price, blank for Binned).

---

## What We Are Not Yet Measuring (and Why)

**True Waste Rate (waste ÷ ordered):** Requires recording actual ordered quantities per cycle. Currently proxied as `Waste Qty ÷ (Sold Qty + Waste Qty)`, which is directionally correct. If cycle efficiency tracking is added later, this becomes exact.

**Substitution effect:** When an item stocks out, some customers buy a substitute rather than leaving. Lost sales estimates will be slightly overstated — typically 70–85% of the modelled figure reflects true lost revenue.

**Item-level forecast accuracy:** The current backtest reports WMAPE at the aggregate level. Item-level accuracy varies significantly; a heatmap by item over time will show which items the model struggles with most.

---

## Review Cadence

| Review | Frequency | What to look at |
|---|---|---|
| Waste log entry | Weekly (Monday morning) | Enter previous week's paper logs |
| Panel review | Weekly (Monday, after log entry) | Waste cost trend, top offenders |
| Model retrain | Weekly (Monday) | Run FruitVeg_Demand_Forecast.ipynb with fresh sales data |
| Stockout log | Per cycle | Record any items that hit zero before delivery |
| Full KPI review | Monthly | All three pillars; compare to benchmarks |
| item_price update | Quarterly or after price changes | Refresh cost/sell prices from sales CSV |

---

## Key Decisions Logged

| Decision | Rationale |
|---|---|
| Cost price for waste cost (not sell price) | Sell price overstates loss by the GP margin (~37%). Cost price represents actual cash spent. |
| Waste Rate proxy = waste ÷ (sold + waste) | No ordered-quantity record exists yet. Proxy is directionally correct and available immediately. |
| SOH filter: 1–300 units | Values >300 treated as data errors (system inaccuracy observed above this threshold). |
| Active item filter: sold in last 2 weeks OR on special | Prevents seasonal/discontinued items from appearing in the order sheet. |
| EWMA fallback for new items | Items not in the trained model get a simple exponentially-weighted average from recent same-weekday sales. |
| No pre-model baseline recorded | Decision made at go-live. First 8–12 weeks of tracked data will serve as the internal baseline. |
