import streamlit as st
import yfinance as yf
import pandas as pd

st.title("📊 Investment Portfolio Dashboard")

# --- Portfolio Data ---
data = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK", "ANTM.JK", "PNBN.JK", "TAPG.JK"],
    "Shares": [3300, 3600, 1600, 1000, 1000, 1000],
    "Buy Price": [3600, 2400, 3800, 1500, 1500, 4000],
    "Dividend Yield": [0.09, 0.18, 0.075, 0.05, 0.02, 0.06]
}

df = pd.DataFrame(data)

# --- Get Market Data ---
prices = []
for ticker in df["Ticker"]:
    stock = yf.Ticker(ticker)
    price = stock.history(period="1d")["Close"].iloc[-1]
    prices.append(price)

df["Current Price"] = prices

# --- Calculations ---
df["Market Value"] = df["Shares"] * df["Current Price"]
df["Cost Basis"] = df["Shares"] * df["Buy Price"]
df["Unrealized P/L"] = df["Market Value"] - df["Cost Basis"]
df["Dividend Income"] = df["Market Value"] * df["Dividend Yield"]

# --- Display Table ---
st.subheader("📈 Stock Portfolio")
st.dataframe(df)

# --- Totals ---
total_value = df["Market Value"].sum()
total_cost = df["Cost Basis"].sum()
total_pl = df["Unrealized P/L"].sum()
total_dividend = df["Dividend Income"].sum()

# --- Bonds (manual input) ---
st.subheader("💰 Bond Income")

bond_nominal = st.number_input("Total Bond Nominal", value=50000000)
bond_coupon = st.number_input("Average Coupon Rate", value=0.064)

bond_income = bond_nominal * bond_coupon * 0.9

# --- Portfolio Summary ---
st.subheader("📊 Portfolio Summary")

st.metric("Portfolio Value", f"Rp {total_value:,.0f}")
st.metric("Unrealized P/L", f"Rp {total_pl:,.0f}")
st.metric("Estimated Stock Dividend", f"Rp {total_dividend:,.0f}")
st.metric("Bond Income", f"Rp {bond_income:,.0f}")

total_income = total_dividend + bond_income

st.subheader("💵 Total Annual Cashflow")

st.metric("Total Income", f"Rp {total_income:,.0f}")
