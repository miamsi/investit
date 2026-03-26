import streamlit as st
import yfinance as yf
import pandas as pd
from supabase import create_client
import datetime
from groq import Groq

st.set_page_config(page_title="Investment Card Monitor", layout="wide")

# -------------------------
# FORMAT RUPIAH
# -------------------------

def format_rupiah(value):
    if pd.isna(value):
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")

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
# GROQ CLIENT
# -------------------------

groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# -------------------------
# HEADER
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
# PORTFOLIO
# -------------------------

portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK", "BSSR.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM", "BSSR"],
    "Buy Min": [3400, 2200, 3500, 3600],
    "Buy Max": [3650, 2500, 3900, 4200],
    "Target Capital": [11880000, 3600000, 6080000, 5400000]
}

df = pd.DataFrame(portfolio)

# -------------------------
# PEER GROUPS
# -------------------------

peer_groups = {
    "BBRI.JK": ["BMRI.JK","BBCA.JK"],
    "PTBA.JK": ["ADRO.JK","ITMG.JK"],
    "TLKM.JK": ["EXCL.JK","ISAT.JK"],
    "BSSR.JK": ["ADRO.JK","ITMG.JK"]
}

# -------------------------
# MARKET DATA
# -------------------------

@st.cache_data(ttl=300)
def get_stock_data(ticker):

    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")

    price = hist["Close"].iloc[-1]
    ma200 = hist["Close"].rolling(200).mean().iloc[-1]

    month_change = (hist["Close"].iloc[-1] - hist["Close"].iloc[-22]) / hist["Close"].iloc[-22] * 100

    return price, ma200, month_change

def get_peer_performance(peers):

    perf = []

    for p in peers:
        try:
            hist = yf.Ticker(p).history(period="1mo")
            change = (hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100
            perf.append(change)
        except:
            continue

    if len(perf)==0:
        return 0

    return sum(perf)/len(perf)

prices=[]
ma200_list=[]
distance_list=[]
ma_signal_list=[]
peer_perf=[]
stock_perf=[]
low_52_list=[]
dist_low_list=[]

for ticker in df["Ticker"]:

    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")

    price = hist["Close"].iloc[-1]
    ma200 = hist["Close"].rolling(200).mean().iloc[-1]
    low_52 = hist["Low"].min()

    change = (hist["Close"].iloc[-1] - hist["Close"].iloc[-22]) / hist["Close"].iloc[-22] * 100
    distance = (price - ma200) / ma200 * 100
    dist_low = (price - low_52) / low_52 * 100

    peers = peer_groups.get(ticker,[])
    peer_change = get_peer_performance(peers)

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
    peer_perf.append(round(peer_change,2))
    stock_perf.append(round(change,2))
    low_52_list.append(round(low_52,2))
    dist_low_list.append(round(dist_low,2))

df["Current Price"]=prices
df["MA200"]=ma200_list
df["MA200 Distance %"]=distance_list
df["MA Signal"]=ma_signal_list
df["Peer 1M %"]=peer_perf
df["Stock 1M %"]=stock_perf
df["52W Low"]=low_52_list
df["Dist From Low %"]=dist_low_list

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

df["Decision"]=df.apply(decision,axis=1)

# -------------------------
# AI SIGNAL
# -------------------------

def ai_signal(row):

    if row["Decision"]=="BUY ZONE" and row["MA Signal"] in ["BUY","STRONG BUY"]:
        return "BUY"

    if row["Decision"]=="WAIT" and row["Peer 1M %"]>0:
        return "WATCH"

    if row["MA Signal"]=="OVEREXTENDED":
        return "WAIT"

    return "WAIT"

df["AI Buy Signal"]=df.apply(ai_signal,axis=1)

# -------------------------
# AI INTERPRETATION
# -------------------------

def ai_interpretation(row):

    if row["AI Buy Signal"] == "BUY":
        return "Undervalued. Accumulation zone."

    if row["MA Signal"] == "OVEREXTENDED":
        return "Too hot. Wait for pullback."

    if row["Decision"] == "WAIT" and row["Peer 1M %"] > 0:
        return "Sector strong. Stock lagging."

    if row["Dist From Low %"] < 10:
        return "Near bottom. Good risk reward."

    return "No edge."

df["AI Interpretation"]=df.apply(ai_interpretation,axis=1)

# -------------------------
# ALTERNATIVE ENGINE
# -------------------------

def alternative(row):

    if row["AI Buy Signal"] == "BUY":
        return "-"

    peers = peer_groups.get(row["Ticker"], [])

    for p in peers:
        try:
            price, ma200, _ = get_stock_data(p)
            distance = (price - ma200) / ma200 * 100

            if distance < -3:
                return p.replace(".JK","")
        except:
            continue

    return "-"

df["Alternative"]=df.apply(alternative,axis=1)

# -------------------------
# SCORE ENGINE
# -------------------------

def score(row):

    s = 0

    if row["MA200 Distance %"] < -3:
        s += 2

    if row["Dist From Low %"] < 15:
        s += 2

    if row["Decision"] == "BUY ZONE":
        s += 3

    div_map = {
        "PTBA": 12,
        "BBRI": 5,
        "TLKM": 6,
        "BSSR": 10
    }

    est_yield = div_map.get(row["Stock"], 0)

    if est_yield > 10:
        s += 2
    elif est_yield > 7:
        s += 1

    return s

df["Score"]=df.apply(score,axis=1)

# -------------------------
# DIVIDEND DEADLINE
# -------------------------

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

df["Last Buy Date"]=last_buy_dates
df["Days Left"]=days_left

# -------------------------
# LOAD TRANSACTIONS
# -------------------------

response=supabase.table("transactions").select("*").execute()
transactions=pd.DataFrame(response.data)

if not transactions.empty:

    avg_price = transactions.groupby("ticker").apply(
        lambda x:(x["shares"]*x["price"]).sum()/x["shares"].sum()
    )

    avg_price = avg_price.reset_index(name="Avg Price")

    df=df.merge(avg_price,how="left",left_on="Stock",right_on="ticker")

    summary = transactions.groupby("ticker")["capital_used"].sum().reset_index()

    df=df.merge(summary,how="left",left_on="Stock",right_on="ticker")

else:
    df["Avg Price"]=0
    df["capital_used"]=0

df["capital_used"]=df["capital_used"].fillna(0)
df["Avg Price"]=df["Avg Price"].fillna(0)

df["Remaining Capital"]=df["Target Capital"]-df["capital_used"]
df["Gain/Loss %"]=((df["Current Price"]-df["Avg Price"])/df["Avg Price"]*100).fillna(0)

# -------------------------
# DISPLAY
# -------------------------

st.subheader("Market Signals")

market_df = df.copy()

market_df["Current Price"] = market_df["Current Price"].apply(format_rupiah)
market_df["Buy Min"] = market_df["Buy Min"].apply(format_rupiah)
market_df["Buy Max"] = market_df["Buy Max"].apply(format_rupiah)
market_df["MA200"] = market_df["MA200"].apply(format_rupiah)

st.dataframe(market_df[[
"Stock","Current Price","Buy Min","Buy Max","MA200",
"MA200 Distance %","Dist From Low %","Score",
"MA Signal","Decision","AI Buy Signal","Alternative","AI Interpretation"
]])

st.subheader("Portfolio Performance")

perf_df = df.copy()
perf_df["Avg Price"] = perf_df["Avg Price"].apply(format_rupiah)
perf_df["Current Price"] = perf_df["Current Price"].apply(format_rupiah)

st.dataframe(perf_df[["Stock","Avg Price","Current Price","Gain/Loss %"]])

st.subheader("Portfolio Deployment")

progress_df=df[["Stock","Target Capital","capital_used","Remaining Capital"]].copy()
progress_df.columns=["Stock","Target","Invested","Remaining"]

progress_df["Target"]=progress_df["Target"].apply(format_rupiah)
progress_df["Invested"]=progress_df["Invested"].apply(format_rupiah)
progress_df["Remaining"]=progress_df["Remaining"].apply(format_rupiah)

st.dataframe(progress_df)

total_target=df["Target Capital"].sum()
total_used=df["capital_used"].sum()

progress=total_used/total_target if total_target>0 else 0

st.progress(progress)

st.write(f"Capital Used: {format_rupiah(total_used)}")
st.write(f"Remaining Capital: {format_rupiah(total_target-total_used)}")

# -------------------------
# EXECUTE BUY
# -------------------------

st.subheader("Execute Buy")

ticker_choice=st.selectbox("Stock",df["Stock"])
shares=st.number_input("Shares",min_value=1,step=1)
price=st.number_input("Execution Price",min_value=1.0,step=1.0)

if st.button("Record Buy"):

    capital=shares*price

    supabase.table("transactions").insert({
        "ticker":ticker_choice,
        "shares":shares,
        "price":price,
        "capital_used":capital
    }).execute()

    st.success("Trade recorded")

# -------------------------
# TRANSACTION HISTORY
# -------------------------

st.subheader("Transaction History")

if not transactions.empty:

    trans_df = transactions.copy()
    trans_df["capital_used"] = trans_df["capital_used"].apply(format_rupiah)

    st.dataframe(trans_df[[
    "ticker","shares","price","capital_used","created_at"
    ]])

else:
    st.write("No trades recorded yet.")

# -------------------------
# FUNDAMENTALS
# -------------------------

@st.cache_data(ttl=3600)
def get_fundamentals(ticker):

    stock=yf.Ticker(ticker)
    info=stock.info

    return{
    "Ticker":ticker,
    "Price":info.get("currentPrice"),
    "PE":info.get("trailingPE"),
    "PB":info.get("priceToBook"),
    "Dividend Yield":info.get("dividendYield"),
    "ROE":info.get("returnOnEquity"),
    "Beta":info.get("beta")
    }

fundamentals=[get_fundamentals(t) for t in portfolio["Ticker"]]
fundamental_df=pd.DataFrame(fundamentals)

st.subheader("Fundamental Snapshot")
st.dataframe(fundamental_df)

# -------------------------
# AI REPORT
# -------------------------

def generate_ai_report():

    prompt=f"""
Analisis portofolio saham Indonesia.

DATA FUNDAMENTAL:
{fundamental_df.to_string(index=False)}

DATA MARKET:
{df.to_string(index=False)}

Berikan analisis per saham dan kesimpulan.
"""

    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3
    )

    return completion.choices[0].message.content

st.subheader("AI Portfolio Analyst")

if st.button("Generate AI Analysis"):
    with st.spinner("Analyzing market..."):
        report=generate_ai_report()
        st.markdown(report)
