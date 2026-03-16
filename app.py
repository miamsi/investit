import streamlit as st
import yfinance as yf
import pandas as pd
from supabase import create_client
import datetime
from groq import Groq

st.set_page_config(page_title="Investment Card Monitor", layout="wide")

# -------------------------
# PASSWORD
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
# SUPABASE
# -------------------------

supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

# -------------------------
# GROQ
# -------------------------

groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# -------------------------
# REFRESH
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
# PORTFOLIO PLAN
# -------------------------

portfolio = {
    "Ticker": ["BBRI.JK","PTBA.JK","TLKM.JK","BSSR.JK"],
    "Stock": ["BBRI","PTBA","TLKM","BSSR"],
    "Buy Min": [3400,2200,3500,3600],
    "Buy Max": [3650,2500,3900,4200],
    "Target Capital": [11880000,3600000,6080000,5400000]
}

df = pd.DataFrame(portfolio)

# -------------------------
# PEER MAP
# -------------------------

peer_map = {

    "BBRI.JK": ["BMRI.JK","BBNI.JK","BRIS.JK"],
    "TLKM.JK": ["EXCL.JK","ISAT.JK"],
    "PTBA.JK": ["ADRO.JK","ITMG.JK","BSSR.JK"],
    "BSSR.JK": ["PTBA.JK","ADRO.JK","ITMG.JK"]

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

    return price, ma200

@st.cache_data(ttl=3600)
def get_peer_perf(ticker):

    peers = peer_map.get(ticker, [])

    changes = []

    for p in peers:

        try:

            stock = yf.Ticker(p)
            hist = stock.history(period="1mo")

            change = (
                hist["Close"].iloc[-1] - hist["Close"].iloc[0]
            ) / hist["Close"].iloc[0] * 100

            changes.append(change)

        except:
            pass

    if len(changes) == 0:
        return None

    return round(sum(changes)/len(changes),2)

prices=[]
ma200_list=[]
distance_list=[]
ma_signal_list=[]
peer_perf=[]

for ticker in df["Ticker"]:

    price,ma200 = get_stock_data(ticker)

    distance=(price-ma200)/ma200*100

    if distance>15:
        signal="OVEREXTENDED"
    elif distance>8:
        signal="WAIT"
    elif distance>2:
        signal="WATCH"
    elif distance>-3:
        signal="BUY"
    else:
        signal="STRONG BUY"

    prices.append(round(price,2))
    ma200_list.append(round(ma200,2))
    distance_list.append(round(distance,2))
    ma_signal_list.append(signal)

    peer_perf.append(get_peer_perf(ticker))

df["Current Price"]=prices
df["MA200"]=ma200_list
df["MA200 Distance %"]=distance_list
df["MA Signal"]=ma_signal_list
df["Peer 1M %"]=peer_perf

# -------------------------
# BUY DECISION
# -------------------------

def decision(row):

    if row["Current Price"]<=row["Buy Max"] and row["Current Price"]>=row["Buy Min"]:
        return "BUY ZONE"

    elif row["Current Price"]<row["Buy Min"]:
        return "STRONG BUY"

    else:
        return "WAIT"

df["Decision"]=df.apply(decision,axis=1)

# -------------------------
# LOAD TRANSACTIONS
# -------------------------

response=supabase.table("transactions").select("*").execute()

transactions=pd.DataFrame(response.data)

if not transactions.empty:

    capital_summary=transactions.groupby("ticker")["capital_used"].sum().reset_index()

else:

    capital_summary=pd.DataFrame(columns=["ticker","capital_used"])

df=df.merge(capital_summary,how="left",left_on="Stock",right_on="ticker")

df["capital_used"]=df["capital_used"].fillna(0)

df["Remaining Capital"]=df["Target Capital"]-df["capital_used"]

# -------------------------
# LAST BUY PRICE
# -------------------------

if not transactions.empty:

    last_buy=transactions.sort_values("created_at").groupby("ticker").last().reset_index()

    last_buy=last_buy[["ticker","price"]]

    last_buy.columns=["Stock","Last Buy Price"]

    df=df.merge(last_buy,how="left",on="Stock")

else:

    df["Last Buy Price"]=None

df["Vs Last Buy %"]=(df["Current Price"]-df["Last Buy Price"])/df["Last Buy Price"]*100

# -------------------------
# MARKET SIGNAL TABLE
# -------------------------

st.subheader("Market Signals")

st.dataframe(df[
[
"Stock",
"Current Price",
"Last Buy Price",
"Vs Last Buy %",
"Buy Min",
"Buy Max",
"MA200",
"MA200 Distance %",
"Peer 1M %",
"MA Signal",
"Decision"
]
])

# -------------------------
# PORTFOLIO DEPLOYMENT
# -------------------------

st.subheader("Portfolio Deployment")

progress_df=df[
["Stock","Target Capital","capital_used","Remaining Capital"]
]

progress_df.columns=["Stock","Target","Invested","Remaining"]

st.dataframe(progress_df)

total_target=df["Target Capital"].sum()
total_used=df["capital_used"].sum()

progress=total_used/total_target if total_target>0 else 0

st.progress(progress)

# -------------------------
# EXECUTE BUY
# -------------------------

st.subheader("Execute Buy")

ticker_choice=st.selectbox("Stock",df["Stock"])

shares=st.number_input("Shares",min_value=1)

price=st.number_input("Execution Price",min_value=1.0)

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
# PORTFOLIO PERFORMANCE
# -------------------------

st.subheader("Portfolio Performance")

if not transactions.empty:

    summary=transactions.groupby("ticker").agg(

        shares=("shares","sum"),
        capital=("capital_used","sum")

    ).reset_index()

    summary["avg_price"]=summary["capital"]/summary["shares"]

    price_map=dict(zip(df["Stock"],df["Current Price"]))

    summary["current_price"]=summary["ticker"].map(price_map)

    summary["market_value"]=summary["shares"]*summary["current_price"]

    summary["profit"]=summary["market_value"]-summary["capital"]

    summary["return_%"]=summary["profit"]/summary["capital"]*100

    st.dataframe(summary)

else:

    st.write("No holdings yet")

# -------------------------
# AI BUY ENGINE
# -------------------------

st.subheader("AI Buy Signal")

def ai_buy_signal(row):

    if row["Decision"]=="BUY ZONE" and row["MA Signal"] in ["BUY","STRONG BUY"]:

        return "BUY"

    if row["Peer 1M %"]!=None and row["Peer 1M %"]>0 and row["Decision"]=="WAIT":

        return "WATCH"

    return "WAIT"

df["AI Signal"]=df.apply(ai_buy_signal,axis=1)

st.dataframe(df[["Stock","Current Price","AI Signal"]])

# -------------------------
# FUNDAMENTALS
# -------------------------

@st.cache_data(ttl=3600)
def get_fundamentals(ticker):

    stock=yf.Ticker(ticker)
    info=stock.info

    return {

        "Ticker":ticker,
        "PE":info.get("trailingPE"),
        "PB":info.get("priceToBook"),
        "Dividend Yield":info.get("dividendYield"),
        "ROE":info.get("returnOnEquity")

    }

fundamentals=[]

for t in portfolio["Ticker"]:

    fundamentals.append(get_fundamentals(t))

fundamental_df=pd.DataFrame(fundamentals)

st.subheader("Fundamental Snapshot")

st.dataframe(fundamental_df)

# -------------------------
# NEWS
# -------------------------

@st.cache_data(ttl=1800)
def get_news(ticker):

    stock=yf.Ticker(ticker)

    try:

        news=stock.news

        return [n.get("title","") for n in news[:3]]

    except:

        return []

news_data={}

for t in portfolio["Ticker"]:

    news_data[t]=get_news(t)

# -------------------------
# AI REPORT
# -------------------------

st.subheader("AI Portfolio Analyst")

def generate_ai_report():

    news_text=""

    for t,h in news_data.items():

        news_text+=f"\n{t}\n"

        for i in h:

            news_text+=f"- {i}\n"

    prompt=f"""

Analisis portofolio saham Indonesia berikut.

Technical:
{df[['Stock','Current Price','MA200 Distance %','Peer 1M %']].to_string(index=False)}

Fundamental:
{fundamental_df.to_string(index=False)}

News:
{news_text}

Beri analisis:
1 prospek tiap saham
2 apakah underperform sector
3 risiko
4 rekomendasi

Jawab bahasa Indonesia.
"""

    try:

        completion=groq_client.chat.completions.create(

            model="llama-3.3-70b-versatile",

            messages=[{"role":"user","content":prompt}],

            temperature=0.3,
            max_tokens=1000
        )

        return completion.choices[0].message.content

    except Exception as e:

        return str(e)

if st.button("Generate AI Analysis"):

    with st.spinner("Analyzing market..."):

        st.markdown(generate_ai_report())
