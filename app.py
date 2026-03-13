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

capital = st.sidebar.number_input("Investment Capital (IDR)", value=30000000)

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

stock_candidates = stocks[stocks["dividend_yield"] >= min_dividend].copy()

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
# SHOW FILTERED DATA
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

    ticker = str(r["ticker"]).replace(".JK","").strip()

    growth = (
        r["predicted_high"] -
        r["live_price_2026"]
    ) / r["live_price_2026"]

    total_return = growth + r["dividend_yield"]/100

    stock_returns[ticker] = total_return

bond_returns = {}

for _, r in bond_candidates.iterrows():

    code = str(r["BOND'S CODE"]).strip()

    bond_returns[code] = r["YEARLY COUPON RATE"]/100

# -----------------------------
# GENERATE PORTFOLIOS
# -----------------------------

if st.button("Generate Portfolio Options"):

    client = Groq(api_key=st.secrets["GROQ_API_KEY"])

    stock_list = list(stock_candidates["ticker"].str.replace(".JK",""))
    bond_list = list(bond_candidates["BOND'S CODE"])

    prompt = f"""
You are an Indonesian investment advisor.

Available stocks:
{stock_list}

Available bonds:
{bond_list}

Create 3 portfolios.

Return JSON only.

Format:

[
{{
"name":"Income Portfolio",
"stocks":["BBCA","TLKM"],
"bonds":["FR0080","FR0083"]
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
# BUILD PORTFOLIO TABLES
# -----------------------------

    for p in portfolios:

        st.subheader(p["name"])

        stocks = p["stocks"]
        bonds = p["bonds"]

        assets = stocks + bonds

        allocation = 100 / len(assets)

        rows = []

        for asset in assets:

            if asset in stock_returns:
                r = stock_returns[asset]

            elif asset in bond_returns:
                r = bond_returns[asset]

            else:
                r = 0

            amount = capital * allocation / 100
            ret_rp = amount * r

            rows.append({
                "Asset":asset,
                "Allocation %":allocation,
                "Amount":amount,
                "Return %":r,
                "Return (Rp)":ret_rp
            })

        df = pd.DataFrame(rows)

# -----------------------------
# TOTAL ROW
# -----------------------------

        total = pd.DataFrame([{
            "Asset":"TOTAL",
            "Allocation %":df["Allocation %"].sum(),
            "Amount":df["Amount"].sum(),
            "Return %":None,
            "Return (Rp)":df["Return (Rp)"].sum()
        }])

        df = pd.concat([df,total],ignore_index=True)

# -----------------------------
# FORMAT DISPLAY
# -----------------------------

        display = df.copy()

        display["Allocation"] = display["Allocation %"].apply(
            lambda x: "" if pd.isna(x) else f"{x:.0f}%"
        )

        display["Amount"] = display["Amount"].apply(
            lambda x: f"Rp {x:,.0f}"
        )

        display["Return %"] = display["Return %"].apply(
            lambda x: "" if pd.isna(x) else f"{x*100:.2f}%"
        )

        display["Return (Rp)"] = display["Return (Rp)"].apply(
            lambda x: f"Rp {x:,.0f}"
        )

        display = display[[
            "Asset",
            "Allocation",
            "Amount",
            "Return %",
            "Return (Rp)"
        ]]

        st.dataframe(display,use_container_width=True)

# -----------------------------
# AI EXPLANATION
# -----------------------------

        explanation_prompt = f"""
Explain this investment portfolio in Bahasa Indonesia.

{df.to_string()}
"""

        exp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":explanation_prompt}],
            temperature=0.3
        )

        st.write(exp.choices[0].message.content)
