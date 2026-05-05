# Fruit sales EDA — notebook cells (run top to bottom)

Assumes CSVs `sales_fruit_2025.csv` and `sales_fruit_2026.csv` are in the notebook working directory.

---

## Cell 0 — Imports

**What this does:** Loads the necessary Python libraries for data manipulation (Pandas, NumPy) and visualization (Matplotlib, Seaborn). It also sets a clean default visual style and size for all our charts.

**How to interpret:** There is no output for this cell. As long as it runs without an error, your environment is set up correctly.

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid")
plt.rcParams["figure.figsize"] = (10, 5)
```

---

## Cell 1 — Load and concatenate

**What this does:** Reads the separate sales files for 2025 and 2026 and stacks them on top of each other into a single, combined dataset (`sales_fruit`). 

**How to interpret:** The output will show a summary of the combined dataset. Check the total number of entries (rows) and look at the "Dtype" column to ensure numbers are recognized as floats/integers and text is recognized as objects/strings.

```python
sales_fruit_2025 = pd.read_csv("sales_fruit_2025.csv", dtype={"APN": "string"})
sales_fruit_2026 = pd.read_csv("sales_fruit_2026.csv", dtype={"APN": "string"})
sales_fruit = pd.concat([sales_fruit_2025, sales_fruit_2026], ignore_index=True)

# Display basic information about the combined dataset
sales_fruit.info()
```

---

## Cell 2 — Data Validation (Counts, Duplicates, and Missing Values)

**What this does:** Checks the health of the data. It verifies that no rows were lost during the merge, looks for accidentally duplicated records, and counts missing values (nulls) in critical columns like APN (barcode) and Sub Department. 

**How to interpret:** * **Rows:** The combined row count should perfectly match the sum of the individual years.
* **Duplicates:** If there are many duplicates, the raw data may have been exported twice.
* **Nulls:** High numbers of missing APNs or Sub Departments mean we might need to clean the data before digging deeper, as missing categories can skew our totals.

```python
# Row counts
n25, n26 = len(sales_fruit_2025), len(sales_fruit_2026)
assert len(sales_fruit) == n25 + n26, "Error: Combined row count does not match individual files."
print(f"✅ Row count validation passed! 2025: {n25} + 2026: {n26} = Combined: {len(sales_fruit)}")

sales_fruit["Date"] = pd.to_datetime(sales_fruit["Date"])
sales_fruit["year"] = sales_fruit["Date"].dt.year
sales_fruit["year_month"] = sales_fruit["Date"].dt.to_period("M")

print(f"🔍 Exact duplicate rows found: {sales_fruit.duplicated().sum()}")
print(f"🔍 Duplicates based on Date, APN, and Name only: {sales_fruit.duplicated(subset=['Date', 'APN', 'Name']).sum()}")

null_apn = sales_fruit["APN"].isna()
null_sub = sales_fruit["Sub Department Name"].isna()
print("\n⚠️ Count of missing values in key columns:")
print(sales_fruit[["APN", "Sub Department Name"]].isna().sum())
print(f"Rows missing BOTH APN and Sub Department: {(null_apn & null_sub).sum()}")

print("\n--- Preview of rows with missing data ---")
display(sales_fruit.loc[null_apn | null_sub, ["Date", "APN", "Name", "Sub Department Name"]].head(15))

# Store columns: checking if store totals vary within the same day
print("\n--- Store Level Checks ---")
for col in ["Store Sales Ex", "Store Sales Inc"]:
    nu = sales_fruit.groupby("Date")[col].nunique()
    print(f"Column '{col}': found { (nu > 1).sum() } days out of {len(nu)} where values change mid-day.")

sales_fruit.head()
```

---

## Cell 3 — Sales Trends Over Time

**What this does:** Visualizes the rhythm of the business. It plots overall daily and weekly sales over time, compares sales by day of the week, and creates a "heatmap" to show which months generate the most revenue.

**How to interpret:** * **Line Charts:** Look for obvious spikes (holidays) or dips. Weekly sales smooth out the daily noise so you can see the overall trajectory.
* **Bar Chart:** Tells you your busiest and quietest days of the week.
* **Heatmap:** Darker/warmer colors instantly highlight your best-performing months across both years.

```python
print(f"📅 Overall Date Range: {sales_fruit['Date'].min().date()} to {sales_fruit['Date'].max().date()}")
print("\n📅 Date Range by Year:")
display(sales_fruit.groupby("year")["Date"].agg(["min", "max"]))

daily = (
    sales_fruit.groupby("Date", as_index=False)
    .agg(rows=("Name", "count"), sales_ex_gst=("Sales Ex GST", "sum"), gp_dollar=("GP $", "sum"))
    .sort_values("Date")
)
weekly = daily.set_index("Date").resample("W-MON")["sales_ex_gst"].sum()

fig, ax = plt.subplots()
ax.plot(daily["Date"], daily["sales_ex_gst"], lw=0.8)
ax.set_title("Daily Sales Trend (Excluding GST)")
ax.set_ylabel("Revenue ($)")
plt.tight_layout()
plt.show()

fig, ax = plt.subplots()
ax.bar(weekly.index, weekly.values, width=5)
ax.set_title("Weekly Sales Trend (Excluding GST, week ending Mon)")
ax.set_ylabel("Revenue ($)")
plt.tight_layout()
plt.show()

sales_fruit["dow"] = sales_fruit["Date"].dt.dayofweek
sales_fruit["month"] = sales_fruit["Date"].dt.month

pivot_dow = sales_fruit.pivot_table(values="Sales Ex GST", index="dow", columns="year", aggfunc="sum")
fig, ax = plt.subplots()
pivot_dow.plot(kind="bar", ax=ax, rot=0)
ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
ax.set_title("Total Sales by Day of the Week")
ax.set_ylabel("Revenue ($)")
plt.tight_layout()
plt.show()

heat = sales_fruit.pivot_table(values="Sales Ex GST", index="month", columns="year", aggfunc="sum")
fig, ax = plt.subplots(figsize=(8, 5))
sns.heatmap(heat, annot=True, fmt=".0f", cmap="YlOrRd", ax=ax)
ax.set_title("Monthly Sales Heatmap (Excluding GST)")
ax.set_ylabel("Month (1-12)")
plt.tight_layout()
plt.show()
```

---

## Cell 4 — Top Performers (Sub-departments & Items)

**What this does:** Breaks down the business to see what is actually selling. It creates a "Pareto chart" to show how much each sub-department contributes to total sales, and then identifies the top 20 specific items (SKUs) by revenue, profit, and volume.

**How to interpret:** * **Pareto Chart:** The bars show the size of the department, and the orange line shows the cumulative percentage. Often, you'll see the "80/20 rule" where just a few departments generate most of the revenue.
* **Top 20 Tables:** These are your core products. Make sure your top volume items align with your top profit items; if they don't, you might be moving a lot of product for very little return.

```python
sub_dept = (
    sales_fruit.groupby("Sub Department Name", dropna=False)
    .agg(sales_ex_gst=("Sales Ex GST", "sum"), gp_dollar=("GP $", "sum"), rows=("Name", "count"))
    .sort_values("sales_ex_gst", ascending=False)
)
sub_dept["share_pct"] = sub_dept["sales_ex_gst"] / sub_dept["sales_ex_gst"].sum() * 100
sub_dept["cum_share_pct"] = sub_dept["share_pct"].cumsum()

print("\n--- Sub-Department Sales Summary ---")
display(sub_dept)

fig, ax = plt.subplots()
ax.barh(sub_dept.index.astype(str)[::-1], sub_dept["sales_ex_gst"].iloc[::-1])
ax.set_xlabel("Revenue Ex GST ($)")
ax.set_title("Total Sales by Sub-Department")
plt.tight_layout()
plt.show()

fig, ax1 = plt.subplots()
x = np.arange(len(sub_dept))
ax1.bar(x, sub_dept["share_pct"].values, label="Share %")
ax2 = ax1.twinx()
ax2.plot(x, sub_dept["cum_share_pct"].values, color="C1", marker="o", lw=2, label="Cumulative %")
ax1.set_xticks(x)
ax1.set_xticklabels(sub_dept.index.astype(str), rotation=45, ha="right")
ax1.set_ylabel("Share of Total Sales (%)")
ax2.set_ylabel("Cumulative Total (%)")
ax1.set_title("Pareto Chart: Sub-Department Revenue Contribution")
fig.tight_layout()
plt.show()

sales_fruit["sku_key"] = sales_fruit["APN"].fillna("<no APN>") + " | " + sales_fruit["Name"]

for label, col in [("Revenue (Sales Ex GST)", "Sales Ex GST"), ("Profit (GP $)", "GP $"), ("Volume (Quantity)", "Quantity")]:
    top = sales_fruit.groupby("sku_key", dropna=False)[col].sum().sort_values(ascending=False).head(20)
    print(f"\n🏆 Top 20 Items by {label}:")
    display(top.to_frame(label))
```

---

## Cell 5 — Profit Margin Health & Anomalies

**What this does:** Examines the Gross Profit percentage (GP%). It visualizes the normal range of margins across different departments and flags records where the store lost money (negative margin) or made an unrealistically high margin (over 95%).

**How to interpret:** * **Charts:** The histogram shows your "average" margin peak. The boxplots show if certain departments consistently yield higher or more volatile margins than others.
* **Negative/Extreme Tables:** Treat these as an exception report. A negative margin means the item was sold for less than it cost (possibly a markdown, spoilage, or pricing error). Extreme margins (>95%) usually indicate missing cost data.

```python
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
sns.histplot(sales_fruit["GP %"], bins=50, kde=True, ax=axes[0])
axes[0].set_title("Overall Distribution of Gross Profit %")
sns.boxplot(data=sales_fruit, x="Sub Department Name", y="GP %", ax=axes[1])
axes[1].set_xticklabels(axes[1].get_xticklabels(), rotation=45, ha="right")
axes[1].set_title("Gross Profit % Range by Sub-Department")
plt.tight_layout()
plt.show()

neg = sales_fruit[sales_fruit["GP %"] < 0][
    ["Date", "Name", "Sub Department Name", "Sales Ex GST", "Cost Inc GST", "GP %", "GP $", "Lines", "Quantity"]
].sort_values("GP $")
print(f"\n🚨 WARNING: Found {len(neg)} rows where money was lost (GP % < 0). Showing worst offenders:")
display(neg.head(30))

extreme = sales_fruit[(sales_fruit["GP %"] < -5) | (sales_fruit["GP %"] > 95)]
print(f"\n⚠️ WARNING: Found {len(extreme)} rows with highly unusual margins (< -5% or > 95%). Showing sample:")
display(extreme.head(20))

print("\n--- Quick check: Difference between Sales Inc GST and Ex GST ---")
print(
    sales_fruit.assign(
        diff_inc_ex=sales_fruit["Sales Inc GST"] - sales_fruit["Sales Ex GST"]
    )["diff_inc_ex"].describe()
)
```

---

## Cell 6 — Year-Over-Year Growth

**What this does:** Directly compares 2025 to 2026. It tracks monthly revenue side-by-side and calculates the exact dollar and percentage growth (or decline) for every sub-department.

**How to interpret:** * **Line Chart:** If the 2026 line is consistently above 2025, the business is growing. 
* **Sub-department Table:** Look at the `delta` (dollar growth) and `pct_change` (percentage growth) columns. This tells you exactly which areas of the store are expanding and which are shrinking compared to last year.

```python
monthly = (
    sales_fruit.groupby(["year", "year_month"], as_index=False)
    .agg(sales_ex_gst=("Sales Ex GST", "sum"), gp_dollar=("GP $", "sum"))
)
monthly_pivot = monthly.pivot(index="year_month", columns="year", values="sales_ex_gst")

print("\n--- Monthly Revenue Comparison ---")
display(monthly_pivot)

fig, ax = plt.subplots(figsize=(10, 4))
monthly_pivot.plot(ax=ax, marker="o")
ax.set_title("Year-Over-Year Monthly Revenue (Excluding GST)")
ax.set_ylabel("Revenue ($)")
plt.tight_layout()
plt.show()

sub_yoy = sales_fruit.pivot_table(
    values="Sales Ex GST", index="Sub Department Name", columns="year", aggfunc="sum"
)
if sub_yoy.shape[1] >= 2:
    yrs = sorted(sub_yoy.columns)
    sub_yoy["delta"] = sub_yoy[yrs[-1]] - sub_yoy[yrs[-2]]
    sub_yoy["pct_change"] = (sub_yoy[yrs[-1]] / sub_yoy[yrs[-2]] - 1) * 100

print(f"\n--- Sub-Department Growth: {yrs[-2]} vs {yrs[-1]} ---")
display(sub_yoy.sort_values("delta", ascending=False, na_position="last"))
```

---

## Cell 7 — Operational Efficiency (Scans vs Volume)

**What this does:** Analyzes labor and efficiency. "Lines" usually represents how many times an item was scanned at the register, while "Quantity" is how many physical items were sold. It calculates the average dollar value generated every time a cashier scans an item.

**How to interpret:** * **Summary Table:** Departments with a high `median_avg_line` generate more revenue per transaction, meaning they are highly efficient. 
* **Outliers:** The final table flags items that take a lot of work (high scans/lines) but generate very little revenue. These might be cheap, single-buy items holding up the checkout line.

```python
sales_fruit["avg_line_value"] = np.where(
    sales_fruit["Lines"] > 0, sales_fruit["Sales Ex GST"] / sales_fruit["Lines"], np.nan
)

line_summary = (
    sales_fruit.groupby("Sub Department Name", dropna=False)
    .agg(
        median_lines=("Lines", "median"),
        median_qty=("Quantity", "median"),
        median_avg_line=("avg_line_value", "median"),
    )
    .sort_values("median_avg_line", ascending=False)
)
print("\n--- Operational Efficiency by Sub-Department ---")
display(line_summary)

sample = sales_fruit.sample(min(2000, len(sales_fruit)), random_state=42)
fig, ax = plt.subplots()
ax.scatter(sample["Quantity"], sample["Lines"], alpha=0.3, s=10)
ax.set_xlabel("Quantity Sold")
ax.set_ylabel("Register Scans (Lines)")
ax.set_title("Scans vs. Quantity Sold (Random Sample)")
plt.tight_layout()
plt.show()

outliers = sales_fruit[(sales_fruit["Lines"] >= sales_fruit["Lines"].quantile(0.99)) & (sales_fruit["Sales Ex GST"] < sales_fruit["Sales Ex GST"].quantile(0.5))]
print("\n⏰ Inefficiency Alert: Items scanned very frequently but yielding low revenue:")
display(outliers[["Date", "Name", "Lines", "Quantity", "Sales Ex GST", "Sub Department Name"]].head(20))
```

---

## Cell 8 (Optional) — Product Type Extraction

**What this does:** Scans the text in the product names to guess if an item is sold loose by weight ("PER KG") or pre-packaged ("PRE PACK", "PUNNET"). It then compares the total sales of these two categories.

**How to interpret:** Look at the table output. It reveals consumer preferences: does your customer base prefer grabbing loose fruit by the kilo, or do they prefer the convenience of grabbing pre-packaged punnets? 

```python
name_u = sales_fruit["Name"].str.upper()
sales_fruit["flag_per_kg"] = name_u.str.contains("PER KG", na=False)
sales_fruit["flag_pre_pack"] = name_u.str.contains("PRE PACK|P/PACK|PUNNET", na=False, regex=True)

flags = (
    sales_fruit.groupby(["flag_per_kg", "flag_pre_pack"], dropna=False)
    .agg(sales_ex_gst=("Sales Ex GST", "sum"), rows=("Name", "count"))
    .sort_values("sales_ex_gst", ascending=False)
)
print("\n--- Sales split: Sold by Weight (PER KG) vs Pre-Packaged ---")
print("Note: True means the flag was found in the product name.")
display(flags)
```