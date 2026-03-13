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

# Remove rows with missing prices
stocks = stocks.dropna(subset=["live_price_2026"])
bonds = bonds.dropna(subset=["LATEST PRICE PER UNIT"])

# -----------------------------
# USER INPUT
# -----------------------------

st.sidebar.header("Investment Preferences")

capital = st.sidebar.number_input("Investment Capital (IDR)",value=30000000)

stock_percent = st.sidebar.slider("Stock Allocation %",0,100,60)
bond_percent = 100 - stock_percent

min_dividend = st.sidebar.number_input("Minimal Stock Dividend Yield %",value=3.0)
min_coupon = st.sidebar.number_input("Minimal Bond Coupon %",value=6.0)

growth_preference = st.sidebar.selectbox(
    "Stock Preference",
    ["Capital Growth","High Dividend"]
)

max_stocks = st.sidebar.slider("Maximum Number of Stocks",1,20,5)
max_bonds = st.sidebar.slider("Maximum Number of Bonds",1,20,3)

# -----------------------------
# FILTER STOCKS
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
    "score",ascending=False
).head(max_stocks)

# -----------------------------
# FILTER BONDS
# -----------------------------

bond_candidates = bonds[
    bonds["YEARLY COUPON RATE"] >= min_coupon
].copy()

bond_candidates = bond_candidates.sort_values(
    "YEARLY COUPON RATE",
    ascending=False
).head(max_bonds)

# -----------------------------
# SHOW DATA
# -----------------------------

st.subheader("Stock Candidates")
st.dataframe(stock_candidates)

st.subheader("Bond Candidates")
st.dataframe(bond_candidates)

# -----------------------------
# GENERATE PORTFOLIO
# -----------------------------

if st.button("Generate Portfolio Options"):

    client = Groq(api_key=st.secrets["GROQ_API_KEY"])

    stocks_ai = stock_candidates[
        ["ticker","live_price_2026","dividend_yield"]
    ].to_json(orient="records")

    bonds_ai = bond_candidates[
        ["BOND'S CODE","LATEST PRICE PER UNIT","YEARLY COUPON RATE"]
    ].to_json(orient="records")

    prompt = f"""
You are an Indonesian investment advisor.

Capital: {capital}
Stock allocation target: {stock_percent}%
Bond allocation target: {bond_percent}%

Available Stocks:
{stocks_ai}

Available Bonds:
{bonds_ai}

Create 3 portfolios.

Rules:
- Use only provided assets
- Allocation must sum to 100
- Do not invent assets

Return JSON ONLY.

[
{{
"name":"Portfolio A",
"allocation":[
{{"asset":"BBCA","percent":30}},
{{"asset":"FR0080","percent":40}}
]
}}
]
"""

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3
    )

    raw = completion.choices[0].message.content

    try:
        portfolios = json.loads(raw)
    except:
        st.error("AI returned invalid JSON")
        st.write(raw)
        st.stop()

# -----------------------------
# LOOKUPS
# -----------------------------

    stock_lookup = stock_candidates.set_index("ticker")
    bond_lookup = bond_candidates.set_index("BOND'S CODE")

# -----------------------------
# BUILD PORTFOLIOS
# -----------------------------

    summary_text = ""

    for p in portfolios:

        st.subheader(p["name"])

        rows = []

        for a in p["allocation"]:

            asset = str(a["asset"]).replace(".JK","").strip()
            percent = a["percent"]

            amount = capital * percent/100

# -----------------------------
# STOCK
# -----------------------------

            if asset in stock_lookup.index:

                price = stock_lookup.loc[asset]["live_price_2026"]
                dy = stock_lookup.loc[asset]["dividend_yield"]/100

                if pd.isna(price) or price <= 0:
                    shares = 0
                    income = 0
                else:
                    shares = amount/price
                    income = amount*dy

                rows.append({
                    "Asset":asset,
                    "Allocation":f"{percent}%",
                    "Amount":amount,
                    "Units":int(shares),
                    "Income":income
                })

# -----------------------------
# BOND
# -----------------------------

            elif asset in bond_lookup.index:

                price = bond_lookup.loc[asset]["LATEST PRICE PER UNIT"]
                coupon = bond_lookup.loc[asset]["YEARLY COUPON RATE"]/100

                if pd.isna(price) or price <= 0:
                    units = 0
                    income = 0
                else:
                    units = amount/price
                    income = units*1000000*coupon

                rows.append({
                    "Asset":asset,
                    "Allocation":f"{percent}%",
                    "Amount":amount,
                    "Units":int(units),
                    "Income":income
                })

        df = pd.DataFrame(rows)

# -----------------------------
# TOTALS
# -----------------------------

        total_amount = df["Amount"].sum()
        total_income = df["Income"].sum()

        total_row = pd.DataFrame([{
            "Asset":"TOTAL",
            "Allocation":"100%",
            "Amount":total_amount,
            "Units":"",
            "Income":total_income
        }])

        df = pd.concat([df,total_row],ignore_index=True)

# -----------------------------
# FORMAT
# -----------------------------

        df["Amount"] = df["Amount"].apply(lambda x: f"Rp {x:,.0f}" if x!="" else "")
        df["Income"] = df["Income"].apply(lambda x: f"Rp {x:,.0f}" if x!="" else "")

        df = df.rename(columns={
            "Units":"Shares / Units",
            "Income":"Annual Income"
        })

        st.dataframe(df,use_container_width=True)

# -----------------------------
# SUMMARY
# -----------------------------

        monthly_income = total_income/12

        summary_text += f"""
{p['name']}
Capital: {capital}
Annual Income: {round(total_income)}
Monthly Income: {round(monthly_income)}
Assets: {', '.join([x['asset'] for x in p['allocation']])}

"""

# -----------------------------
# AI EXPLANATION
# -----------------------------

    explanation_prompt = f"""
You are a financial advisor.

Below are 3 portfolios.

{summary_text}

Explain the differences between them.

Rules:
- Text only
- No tables
- No new numbers
"""

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":explanation_prompt}],
        temperature=0.4
    )

    explanation = completion.choices[0].message.content

    st.subheader("AI Portfolio Explanation")
    st.write(explanation)
