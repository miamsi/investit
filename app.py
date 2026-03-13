import streamlit as st
import yfinance as yf
import pandas as pd

st.title("Investment Card Monitor")

portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM"],
    "Buy Min": [3400, 2200, 3500],
    "Buy Max": [3650, 2500, 3900]
}

df = pd.DataFrame(portfolio)

prices = []
ma200_list = []
distance_list = []
ma_signal_list = []

for ticker in df["Ticker"]:

    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")

    price = hist["Close"].iloc[-1]
    ma200 = hist["Close"].rolling(200).mean().iloc[-1]

    distance = (price - ma200) / ma200 * 100

    if distance > 8:
        ma_signal = "WAIT"
    elif distance > 2:
        ma_signal = "WATCH"
    elif distance > -3:
        ma_signal = "BUY"
    else:
        ma_signal = "STRONG BUY"

    prices.append(price)
    ma200_list.append(ma200)
    distance_list.append(distance)
    ma_signal_list.append(ma_signal)

df["Current Price"] = prices
df["MA200"] = ma200_list
df["MA200 Distance %"] = distance_list
df["MA Signal"] = ma_signal_list


def decision(row):

    if row["Current Price"] <= row["Buy Max"] and row["Current Price"] >= row["Buy Min"]:
        return "BUY ZONE"

    elif row["Current Price"] < row["Buy Min"]:
        return "STRONG BUY"

    else:
        return "WAIT"


df["Decision"] = df.apply(decision, axis=1)

st.dataframe(df)
