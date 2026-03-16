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

for ticker in df["Ticker"]:

    price, ma200, change = get_stock_data(ticker)

    distance = (price - ma200) / ma200 * 100

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

df["Current Price"]=prices
df["MA200"]=ma200_list
df["MA200 Distance %"]=distance_list
df["MA Signal"]=ma_signal_list
df["Peer 1M %"]=peer_perf
df["Stock 1M %"]=stock_perf

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

def interpret(row):

    m=row["Decision"]
    a=row["AI Buy Signal"]

    if m=="BUY ZONE" and a=="BUY":
        return "Ideal entry. Price inside buy range and momentum healthy."

    if m=="WAIT" and a=="WATCH":
        return "Sector momentum positive but price above buy zone."

    if m=="STRONG BUY" and a=="WAIT":
        return "Cheap but sector weak. Risk of falling knife."

    if m=="BUY ZONE" and a=="WAIT":
        return "Buy zone reached but momentum slightly overextended."

    return "Neutral condition."

df["AI Interpretation"]=df.apply(interpret,axis=1)

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
# MARKET SIGNAL TABLE
# -------------------------

st.subheader("Market Signals")

market_df = df.copy()

market_df["Current Price"] = market_df["Current Price"].apply(format_rupiah)
market_df["Buy Min"] = market_df["Buy Min"].apply(format_rupiah)
market_df["Buy Max"] = market_df["Buy Max"].apply(format_rupiah)
market_df["MA200"] = market_df["MA200"].apply(format_rupiah)

st.dataframe(market_df[[
"Stock",
"Current Price",
"Buy Min",
"Buy Max",
"MA200",
"MA200 Distance %",
"MA Signal",
"Decision",
"AI Buy Signal",
"AI Interpretation"
]])

# -------------------------
# PORTFOLIO PERFORMANCE
# -------------------------

st.subheader("Portfolio Performance")

perf_df = df.copy()

perf_df["Avg Price"] = perf_df["Avg Price"].apply(format_rupiah)
perf_df["Current Price"] = perf_df["Current Price"].apply(format_rupiah)

st.dataframe(perf_df[[
"Stock",
"Avg Price",
"Current Price",
"Gain/Loss %"
]])

# -------------------------
# PORTFOLIO DEPLOYMENT
# -------------------------

st.subheader("Portfolio Deployment")

progress_df=df[[
"Stock",
"Target Capital",
"capital_used",
"Remaining Capital"
]].copy()

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
    "ticker",
    "shares",
    "price",
    "capital_used",
    "created_at"
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
Kamu adalah analis saham Indonesia.

Gunakan data berikut untuk menganalisis portofolio.

DATA FUNDAMENTAL:
{fundamental_df.to_string(index=False)}

DATA MARKET SIGNALS:
{df.to_string(index=False)}

Penjelasan kolom penting:
- Peer 1M % = rata-rata performa saham peer dalam sektor yang sama selama 1 bulan
- Stock 1M % = performa saham tersebut selama 1 bulan
- Jika Stock 1M % lebih rendah dari Peer 1M %, berarti saham underperform sektor
- Jika Stock 1M % lebih tinggi dari Peer 1M %, berarti saham outperform sektor

Tugas kamu:

1. Analisis setiap saham satu per satu
2. Bandingkan performa saham dengan peer sektor
3. Jelaskan apakah pergerakan saham:
   - mengikuti sektor
   - atau bergerak sendiri
4. Analisis valuasi fundamental (PE, PB, ROE, Dividend Yield)
5. Berikan outlook 1 bulan
6. Sebutkan risiko utama
7. Berikan kesimpulan portofolio secara keseluruhan

Gunakan bahasa Indonesia profesional namun mudah dipahami investor retail.

Format jawaban:

SAHAM: BBRI
- Performa vs peer:
- Analisis fundamental:
- Sentimen sektor:
- Outlook 1 bulan:
- Risiko:

Ulangi untuk semua saham.
"""

    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3
    )

    return completion.choices[0].message.content

    return completion.choices[0].message.content

st.subheader("AI Portfolio Analyst")

if st.button("Generate AI Analysis"):

    with st.spinner("Analyzing market..."):

        report=generate_ai_report()

        st.markdown(report)
