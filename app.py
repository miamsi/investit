import streamlit as st
import pandas as pd
from groq import Groq
import json

st.set_page_config(layout="wide")

st.title("📊 Indonesian Investment Portfolio Advisor")

# -----------------------------
# LOAD DATA
# -----------------------------

@st.cache_data
def load_stock_data():
    return pd.read_csv("master_schedule_rows.csv")

@st.cache_data
def load_bonds():
    return pd.read_excel("LIST HARGA OBLIGASI PER 12 MARET 2026.xlsx")

stocks = load_stock_data()
bonds = load_bonds()

# -----------------------------
# USER INPUT
# -----------------------------

st.sidebar.header("Investment Preferences")

capital = st.sidebar.number_input(
    "Investment Capital (IDR)",
    value=30000000
)

stock_percent = st.sidebar.slider(
    "Stock Allocation %",
    0,100,60
)

bond_percent = 100 - stock_percent

min_dividend = st.sidebar.number_input(
    "Minimal Stock Dividend Yield %",
    value=3.0
)

min_coupon = st.sidebar.number_input(
    "Minimal Bond Coupon %",
    value=6.0
)

growth_preference = st.sidebar.selectbox(
    "Stock Preference",
    [
        "Capital Growth",
        "High Dividend"
    ]
)

max_stocks = st.sidebar.slider(
    "Maximum Number of Stocks",
    1,20,5
)

max_bonds = st.sidebar.slider(
    "Maximum Number of Bonds",
    1,20,3
)

# -----------------------------
# PREPROCESS STOCKS
# -----------------------------

stock_candidates = stocks[
    stocks["dividend_yield"] >= min_dividend
].copy()

if growth_preference == "Capital Growth":

    stock_candidates["score"] = (
        stock_candidates["predicted_high"] -
        stock_candidates["live_price_2026"]
    ) / stock_candidates["live_price_2026"]

else:

    stock_candidates["score"] = stock_candidates["dividend_yield"]

stock_candidates = stock_candidates.sort_values(
    "score",
    ascending=False
).head(max_stocks)

# -----------------------------
# PREPROCESS BONDS
# -----------------------------

bond_candidates = bonds[
    bonds["YEARLY COUPON RATE"] >= min_coupon
].copy()

bond_candidates = bond_candidates.sort_values(
    "YEARLY COUPON RATE",
    ascending=False
).head(max_bonds)

# -----------------------------
# SHOW CANDIDATES
# -----------------------------

st.subheader("Stock Candidates")
st.dataframe(stock_candidates)

st.subheader("Bond Candidates")
st.dataframe(bond_candidates)

# -----------------------------
# BUILD RETURN LOOKUP
# -----------------------------

stock_returns = {}

for _, r in stock_candidates.iterrows():

    growth = (
        r["predicted_high"] -
        r["live_price_2026"]
    ) / r["live_price_2026"]

    total_return = growth + r["dividend_yield"]/100

    stock_returns[r["ticker"]] = total_return

bond_returns = {}

for _, r in bond_candidates.iterrows():

    bond_returns[r["BOND'S CODE"]] = r["YEARLY COUPON RATE"]/100

# -----------------------------
# AI PORTFOLIO GENERATION
# -----------------------------

if st.button("Generate Portfolio Options"):

    client = Groq(api_key=st.secrets["GROQ_API_KEY"])

    stock_json = stock_candidates.to_json(orient="records")
    bond_json = bond_candidates.to_json(orient="records")

    prompt = f"""
You are an Indonesian investment advisor.

IMPORTANT:
Use asset names EXACTLY as provided in the dataset. Do not modify tickers. Use bahasa Indonesia.

Capital: {capital}
Stock allocation: {stock_percent}%
Bond allocation: {bond_percent}%

Available stocks:
{stock_json}

Available bonds:
{bond_json}

Create 3 different portfolios.

Return JSON only like this:

[
{{
"name":"Portfolio A",
"allocation":[
{{"asset":"BBCA.JK","percent":30}},
{{"asset":"BBRI.JK","percent":30}},
{{"asset":"FR0080","percent":40}}
],
"strength":"...",
"weakness":"..."
}}
]
"""

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    result = json.loads(
        completion.choices[0].message.content
    )

# -----------------------------
# BUILD TABLES
# -----------------------------

    for p in result:

        st.subheader(p["name"])

        df = pd.DataFrame(p["allocation"])

        df = df.rename(columns={
            "asset":"Asset",
            "percent":"Allocation %"
        })

        df["Amount"] = df["Allocation %"]/100 * capital

        def get_return(asset):
            asset = str(asset).strip()
            if asset in stock_returns:
                return stock_returns[asset]
            if asset in bond_returns:
                return bond_returns[asset]
            asset_clean = asset.replace(".JK","")
            for k in stock_returns:
                if asset_clean in k:
                    return stock_returns[k]
            for k in bond_returns:
                if asset_clean in k:
                    return bond_returns[k]
            return 0

        df["Return %"] = df["Asset"].apply(get_return).fillna(0)
        df["Return (Rp)"] = df["Amount"].astype(float) * df["Return %"]

# -----------------------------
# TOTAL ROW
# -----------------------------

        total_allocation = df["Allocation %"].sum()
        total_amount = df["Amount"].sum()
        total_return_rp = df["Return (Rp)"].sum()

        total_row = pd.DataFrame([{
            "Asset":"TOTAL",
            "Allocation %":total_allocation,
            "Amount":total_amount,
            "Return %":"",
            "Return (Rp)":total_return_rp
        }])

        df = pd.concat([df,total_row],ignore_index=True)

# -----------------------------
# FORMAT TABLE
# -----------------------------

        df["Allocation"] = df["Allocation %"].apply(
            lambda x: "" if x=="" else f"{x:.0f}%"
        )

        df["Amount"] = df["Amount"].apply(
            lambda x: f"Rp {x:,.0f}"
        )

        df["Return %"] = df["Return %"].apply(
            lambda x: "" if x=="" else f"{x*100:.2f}%"
        )

        df["Return (Rp)"] = df["Return (Rp)"].apply(
            lambda x: f"Rp {x:,.0f}"
        )

        df = df[[
            "Asset",
            "Allocation",
            "Amount",
            "Return %",
            "Return (Rp)"
        ]]

        st.dataframe(df, use_container_width=True)

        st.write("Strength:", p["strength"])
        st.write("Weakness:", p["weakness"])
