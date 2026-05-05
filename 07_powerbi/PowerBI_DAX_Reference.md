# Power BI — DAX Measures Reference
## Fruit & Veg Department | Foodland Wudinna

---

## Step 0 — Add fact_promotions to the Model

Before creating measures, load `fact_promotions.csv` the same way you loaded the
other three tables (Get Data → Text/CSV). Then add two relationships in Model view:

| From                              | To                        | Cardinality  |
|-----------------------------------|---------------------------|--------------|
| fact_promotions[cycle_date_key]   | dim_calendar[date_key]    | Many-to-One  |
| fact_promotions[item_key]         | dim_item[item_key]        | Many-to-One  |

Your final model should have four tables with these relationships:

```
dim_calendar ──< fact_sales      >── dim_item
dim_calendar ──< fact_promotions >── dim_item
```

---

## Step 1 — Create a Measures Table

In Power BI, create an empty table to house all measures cleanly:
Home → Enter Data → name it `_Measures` → Load.
Then right-click each measure below and move it to `_Measures`.

---

## Revenue Measures

```dax
Revenue =
SUM(fact_sales[sales_ex_gst])
```

```dax
Revenue LY =
CALCULATE(
    [Revenue],
    SAMEPERIODLASTYEAR(dim_calendar[date])
)
```

```dax
Revenue YoY % =
DIVIDE(
    [Revenue] - [Revenue LY],
    [Revenue LY]
)
```

```dax
-- Normalises for different numbers of trading days between periods.
-- Use this as the primary comparison metric, not raw revenue.
Rev per Trading Day =
DIVIDE([Revenue], [Trading Days])
```

```dax
Rev per Trading Day LY =
DIVIDE(
    [Revenue LY],
    CALCULATE([Trading Days], SAMEPERIODLASTYEAR(dim_calendar[date]))
)
```

```dax
Rev per Trading Day YoY % =
DIVIDE(
    [Rev per Trading Day] - [Rev per Trading Day LY],
    [Rev per Trading Day LY]
)
```

---

## GP Measures

```dax
GP$ =
SUM(fact_sales[gp_dollars])
```

```dax
-- Weighted GP% across all selected items and dates.
GP% =
DIVIDE([GP$], [Revenue])
```

```dax
GP$ LY =
CALCULATE([GP$], SAMEPERIODLASTYEAR(dim_calendar[date]))
```

```dax
GP% LY =
DIVIDE([GP$ LY], [Revenue LY])
```

```dax
GP% YoY pp =
-- Percentage point change, not a ratio. E.g. 38% → 36% = -2pp
([GP%] - [GP% LY]) * 100
```

---

## Volume Measures

```dax
Quantity =
SUM(fact_sales[quantity])
```

```dax
Quantity LY =
CALCULATE([Quantity], SAMEPERIODLASTYEAR(dim_calendar[date]))
```

```dax
Quantity YoY % =
DIVIDE([Quantity] - [Quantity LY], [Quantity LY])
```

---

## Trading Day Measures

```dax
-- Count of store-open days in the current filter context.
Trading Days =
CALCULATE(
    COUNTROWS(dim_calendar),
    dim_calendar[is_store_open] = 1
)
```

```dax
-- Useful for annotating charts: "Week 12 had a public holiday on Wednesday"
Public Holidays =
CALCULATE(
    COUNTROWS(dim_calendar),
    dim_calendar[is_public_holiday] = 1
)
```

---

## Promotions & Markdown Measures

```dax
GP Loss =
SUM(fact_promotions[gp_loss])
```

```dax
GP Loss LY =
CALCULATE([GP Loss], SAMEPERIODLASTYEAR(dim_calendar[date]))
```

```dax
Markdown Events =
CALCULATE(
    COUNTROWS(fact_promotions),
    fact_promotions[event_type] = "Markdown"
)
```

```dax
Special Events =
CALCULATE(
    COUNTROWS(fact_promotions),
    fact_promotions[event_type] = "Special"
)
```

```dax
GP Loss per Markdown =
DIVIDE([GP Loss], [Markdown Events])
```

```dax
-- % of total revenue lost to markdowns. Useful for trend tracking.
GP Loss as % of Revenue =
DIVIDE([GP Loss], [Revenue])
```

---

## Page 1 — Sales Overview

**Purpose:** Landing page. Answers "how are we going this week vs last year?"

**Filters / Slicers (top of page):**
- Year slicer (2025 / 2026)
- Month slicer

**Visuals:**

| Visual | Type | X-axis / Rows | Values | Notes |
|--------|------|---------------|--------|-------|
| Weekly revenue trend | Line chart | dim_calendar[week_of_year] | [Revenue], [Revenue LY] | Two lines, current vs prior year |
| Revenue YoY % by week | Column chart | dim_calendar[week_of_year] | [Revenue YoY %] | Conditional format: red if negative |
| GP% trend | Line chart | dim_calendar[week_of_year] | [GP%], [GP% LY] | Format as % |
| KPI cards (top row) | Card × 4 | — | [Revenue], [Revenue YoY %], [GP%], [GP% YoY pp] | |
| Trading days context | Card | — | [Trading Days], [Public Holidays] | Small card, secondary info |
| Revenue by sub-department | Donut chart | dim_item[sub_department] | [Revenue] | |

**Key design note:** Use `[Rev per Trading Day]` rather than raw `[Revenue]` whenever
comparing periods of different lengths (e.g. a partial month vs a full month).

---

## Page 2 — Item Performance

**Purpose:** ABC review, sub-department breakdown, top and bottom performers.

**Filters / Slicers:**
- Year slicer
- Sub-department slicer (Fruit / Vegetables / Salads / Potatoes / Misc)
- ABC class slicer (A / B / C)

**Visuals:**

| Visual | Type | X-axis / Rows | Values | Notes |
|--------|------|---------------|--------|-------|
| Revenue by item | Bar chart (horizontal) | dim_item[name] | [Revenue] | Top N filter: top 20 |
| GP$ by item | Bar chart (horizontal) | dim_item[name] | [GP$] | Top N filter: top 20 |
| ABC breakdown | Donut chart | dim_item[abc_class] | [Revenue] | A=green, B=amber, C=grey |
| Sub-dept performance | Clustered bar | dim_item[sub_department] | [Revenue], [GP%] | Dual axis |
| Item detail table | Table | dim_item[name], dim_item[sub_department], dim_item[abc_class] | [Revenue], [Revenue YoY %], [GP%], [Quantity] | Sort by Revenue desc |
| Quantity YoY % | Column chart | dim_item[name] | [Quantity YoY %] | Top 20 items only |

**Key design note:** The item detail table is the workhorse of this page.
Add conditional formatting on `Revenue YoY %` (red = declining, green = growing)
and on `GP%` (red if < 30%).

---

## Page 3 — Promotions & Markdowns

**Purpose:** Track where GP is being lost — planned specials vs unplanned markdowns.

**Filters / Slicers:**
- Year slicer
- Event type slicer (Special / Markdown)
- Sub-department slicer

**Visuals:**

| Visual | Type | X-axis / Rows | Values | Notes |
|--------|------|---------------|--------|-------|
| GP loss trend | Line chart | dim_calendar[week_of_year] | [GP Loss], [GP Loss LY] | |
| GP Loss as % of Revenue | Line chart | dim_calendar[week_of_year] | [GP Loss as % of Revenue] | Target line at 0.5% |
| Events by type | Clustered column | dim_calendar[month] | [Special Events], [Markdown Events] | |
| Top items by GP loss | Bar chart | dim_item[name] | [GP Loss] | Filter to Markdown only |
| GP Loss per Markdown | Card | — | [GP Loss per Markdown] | |
| Promo detail table | Table | dim_item[name], fact_promotions[event_type], fact_promotions[cycle_start] | fact_promotions[gp_loss], fact_promotions[cycle_gp_pct], fact_promotions[baseline_gp] | Sort by gp_loss desc |

**Key design note:** Keep Specials and Markdowns visually distinct — Specials are
planned and expected to drive volume; Markdowns are waste/clearance and represent
avoidable GP loss. The donut or stacked bar showing the split makes this
immediately clear for a manager audience.

---

## Formatting Conventions

- Revenue: `$#,##0` (no decimals for summary cards)
- GP$: `$#,##0.00`
- GP%: `0.0%`
- YoY % changes: `+0.0%;-0.0%;0.0%` (shows sign explicitly)
- GP pp change: `+0.0pp;-0.0pp;0.0pp`

---

## What Comes Next (Step 4)

Once `fact_forecast.csv` is added, two new measures unlock:

```dax
Forecast Qty = SUM(fact_forecast[forecast_qty])

Forecast Accuracy (WMAPE) =
DIVIDE(
    SUMX(fact_forecast, ABS(fact_forecast[forecast_qty] - fact_forecast[actual_qty]) * fact_forecast[actual_qty]),
    SUMX(fact_forecast, fact_forecast[actual_qty] * fact_forecast[actual_qty])
)

Forecast Bias =
DIVIDE(
    SUM(fact_forecast[forecast_qty]) - SUM(fact_forecast[actual_qty]),
    SUM(fact_forecast[actual_qty])
)
```

These power a **Page 4 — Model Accuracy** showing WMAPE by item, bias direction,
and over-ordering cost estimate.
