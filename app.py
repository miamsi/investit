import streamlit as st
import yfinance as yf
import pandas as pd
from supabase import create_client
import datetime

st.set_page_config(page_title="Investment Card Monitor", layout="wide")

# -------------------------
# PASSWORD PROTECTION
# -------------------------

def check_password():

    if "password_correct" not in st.session_state:

        password = st.text_input("Enter password", type="password")

        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()

        else:
            st.stop()

    elif not st.session_state["password_correct"]:
        st.stop()

check_password()

# -------------------------
# SUPABASE CONNECTION
# -------------------------

url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]

supabase = create_client(url, key)

# -------------------------
# REFRESH BUTTON
# -------------------------

col1, col2 = st.columns([6,1])

with col1:
    st.title("Investment Card Monitor")

with col2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Last update: {datetime.datetime.now().strftime('%H:%M:%S')}")

# -------------------------
# INVESTMENT PLAN
# -------------------------

portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM"],
    "Buy Min": [3400, 2200, 3500],
    "Buy Max": [3650, 2500, 3900],
    "Target Capital": [11880000, 9000000, 6080000]
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

    return price, ma200


prices = []
ma200_list = []
distance_list = []
ma_signal_list = []

for ticker in df["Ticker"]:

    price, ma200 = get_stock_data(ticker)

    distance = (price - ma200) / ma200 * 100

    if distance > 15:
        ma_signal = "OVEREXTENDED"
    elif distance > 8:
        ma_signal = "WAIT"
    elif distance > 2:
        ma_signal = "WATCH"
    elif distance > -3:
        ma_signal = "BUY"
    else:
        ma_signal = "STRONG BUY"

    prices.append(round(price,2))
    ma200_list.append(round(ma200,2))
    distance_list.append(round(distance,2))
    ma_signal_list.append(ma_signal)

df["Current Price"] = prices
df["MA200"] = ma200_list
df["MA200 Distance %"] = distance_list
df["MA Signal"] = ma_signal_list

# -------------------------
# BUY DECISION
# -------------------------

def decision(row):

    if row["Current Price"] <= row["Buy Max"] and row["Current Price"] >= row["Buy Min"]:
        return "BUY ZONE"

    elif row["Current Price"] < row["Buy Min"]:
        return "STRONG BUY"

    else:
        return "WAIT"

df["Decision"] = df.apply(decision, axis=1)

# -------------------------
# LOAD TRANSACTIONS
# -------------------------

response = supabase.table("transactions").select("*").execute()

transactions = pd.DataFrame(response.data)

if not transactions.empty:
    summary = transactions.groupby("ticker")["capital_used"].sum().reset_index()
else:
    summary = pd.DataFrame(columns=["ticker","capital_used"])

df = df.merge(summary, how="left", left_on="Stock", right_on="ticker")

df["capital_used"] = df["capital_used"].fillna(0)

df["Remaining Capital"] = df["Target Capital"] - df["capital_used"]

# -------------------------
# MARKET SIGNAL TABLE
# -------------------------

st.subheader("Market Signals")

st.dataframe(
    df[
        [
            "Stock",
            "Current Price",
            "Buy Min",
            "Buy Max",
            "MA200",
            "MA200 Distance %",
            "MA Signal",
            "Decision"
        ]
    ]
)

# -------------------------
# PORTFOLIO PROGRESS
# -------------------------

st.subheader("Portfolio Deployment")

progress_df = df[
    ["Stock","Target Capital","capital_used","Remaining Capital"]
]

progress_df.columns = ["Stock","Target","Invested","Remaining"]

st.dataframe(progress_df)

total_target = df["Target Capital"].sum()
total_used = df["capital_used"].sum()

progress = total_used / total_target if total_target > 0 else 0

st.progress(progress)

st.write(f"Capital Used: Rp{int(total_used):,}")
st.write(f"Remaining Capital: Rp{int(total_target-total_used):,}")

# -------------------------
# EXECUTE BUY
# -------------------------

st.subheader("Execute Buy")

ticker_choice = st.selectbox("Stock", df["Stock"])

shares = st.number_input("Shares", min_value=1, step=1)

price = st.number_input("Execution Price", min_value=1.0, step=1.0)

if st.button("Record Buy"):

    capital = shares * price

    supabase.table("transactions").insert(
        {
            "ticker": ticker_choice,
            "shares": shares,
            "price": price,
            "capital_used": capital
        }
    ).execute()

    st.success("Trade recorded")

# -------------------------
# TRANSACTION HISTORY
# -------------------------

st.subheader("Transaction History")

if not transactions.empty:

    st.dataframe(
        transactions[
            [
                "ticker",
                "shares",
                "price",
                "capital_used",
                "created_at"
            ]
        ]
    )

else:

    st.write("No trades recorded yet.")
