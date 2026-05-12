# Retail Operations Intelligence — Foodland Wudinna (2025–2026)

**Role:** Data Scientist / Analyst (independent project)  
**Domain:** Retail fresh produce — Fruit & Vegetable department  
**Stack:** Python · LightGBM · Streamlit · SQLite · pandas · openpyxl · Plotly  
**Period:** 2025 – Q2 2026  

---

## Project Narrative

Foodland Wudinna is an independent supermarket in regional South Australia. The Fruit & Vegetable department was ordering entirely by intuition — no demand history, no waste tracking, no pricing automation. In 2026, a year-on-year analysis revealed the consequence: markdown lines had increased **511.9%** (from 1.35 to 8.24 lines per trading day), pointing to a structural over-ordering problem eroding gross profit.

The engagement covered the full analytical lifecycle — from raw POS export to production tooling — with the goal of replacing ad-hoc decisions with a repeatable, data-driven workflow.

### Phase 1 — Understand the business

The first step was a full exploratory data analysis across 308 trading days of POS history (2025 + Q1 2026). The analysis established the revenue profile, demand seasonality, portfolio composition, and the waste problem's root cause.

Key findings: the department carried 281 active items, but 52% of them (147 items) were highly intermittent — they sell too infrequently to model with volume forecasts. Revenue concentration was high: the top 3 items (Bananas, Strawberries, Lettuce) accounted for ~17% of total revenue. Friday demand ran at 1.54× the weekday average, and a 36% revenue swing between the July trough and November peak meant seasonal calibration was essential. Two "margin trap" items were identified — Green Grapes and Baby Lebanese Cucumbers — where a price increase had triggered a volume drop large enough to reduce GP in absolute terms.

### Phase 2 — Build the forecasting model

A LightGBM model (MAE objective) was trained on the 2025–2026 sales history, covering 175 actively forecastable items with 28 engineered features. Feature engineering centred on demand patterns most relevant to this store's cycle: day-of-week averages, same-weekday lags, EWMA trends, monthly seasonality, specials flags, and order cycle indicators. Items not suitable for the model (new products, highly intermittent items) fall back to an EWMA calculation automatically.

The model was validated against a same-weekday EWMA baseline via a 6-cycle walk-forward backtest. It outperformed the baseline by approximately 15 percentage points WMAPE (37.9% vs. 52.9%), with near-neutral bias (+0.5%) — a slight over-forecast is intentional for perishables to avoid stockouts.

### Phase 3 — Operationalise the forecast

The model was embedded into a Streamlit ordering application. Each order cycle, the app ingests a stock-on-hand export, applies the forecast, consolidates multi-barcode product variants (e.g., Whole/Half/Quarter Cabbage into a single order row), and generates a printable Excel stock count sheet. The app automatically detects South Australian public holidays from a calendar table and warns when they affect delivery timing. Every generated order is logged to a forecast log CSV to enable future actuals-vs-forecast accuracy tracking.

### Phase 4 — Track performance

A separate performance panel was built to track the three pillars that define whether the model is working: waste reduction, stockout prevention, and GP%. Waste cost is calculated at cost price (not sell price), which correctly isolates the actual cash lost rather than the inflated sell-price figure. A stockout detector script was also built — given a SOH export, it identifies items that reached zero stock before the next delivery and estimates lost revenue from median daily sales, trading day gaps, and average sell price.

### Phase 5 — Pricing automation

Freshlink invoices arrive twice a week, and each one previously required manual price review and re-entry into the POS. A pricing automation pipeline was built to parse invoice PDFs and CSVs, match each line to its POS item via a 114-entry verified mapping table, and calculate a suggested sell price at a 40% GP target (rounded up to the nearest X.X9). The output is an Excel review sheet where the user approves or overrides each line. Approved prices are written back to the database and price history is maintained for every invoice. Items are flagged for extra scrutiny if cost or sell price changes exceed ±15%.

### Phase 6 — Cross-department waste analysis and target-setting

With the FV model running, the analysis was extended to cover all three perishable departments (Fruit & Veg, Dairy, and Meat) in a dedicated waste EDA (`Waste_Revenue_EDA.ipynb`), covering 88 trading days from January to April 2026.

The first task was defining the right waste metric. Two definitions were established: *narrow waste* (dump cost + below-cost markdown loss) — the true cash destroyed — and *broad waste* (dump cost + all discounts given) — total margin erosion. All target-setting used the narrow definition to avoid overstating the problem with discount amounts that were still recovered above cost.

Against independent supermarket peer benchmarks (1.5–3.0% for produce, 0.8–1.8% for dairy, 1.0–2.5% for meat), the store was already performing well: FV at 0.77%, Dairy at 1.08%, Meat at 1.58%, and a store total of 1.09% narrow waste on $689k revenue. The old blanket 5% target was retired as obsolete — the store was running at roughly a fifth of it.

Department-specific findings identified the structural causes. In FV, the Salads sub-department accounted for 45% of all FV narrow waste ($1,032 from bagged kit ranges), and 44 items appeared in both the dump and markdown lists simultaneously — being written off and discounted within the same 17-week window, the clearest possible signal of systemic over-ordering. In Dairy, 84 "open-ring" events ($345) could not be attributed to any SKU due to cashier scanning behaviour, masking the true waste picture. In Meat, a single SKU — Chicken Thigh Fillets — generated $300 in narrow waste (dump + below-cost markdown) across 15 markdown events in 88 days.

New department-specific targets were set and annualised: FV to 0.55%, Dairy to 0.75%, Meat to 1.10%, for a combined estimated annual saving of **~$7,889** at current revenue rates. A 10-action priority list was produced and plotted on an impact-vs-effort matrix — the top three quick wins (fix Dairy PLU scanning, remove RTE Meals from Meat, cut bottom-5 Salad kit order volumes) required no capital and were estimated to recover ~$3,360/year combined.

### Phase 7 — Data infrastructure

All data was migrated from flat CSV files into a SQLite star-schema database (`foodland_data.db`), with fact tables for sales, invoices, stock snapshots, dump write-offs, and markdowns, and dimension tables for products, dates, and suppliers. A shared `db.py` module handles all read/write operations, including a workaround for a virtiofs/OneDrive SQLite locking constraint (write to `/tmp`, then copy back). The full schema is documented and the migration script is idempotent.

---

## Achievement Bullets

*(Quantified, CV-ready — suitable for LinkedIn, a resume, or a portfolio)*

- **Built a LightGBM demand forecasting model** on 308 trading days of POS data (28 features, 175 items), achieving 37.9% WMAPE on the test set and outperforming the EWMA baseline by ~15 percentage points — reducing the primary driver of ordering uncertainty in a fresh produce department.

- **Diagnosed a 511.9% YoY increase in markdown lines/day** (1.35 → 8.24) through full exploratory data analysis across 2025–2026 POS history, projecting a $1,207 annual GP loss and identifying the specific over-ordering pattern driving it.

- **Identified margin trap pricing** on two items (Green Grapes, Baby Lebanese Cucumbers) where price increases had produced a net GP loss due to volume elasticity — with a specific rollback recommendation and GP recovery estimate.

- **Designed and built 4 production Streamlit applications** replacing entirely manual processes: demand-driven order sheet generation, waste KPI tracking, sales and GP monitoring, and stockout detection with lost-revenue estimation.

- **Automated the invoice pricing review workflow** — parsing Freshlink invoices (PDF/CSV), matching 114 invoice line descriptions to POS items, calculating GP-targeted sell prices, and producing a structured Excel approval sheet — reducing a manual, error-prone process to a one-click review.

- **Built a SQLite star-schema database** from scratch (fact tables for sales, invoices, stock, dumps, and markdowns; dimension tables for products, dates, and suppliers), migrated from flat CSVs, and implemented an idempotent pipeline with safe write handling for a virtiofs-mounted OneDrive path.

- **Engineered a stockout detection and lost-revenue estimation pipeline** that classifies genuine stockout events from SOH exports using four criteria (SOH threshold, active selling, recency, and timing), and estimates lost revenue from median daily sales × trading day gap × average sell price.

- **Designed a three-pillar performance measurement framework** (waste reduction, stockout prevention, ordering accuracy) with waste cost calculated at cost-price basis — correcting a common error that overstates waste loss by the GP margin (~37%).

- **Conducted ABC portfolio segmentation** across 281 products, classifying 52% (147 items) as highly intermittent and routing them to minimum-stock rules rather than volume forecasts — a deliberate modelling choice that avoids overfitting noise.

- **Built a Power BI data pipeline** (star-schema CSV builder scripts: dim_calendar, dim_item, fact_sales, fact_promotions) with a custom calendar table covering South Australian public holidays, store trading hours, and delivery day logic.

- **Designed for non-technical end users** throughout: one-click BAT launchers, colour-coded Excel outputs, in-app holiday warnings, and a printed stock count sheet format aligned to the store's physical ordering workflow.

- **Conducted a cross-department waste analysis across Fruit & Veg, Dairy, and Meat** (88 trading days, $689k revenue), establishing a two-definition waste framework (narrow: dump + below-cost loss; broad: total discount given) and benchmarking all three departments against independent supermarket peer ranges — revealing that the store was already performing at roughly one-fifth of its previous 5% waste target.

- **Set evidence-based, department-specific waste reduction targets** (FV 0.55%, Dairy 0.75%, Meat 1.10%) with estimated annual savings of **~$7,889** at current revenue, annualised from 88-day actuals — replacing a single blanket target that had no analytical basis.

- **Identified the single worst waste item store-wide** — Chicken Thigh Fillets — responsible for $300 in narrow waste from one SKU across 15 markdown events in 88 days, and quantified 44 FV items appearing simultaneously in both dump and markdown records, confirming systemic over-ordering.

- **Produced a ranked 10-action waste reduction plan with a priority matrix** (impact vs effort), isolating three quick wins requiring no capital outlay — fix Dairy PLU scanning, remove RTE Meals from Meat, and cut Salad kit order volumes — with a combined annual saving estimate of ~$3,360.

---

## Technical Stack

| Category | Detail |
|---|---|
| **Language** | Python 3.10+ |
| **Machine Learning** | LightGBM (MAE objective), walk-forward backtesting, EWMA baseline |
| **Feature Engineering** | Day-of-week averages, same-weekday lags, EWMA, specials flags, order cycle, monthly seasonality |
| **Dashboards** | Streamlit (4 apps), Plotly Express & Graph Objects |
| **Data** | pandas, NumPy, SQLite (star schema), openpyxl |
| **Reporting** | Auto-generated Excel (conditional formatting, VLOOKUPs, summary footers) |
| **BI** | Power BI (star schema, DAX measures) |
| **PDF Parsing** | pdfplumber (Freshlink invoice extraction) |
| **POS System** | GAP POS (data extraction, price management, waste reporting) |
| **Infrastructure** | SQLite on OneDrive/virtiofs (custom write strategy), BAT launchers, Docker |
| **Version Control** | Git |

---

## Domain Knowledge Demonstrated

- Fresh produce ordering logic: coverage demand + depletion demand − stock on hand, applied per delivery cycle
- Markdown and dump waste cost accounting at cost-price basis
- Invoice unit conversion (CTN → per kg, tray → per each) and sell price GP targeting
- South Australian public holiday and trading day calendar management
- Price elasticity and margin trap identification in a retail pricing context
- Industry benchmarking against AFGC / ECR Europe fresh produce standards (waste %, stockout rate, cycle efficiency, GP%)

---

## Key Numbers

| Metric | Value |
|---|---|
| Model WMAPE (test set) | 37.9% |
| Baseline WMAPE (EWMA) | 52.9% |
| Improvement over baseline | ~15 percentage points |
| Forecast bias | +0.5% (near-neutral) |
| Items modelled | 175 (of 281 active) |
| Invoice mapping entries verified | 114 |
| Markdown rate increase identified | 511.9% YoY |
| Projected annual GP loss from FV waste trend | ~$1,207 |
| Production apps delivered | 4 (ordering, performance, sales, waste) |
| Backtest cycles | 6 (walk-forward) |
| Trading days in training data | 308 |
| Departments covered in waste analysis | 3 (FV, Dairy, Meat) |
| Revenue analysed in waste EDA | $689k (88 trading days) |
| Store narrow waste rate (current) | 1.09% of revenue |
| Store narrow waste rate (target) | 0.77% of revenue |
| Estimated annual saving at target | ~$7,889 |
| Waste priority actions identified | 10 (ranked by impact/effort) |
| Items in both dump AND markdown | 44 FV SKUs (chronic over-orders) |
