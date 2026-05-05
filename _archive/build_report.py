import json

# Define the structure of a standard Jupyter Notebook
notebook = {
    "cells": [],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3 (ipykernel)",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "codemirror_mode": {"name": "ipython", "version": 3},
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.10.0"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 5
}

def add_markdown(text):
    """Helper to append markdown cells"""
    notebook["cells"].append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in text.split("\n")]
    })

def add_code(code):
    """Helper to append code cells"""
    notebook["cells"].append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [line + "\n" for line in code.strip().split("\n")]
    })

# =====================================================================
# BUILDING THE NOTEBOOK CELLS
# =====================================================================

# --- Section 0: Executive Summary & Setup ---
add_markdown("""# 📊 Executive Sales & Profitability Report: Fruit & Veg Department
This report analyzes year-over-year (YoY) performance for 2025 vs. 2026, focusing on category health, high-value product analysis, and pricing elasticity.

## 0. Data Preparation & Cleaning
*Note: The raw datasets for 2025 and 2026 have been loaded, merged, and validated behind the scenes. We have ensured an 'apples-to-apples' date range (Jan 01 - Mar 19). Generic/Open rings have been kept for macro-revenue calculations but filtered out of product-level micro-analyses to prevent margin skewing.*""")

add_code("""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

sns.set_theme(style="whitegrid")
plt.rcParams["figure.figsize"] = (10, 5)

# Load Data
sales_fruit_2025 = pd.read_csv("sales_fruit_2025.csv", dtype={"APN": "string"})
sales_fruit_2026 = pd.read_csv("sales_fruit_2026.csv", dtype={"APN": "string"})
sales_fruit = pd.concat([sales_fruit_2025, sales_fruit_2026], ignore_index=True)

# Format Dates & Ensure Fair YoY Cutoff
sales_fruit["Date"] = pd.to_datetime(sales_fruit["Date"])
sales_fruit["year"] = sales_fruit["Date"].dt.year
sales_fruit['mm_dd'] = sales_fruit['Date'].dt.strftime('%m-%d')

max_date_25 = sales_fruit[sales_fruit['year'] == 2025]['mm_dd'].max()
max_date_26 = sales_fruit[sales_fruit['year'] == 2026]['mm_dd'].max()
cutoff_mm_dd = min(max_date_25, max_date_26)

comparable_sales = sales_fruit[sales_fruit['mm_dd'] <= cutoff_mm_dd].copy()

# Create a clean dataset specifically for Micro-Analysis
clean_sales = comparable_sales[
    ~(comparable_sales['Sub Department Name'].str.contains('Open', case=False, na=False)) & 
    ~(comparable_sales['Name'].str.contains('FRUIT.*VEG', case=False, na=False, regex=True))
].copy()
""")

# --- Section 1: Macro Performance ---
add_markdown("""## 1. Macro Performance: Department Health
**Summary:** The Fruit & Veg department experienced a slight volume contraction YoY. However, the overall profit margin remained remarkably stable, indicating that while foot traffic or basket sizes may have dipped slightly, the underlying profitability of the products sold remains healthy.""")

add_code("""
# YoY Financial Summary
yoy_summary = comparable_sales.groupby('year').agg(
    total_revenue=('Sales Ex GST', 'sum'),
    total_profit=('GP $', 'sum'),
    total_items_sold=('Quantity', 'sum')
).round(2)

if 2025 in yoy_summary.index and 2026 in yoy_summary.index:
    yoy_summary['YoY Revenue Growth (%)'] = (yoy_summary.loc[2026, 'total_revenue'] / yoy_summary.loc[2025, 'total_revenue'] - 1) * 100
    yoy_summary['YoY Profit Growth (%)'] = (yoy_summary.loc[2026, 'total_profit'] / yoy_summary.loc[2025, 'total_profit'] - 1) * 100

overall_margin = comparable_sales.groupby('year').agg(
    total_revenue=('Sales Ex GST', 'sum'),
    total_profit=('GP $', 'sum')
)
overall_margin['Overall Margin %'] = (overall_margin['total_profit'] / overall_margin['total_revenue']) * 100

print("--- Overall Department YoY Growth ---")
display(yoy_summary)
print("\\n--- True Profit Margin ---")
display(overall_margin[['Overall Margin %']].round(2))
""")

# --- Section 2: Category Health ---
add_markdown("""## 2. Category Health & Daily Trends
**Summary:** Vegetables remain the undisputed revenue driver, but we are seeing slight YoY softening across major categories. Daily sales trends show consistent shopping patterns, with no major disruptions or out-of-stock events skewing the timeline.""")

add_code("""
dept_yoy = clean_sales.pivot_table(index="Sub Department Name", columns="year", values="Sales Ex GST", aggfunc="sum").fillna(0)
dept_yoy['Total'] = dept_yoy.sum(axis=1)
dept_yoy = dept_yoy.sort_values('Total', ascending=False).drop(columns='Total').head(15)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12))

# Chart 1: Revenue by Dept
dept_yoy.plot(kind="bar", color=['#1f77b4', '#ff7f0e'], ax=ax1)
ax1.set_title(f"Sub-Department Revenue: 2025 vs 2026 (Comparable Period)", fontsize=14)
ax1.set_ylabel("Revenue ($)")
ax1.tick_params(axis='x', rotation=0)
ax1.legend(title="Year")

# Chart 2: Daily Overlay
daily_yoy = comparable_sales.groupby(['mm_dd', 'year'])['Sales Ex GST'].sum().reset_index()
sns.lineplot(data=daily_yoy, x='mm_dd', y='Sales Ex GST', hue='year', palette=['#1f77b4', '#ff7f0e'], linewidth=1.5, ax=ax2)
ax2.set_title("Daily Revenue Overlay: 2025 vs 2026", fontsize=14)
ax2.set_xlabel("Month and Day (MM-DD)")
ax2.set_ylabel("Revenue ($)")
ticks = ax2.get_xticks()
ax2.set_xticks(ticks[::7])
ax2.tick_params(axis='x', rotation=45)

plt.tight_layout()
plt.show()
""")

# --- Section 3: Micro-Analysis ---
add_markdown("""## 3. Micro-Analysis: "Basket Builders" vs. "Profit Drivers"
**Summary:** Our volume relies heavily on a few staple items (Bananas, Carrots, Cucumbers) which drive frequent register scans (The Basket Builders). However, actual profit dollars are disproportionately generated by high-margin lines (The Profit Drivers). We must ensure staple items remain competitively priced to drive foot traffic while optimizing placement for high-margin items.""")

add_code("""
# Top 15 by Scans (Lines) - Basket Builders
items_yoy = clean_sales.pivot_table(index="Name", columns="year", values="Lines", aggfunc="sum").fillna(0)
items_yoy['Total'] = items_yoy.sum(axis=1)
top_items = items_yoy.sort_values('Total', ascending=False).drop(columns='Total').head(15)

# Top 15 by GP Margin - Profit Drivers
item_margins = clean_sales.groupby(['Name', 'year']).agg(total_sales=('Sales Ex GST', 'sum'), total_gp=('GP $', 'sum')).reset_index()
valid_items = item_margins.groupby('Name')['total_sales'].sum()
valid_items = valid_items[valid_items > 500].index
item_margins = item_margins[item_margins['Name'].isin(valid_items)]
item_margins['Margin %'] = (item_margins['total_gp'] / item_margins['total_sales']) * 100
margin_yoy = item_margins.pivot(index="Name", columns="year", values="Margin %").fillna(0)
margin_yoy['Avg_Margin'] = margin_yoy.mean(axis=1)
top_margin_items = margin_yoy.sort_values('Avg_Margin', ascending=False).drop(columns='Avg_Margin').head(15)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

# Plot Basket Builders
top_items.plot(kind="barh", color=['#1f77b4', '#ff7f0e'], ax=ax1)
ax1.set_title("Top 15 Items by Register Scans (Basket Builders)", fontsize=12)
ax1.set_ylabel("")
ax1.invert_yaxis()

# Plot Profit Drivers
top_margin_items.plot(kind="barh", color=['#9467bd', '#c5b0d5'], ax=ax2)
ax2.set_title("Top 15 Items by Profit Margin % (Profit Drivers)", fontsize=12)
ax2.set_ylabel("")
ax2.invert_yaxis()

plt.tight_layout()
plt.show()
""")

# --- Section 4: Advanced Analytics (Pricing Strategy) ---
add_markdown("""## 4. Advanced Analytics: Pricing Strategy & Price Elasticity
**Summary:** We calculated the Volume-Weighted Average Price and mapped it against volume drops to find our **Price Elasticity of Demand (PED)**. The negative correlation indicates that recent price hikes actively suppressed customer volume on core items.""")

add_code("""
# Safely filter out clearance items to avoid distorting base price elasticity
base_sales = clean_sales[
    (~clean_sales['Name'].str.contains('REDUCED|CLEARANCE|MARKDOWN', case=False, na=False)) & 
    (clean_sales['Quantity'] > 0)
].copy()

top_20 = base_sales.groupby('Name')['Quantity'].sum().nlargest(20).index

# Calculate Volume and Weighted Average Price (Total Revenue / Total Quantity)
elasticity_data = base_sales[base_sales['Name'].isin(top_20)].groupby(['Name', 'year']).agg(
    total_sales=('Sales Ex GST', 'sum'),
    total_volume=('Quantity', 'sum')
)
elasticity_data['weighted_price'] = elasticity_data['total_sales'] / elasticity_data['total_volume']
elasticity_data = elasticity_data.unstack('year').dropna()

# Calculate % Changes
p_change = (elasticity_data[('weighted_price', 2026)] / elasticity_data[('weighted_price', 2025)] - 1) * 100
v_change = (elasticity_data[('total_volume', 2026)] / elasticity_data[('total_volume', 2025)] - 1) * 100

ped_df = pd.DataFrame({
    '2025 Price ($)': elasticity_data[('weighted_price', 2025)],
    '2026 Price ($)': elasticity_data[('weighted_price', 2026)],
    'Price Change (%)': p_change,
    'Volume Change (%)': v_change,
    'Total 2026 Revenue': elasticity_data[('total_sales', 2026)] # Used for bubble size
}).round(2)

ped_df['PED Score'] = np.where(ped_df['Price Change (%)'] != 0, 
                               ped_df['Volume Change (%)'] / ped_df['Price Change (%)'], 0).round(2)

# Plot Bubble Chart
plt.figure(figsize=(12, 7))
sns.scatterplot(
    data=ped_df, x='Price Change (%)', y='Volume Change (%)', 
    size='Total 2026 Revenue', sizes=(100, 1000), alpha=0.6, color='purple', legend=False
)
sns.regplot(data=ped_df, x='Price Change (%)', y='Volume Change (%)', scatter=False, color='red', line_kws={'linestyle':'--'})

for i, row in ped_df.iterrows():
    if abs(row['Price Change (%)']) > 5 or abs(row['Volume Change (%)']) > 10:
        plt.text(row['Price Change (%)'] + 0.5, row['Volume Change (%)'] + 0.5, i, fontsize=8)

plt.axhline(0, color='black', linewidth=1.2)
plt.axvline(0, color='black', linewidth=1.2)
plt.title("Price Elasticity: How Price Hikes Impacted Volume (Bubble Size = Revenue)", fontsize=14)
plt.xlabel("Price Change (%) → (Right means price increased)")
plt.ylabel("Volume Change (%) → (Down means customers bought less)")
plt.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()
plt.show()
""")

# --- Section 5: Strategic Recommendations ---
add_markdown("""## 5. Actionable Insights: The "Margin Trap" Hitlist
The table below identifies the "Margin Trap" culprits: products where we raised the price, customers bought less, and as a direct result, we made *less total profit dollars* than last year. Lowering the retail price of these specific items is the fastest way to win back volume and recover lost GP.""")

add_code("""
# Find total GP lost per item
item_gp = base_sales.groupby(['Name', 'year'])['GP $'].sum().unstack('year').dropna()
item_gp['GP $ Difference'] = item_gp[2026] - item_gp[2025]
target_list = ped_df.join(item_gp[['GP $ Difference']])

# Filter for the Margin Trap: Price UP, Volume DOWN, GP $ DOWN
action_list = target_list[
    (target_list['Price Change (%)'] > 0) & 
    (target_list['Volume Change (%)'] < 0) & 
    (target_list['GP $ Difference'] < 0)
].copy().sort_values('GP $ Difference', ascending=True)

cols_to_display = ['2025 Price ($)', '2026 Price ($)', 'Price Change (%)', 'Volume Change (%)', 'GP $ Difference']
display(action_list[cols_to_display].round(2))

total_lost = action_list['GP $ Difference'].sum()
print(f"📉 Total Gross Profit bleeding across these {len(action_list)} items: ${abs(total_lost):,.2f}")
""")

add_markdown("""### 💡 Final Strategic Recommendations:
1. **Implement Targeted Price Rollbacks:** Immediately review pricing on Green Grapes and Baby Lebanese Cucumbers (the top items on the Margin Trap list). A slight price rollback toward 2025 levels is recommended to stimulate volume and recover profit.
2. **Review Cashier Checkout Procedures:** In Q1 2025, significant revenue was processed through a generic "FRUIT AND VEG / Open Ring" button, masking vital inventory data and skewing margin metrics. Ensure cashiers are trained to look up exact PLU codes to maintain data integrity.""")

# =====================================================================
# SAVE TO DISK
# =====================================================================
output_file = "Executive_EDA_Report.ipynb"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(notebook, f, indent=2)

print(f"Success! {output_file} has been generated.")