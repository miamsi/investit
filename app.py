import streamlit as st
import yfinance as yf
import pandas as pd

st.title("📊 Investment Card Monitor")

portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM"],
    "Buy Min": [3400, 2200, 3500],
    "Buy Max": [3650, 2500, 3900]
}

df = pd.DataFrame(portfolio)

prices = []

for ticker in df["Ticker"]:
    stock = yf.Ticker(ticker)
    price = stock.history(period="1d")["Close"].iloc[-1]
    prices.append(price)

df["Current Price"] = prices

def decision(row):
    if row["Current Price"] <= row["Buy Max"] and row["Current Price"] >= row["Buy Min"]:
        return "🟢 BUY ZONE"
    elif row["Current Price"] < row["Buy Min"]:
        return "🔥 STRONG BUY"
    else:
        return "⏳ WAIT"

df["Decision"] = df.apply(decision, axis=1)

st.subheader("Investment Entry Table")

st.dataframe(df)

st.subheader("Quick Signals")

for i,row in df.iterrows():

    if row["Decision"] == "🟢 BUY ZONE":
        st.success(f"{row['Stock']} is in BUY ZONE")

    elif row["Decision"] == "🔥 STRONG BUY":
        st.error(f"{row['Stock']} is STRONG BUY")

    else:
        st.warning(f"{row['Stock']} still above buy range")
