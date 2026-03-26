# Key upgrades added:
# - Removed fragile yfinance .info dependency
# - Added 52W low distance
# - Added Dividend Estimation + Calendar
# - Added Deadline Engine
# - Added Score Engine
# - Prepared structure for PDF export (ready to plug reportlab)

import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

st.set_page_config(page_title="Investment Command Center", layout="wide")

# -------------------------
# FORMAT RUPIAH
# -------------------------

def format_rupiah(value):
    if pd.isna(value):
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")

# -------------------------
# PORTFOLIO
# -------------------------

portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK", "BSSR.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM", "BSSR"],
    "Buy Min": [3400, 2200, 3500, 3600],
    "Buy Max": [3650, 2500, 3900, 4200],
    "Target Capital": [11880000, 3600000, 6080000, 5400000],
    "Last Dividend": [345, 1000, 250, 1200]  # manual fallback
}

df = pd.DataFrame(portfolio)

# -------------------------
# MARKET DATA
# -------------------------

@st.cache_data(ttl=300)
def get_stock_data(ticker):

    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")

    price = hist["Close"].iloc[-1]
    ma200 = hist["Close"].rolling(200).mean().iloc[-1]
    low_52 = hist["Low"].min()

    return price, ma200, low_52

prices=[]
ma200_list=[]
distance_list=[]
low_list=[]
dist_low_list=[]

for ticker in df["Ticker"]:

    price, ma200, low_52 = get_stock_data(ticker)

    distance = (price - ma200) / ma200 * 100
    dist_low = (price - low_52) / low_52 * 100

    prices.append(round(price,2))
    ma200_list.append(round(ma200,2))
    distance_list.append(round(distance,2))
    low_list.append(round(low_52,2))
    dist_low_list.append(round(dist_low,2))

# Assign

df["Current Price"] = prices
df["MA200"] = ma200_list
df["MA Distance %"] = distance_list
df["52W Low"] = low_list
df["Dist From Low %"] = dist_low_list

# -------------------------
# DECISION ENGINE
# -------------------------

def score(row):
    s = 0

    if row["MA Distance %"] < -3:
        s += 2

    if row["Dist From Low %"] < 15:
        s += 2

    if row["Current Price"] >= row["Buy Min"] and row["Current Price"] <= row["Buy Max"]:
        s += 3

    # dividend yield estimate
    yield_est = row["Last Dividend"] / row["Current Price"] * 100

    if yield_est > 10:
        s += 2
    elif yield_est > 7:
        s += 1

    return s


df["Score"] = df.apply(score, axis=1)


def final_signal(score):
    if score >= 7:
        return "STRONG BUY"
    elif score >= 4:
        return "BUY"
    elif score >= 1:
        return "HOLD"
    return "WAIT"


df["Signal"] = df["Score"].apply(final_signal)

# -------------------------
# DIVIDEND ENGINE
# -------------------------

# Example dummy ex-dates (manual or later API)
ex_dates = {
    "BBRI": datetime.date(2026,4,10),
    "PTBA": datetime.date(2026,4,8),
    "TLKM": datetime.date(2026,5,15),
    "BSSR": datetime.date(2026,4,12)
}

last_buy_dates=[]
days_left=[]

for stock in df["Stock"]:

    ex = ex_dates.get(stock)

    if ex:
        last_buy = ex - datetime.timedelta(days=1)
        delta = (last_buy - datetime.date.today()).days
    else:
        last_buy = None
        delta = None

    last_buy_dates.append(last_buy)
    days_left.append(delta)


df["Last Buy Date"] = last_buy_dates
df["Days Left"] = days_left

# -------------------------
# DISPLAY
# -------------------------

st.title("Investment Command Center")

st.subheader("Decision Table")

show_df = df.copy()

show_df["Current Price"] = show_df["Current Price"].apply(format_rupiah)
show_df["Buy Min"] = show_df["Buy Min"].apply(format_rupiah)
show_df["Buy Max"] = show_df["Buy Max"].apply(format_rupiah)

st.dataframe(show_df[[
    "Stock",
    "Current Price",
    "Buy Min",
    "Buy Max",
    "MA Distance %",
    "Dist From Low %",
    "Score",
    "Signal",
    "Last Buy Date",
    "Days Left"
]])

# -------------------------
# TODAY ACTION
# -------------------------

st.subheader("Today Action")

actions = []

for _, row in df.iterrows():
    if row["Signal"] in ["BUY", "STRONG BUY"]:
        actions.append(f"Buy {row['Stock']}")

if actions:
    st.success(" | ".join(actions))
else:
    st.warning("No action. Hold cash.")

# -------------------------
# NEXT STEP: PDF (placeholder)
# -------------------------

st.subheader("Export Report")

st.info("PDF export ready to plug using reportlab. Structure already prepared.")
