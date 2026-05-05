import streamlit as st
import pandas as pd
import plotly.express as px

# Set page configuration
st.set_page_config(page_title="Waste Dashboard", page_icon="🍎", layout="wide")

st.title("🍎 Fruit & Veg Waste Dashboard")
st.markdown("Select your visualization mode below to drill down into the waste logs.")

# Function to apply clean formatting to Plotly charts
def style_chart(fig):
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=None),
        showlegend=False,
        margin=dict(t=50)
    )
    return fig

# Function to load and clean data
@st.cache_data
def load_data():
    file_path = r"C:\Users\fabio\OneDrive\Documentos\foodland_wudinna\05_waste\FruitVeg_Waste_Log_v2.xlsx"
    df = pd.read_excel(file_path, sheet_name="Weekly Entry", skiprows=2)
    
    # Clean and format core columns
    df = df.dropna(subset=['Date', 'Item Name'])
    df['Date'] = pd.to_datetime(df['Date'])
    df['Waste Cost'] = pd.to_numeric(df['Waste/Markdown Cost $'], errors='coerce').fillna(0).abs()
    df['New Price'] = pd.to_numeric(df['New Price'], errors='coerce').fillna(0)
    df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0)
    
    # Standardize 'Unit'
    df['Unit'] = df['Unit'].fillna('each').astype(str).str.lower().str.strip()
    
    # Date properties
    df['Week'] = df['Date'].dt.isocalendar().week
    df['DayName'] = df['Date'].dt.day_name()
    
    # --- STIR FRY LOGIC ---
    is_stir_fry = df['Action'].astype(str).str.lower().str.contains('stir fry')
    df['Stir Fry Saved'] = 0.0
    df.loc[is_stir_fry, 'Stir Fry Saved'] = df.loc[is_stir_fry, 'Waste Cost']
    df.loc[is_stir_fry, 'Waste Cost'] = 0.0
    
    return df

df = load_data()

# Toggle Menu for View Mode
view_mode = st.radio("Select View:", ["Daily Visualization", "Weekly Visualization"], horizontal=True)
st.markdown("---")

if view_mode == "Daily Visualization":
    # 1. Dropdown for Day Selection (Formatted as DD-MM-YYYY)
    available_days = sorted(df['Date'].dt.date.unique(), reverse=True)
    selected_day = st.selectbox(
        "📅 Select Date:", 
        available_days, 
        format_func=lambda x: x.strftime('%d-%m-%Y')
    )
    
    filtered_df = df[df['Date'].dt.date == selected_day]
    
    # 2. Calculations for Numbers/KPIs
    total_waste_cost = filtered_df['Waste Cost'].sum()
    
    kg_df = filtered_df[filtered_df['Unit'].isin(['kg', 'kilogram'])]
    qty_df = filtered_df[~filtered_df['Unit'].isin(['kg', 'kilogram'])]
    total_kg = kg_df['Qty'].sum()
    total_each = qty_df['Qty'].sum()
    
    reduced_df = filtered_df[filtered_df['Action'].astype(str).str.lower() == 'reduced']
    saved_markdown = (reduced_df['Qty'] * reduced_df['New Price']).sum()
    
    saved_stir_fry = filtered_df['Stir Fry Saved'].sum()
    
    # 3. Display KPIs
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Waste Cost", f"${total_waste_cost:.2f}")
    c2.metric("Total Waste (Weight)", f"{total_kg:.2f} kg")
    c3.metric("Total Waste (Qty)", f"{total_each:.0f} items")
    c4.metric("Saved via Markdown", f"${saved_markdown:.2f}")
    c5.metric("Saved via Stir Fry", f"${saved_stir_fry:.2f}")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_chart, col_table = st.columns(2)
    
    with col_chart:
        # 4. Action Taken Bar Chart
        action_df = filtered_df.groupby('Action')['Waste Cost'].sum().reset_index()
        action_df = action_df[action_df['Waste Cost'] > 0] 
        
        if not action_df.empty:
            fig_action = px.bar(action_df, x='Action', y='Waste Cost', 
                                title='Waste Cost by Action', color='Action',
                                text='Waste Cost',
                                color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_action.update_traces(texttemplate='$%{text:.2f}', textposition='outside', cliponaxis=False)
            fig_action = style_chart(fig_action)
            st.plotly_chart(fig_action, use_container_width=True)
        else:
            st.info("No recorded waste cost for this day.")
            
    with col_table:
        # 5. Top 10 Wasted Items Table
        st.markdown("### ⚠️ Top Wasted Items")
        waste_items_df = filtered_df[filtered_df['Waste Cost'] > 0]
        if not waste_items_df.empty:
            top10 = waste_items_df.groupby(['Item Name', 'Unit'])[['Waste Cost', 'Qty']].sum().reset_index()
            top10 = top10.sort_values('Waste Cost', ascending=False).head(10)
            
            top10['Waste Cost'] = top10['Waste Cost'].apply(lambda x: f"${x:.2f}")
            top10['Qty'] = top10['Qty'].apply(lambda x: f"{x:.2f}")
            
            # Reorder columns: Unit after Qty
            top10 = top10[['Item Name', 'Qty', 'Unit', 'Waste Cost']]
            
            st.dataframe(top10, use_container_width=True, hide_index=True)
        else:
            st.info("No wasted items to display.")

else:
    # WEEKLY VISUALIZATION
    # 1. Dropdown for Week Selection
    available_weeks = sorted(df['Week'].unique(), reverse=True)
    selected_week = st.selectbox("📅 Select Week Number:", available_weeks)
    
    filtered_df = df[df['Week'] == selected_week]
    
    # Display the Date Range for the selected week
    if not filtered_df.empty:
        min_date = filtered_df['Date'].min().strftime('%d-%m-%Y')
        max_date = filtered_df['Date'].max().strftime('%d-%m-%Y')
        st.markdown(f"**📅 Date Range for Week {selected_week}:** `{min_date}` to `{max_date}`")
    
    # 2. Calculations for Numbers/KPIs
    total_waste_cost = filtered_df['Waste Cost'].sum()
    
    kg_df = filtered_df[filtered_df['Unit'].isin(['kg', 'kilogram'])]
    qty_df = filtered_df[~filtered_df['Unit'].isin(['kg', 'kilogram'])]
    total_kg = kg_df['Qty'].sum()
    total_each = qty_df['Qty'].sum()
    
    reduced_df = filtered_df[filtered_df['Action'].astype(str).str.lower() == 'reduced']
    saved_markdown = (reduced_df['Qty'] * reduced_df['New Price']).sum()
    
    saved_stir_fry = filtered_df['Stir Fry Saved'].sum()
    
    # 3. Display KPIs
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Waste Cost", f"${total_waste_cost:.2f}")
    c2.metric("Total Waste (Weight)", f"{total_kg:.2f} kg")
    c3.metric("Total Waste (Qty)", f"{total_each:.0f} items")
    c4.metric("Saved via Markdown", f"${saved_markdown:.2f}")
    c5.metric("Saved via Stir Fry", f"${saved_stir_fry:.2f}")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 4. Total waste by day of the week (Bar Chart)
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_df = filtered_df.groupby('DayName')['Waste Cost'].sum().reset_index()
    
    day_df['DayName'] = pd.Categorical(day_df['DayName'], categories=day_order, ordered=True)
    day_df = day_df.sort_values('DayName')
    
    if not day_df.empty and day_df['Waste Cost'].sum() > 0:
        fig_day = px.bar(day_df, x='DayName', y='Waste Cost', 
                         title="Total Waste Cost by Day of the Week",
                         text='Waste Cost',
                         color='Waste Cost', color_continuous_scale='Blues')
        fig_day.update_traces(texttemplate='$%{text:.2f}', textposition='outside', cliponaxis=False)
        fig_day = style_chart(fig_day)
        st.plotly_chart(fig_day, use_container_width=True)
        
    col_chart, col_table = st.columns(2)
    
    with col_chart:
        # 5. Action Taken Bar Chart
        action_df = filtered_df.groupby('Action')['Waste Cost'].sum().reset_index()
        action_df = action_df[action_df['Waste Cost'] > 0]
        
        if not action_df.empty:
            fig_action = px.bar(action_df, x='Action', y='Waste Cost', 
                                title='Waste Cost by Action', color='Action',
                                text='Waste Cost',
                                color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_action.update_traces(texttemplate='$%{text:.2f}', textposition='outside', cliponaxis=False)
            fig_action = style_chart(fig_action)
            st.plotly_chart(fig_action, use_container_width=True)
            
    with col_table:
        # 6. Top 10 Wasted Items Table
        st.markdown("### ⚠️ Top Wasted Items")
        waste_items_df = filtered_df[filtered_df['Waste Cost'] > 0]
        if not waste_items_df.empty:
            top10 = waste_items_df.groupby(['Item Name', 'Unit'])[['Waste Cost', 'Qty']].sum().reset_index()
            top10 = top10.sort_values('Waste Cost', ascending=False).head(10)
            
            top10['Waste Cost'] = top10['Waste Cost'].apply(lambda x: f"${x:.2f}")
            top10['Qty'] = top10['Qty'].apply(lambda x: f"{x:.2f}")
            
            # Reorder columns: Unit after Qty
            top10 = top10[['Item Name', 'Qty', 'Unit', 'Waste Cost']]
            
            st.dataframe(top10, use_container_width=True, hide_index=True)
        else:
            st.info("No wasted items to display.")