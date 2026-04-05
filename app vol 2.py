import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from supabase import create_client
import datetime
from groq import Groq

st.set_page_config(page_title="Investment Card Monitor", layout="wide")

# -------------------------
# FORMAT RUPIAH
# -------------------------

def format_rupiah(value):
    if pd.isna(value) or value == 0:
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
# SUPABASE & GROQ SETUP
# -------------------------

url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)
groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# -------------------------
# REFRESH LOGIC
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
# INVESTMENT PLAN & DATA
# -------------------------

portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK", "BSSR.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM", "BSSR"],
    "Buy Min": [3400, 2200, 3500, 3600],
    "Buy Max": [3650, 2500, 3900, 4200],
    "Target Capital": [11880000, 3600000, 6080000, 5400000]
}
df = pd.DataFrame(portfolio)

peer_groups = {
    "BBRI.JK": ["BMRI.JK","BBCA.JK"],
    "PTBA.JK": ["ADRO.JK","ITMG.JK"],
    "TLKM.JK": ["EXCL.JK","ISAT.JK"],
    "BSSR.JK": ["ADRO.JK","ITMG.JK"]
}

@st.cache_data(ttl=300)
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if hist.empty: return 0.0, 0.0, 0.0
        price = hist["Close"].iloc[-1]
        ma200 = hist["Close"].rolling(200).mean().iloc[-1] if len(hist) >= 200 else price
        month_change = ((hist["Close"].iloc[-1] - hist["Close"].iloc[-22]) / hist["Close"].iloc[-22] * 100) if len(hist) >= 22 else 0.0
        return price, ma200, month_change
    except: return 0.0, 0.0, 0.0

def get_peer_performance(peers):
    perf = []
    for p in peers:
        try:
            hist = yf.Ticker(p).history(period="1mo")
            if not hist.empty: perf.append(((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100))
        except: continue
    return sum(perf)/len(perf) if perf else 0

# Process Market Data
prices, ma200_list, distance_list, ma_signal_list, peer_perf, stock_perf = [], [], [], [], [], []
for ticker in df["Ticker"]:
    p, m, c = get_stock_data(ticker)
    dist = ((p - m) / m * 100) if m != 0 else 0.0
    peer_c = get_peer_performance(peer_groups.get(ticker,[]))
    
    sig = "OVEREXTENDED" if dist > 15 else "WAIT" if dist > 8 else "WATCH" if dist > 2 else "BUY" if dist > -3 else "STRONG BUY"
    prices.append(round(p,2)); ma200_list.append(round(m,2)); distance_list.append(round(dist,2))
    ma_signal_list.append(sig); peer_perf.append(round(peer_c,2)); stock_perf.append(round(c,2))

df["Current Price"], df["MA200"], df["MA200 Distance %"], df["MA Signal"], df["Peer 1M %"], df["Stock 1M %"] = prices, ma200_list, distance_list, ma_signal_list, peer_perf, stock_perf

# Logic Functions (Decision, AI Signal, Interpret)
def decision(row):
    if row["Current Price"] <= row["Buy Max"] and row["Current Price"] >= row["Buy Min"]: return "BUY ZONE"
    return "STRONG BUY" if row["Current Price"] < row["Buy Min"] else "WAIT"
df["Decision"] = df.apply(decision, axis=1)

def ai_signal(row):
    if row["Decision"]=="BUY ZONE" and row["MA Signal"] in ["BUY","STRONG BUY"]: return "BUY"
    if row["Decision"]=="WAIT" and row["Peer 1M %"]>0: return "WATCH"
    return "WAIT"
df["AI Buy Signal"] = df.apply(ai_signal, axis=1)

def interpret(row):
    m, a = row["Decision"], row["AI Buy Signal"]
    if m=="BUY ZONE" and a=="BUY": return "Ideal entry. Price inside buy range and momentum healthy."
    if m=="WAIT" and a=="WATCH": return "Sector momentum positive but price above buy zone."
    if m=="STRONG BUY" and a=="WAIT": return "Cheap but sector weak. Risk of falling knife."
    if m=="BUY ZONE" and a=="WAIT": return "Buy zone reached but momentum slightly overextended."
    return "Neutral condition."
df["AI Interpretation"] = df.apply(interpret, axis=1)

# Transactions
try:
    res = supabase.table("transactions").select("*").execute()
    transactions = pd.DataFrame(res.data)
except: transactions = pd.DataFrame()

if not transactions.empty:
    avg_p = transactions.groupby("ticker").apply(lambda x:(x["shares"]*x["price"]).sum()/x["shares"].sum()).reset_index(name="Avg Price")
    df = df.merge(avg_p, how="left", left_on="Stock", right_on="ticker")
    summ = transactions.groupby("ticker")["capital_used"].sum().reset_index()
    df = df.merge(summ, how="left", left_on="Stock", right_on="ticker")
else:
    df["Avg Price"], df["capital_used"] = 0, 0

df["capital_used"] = df["capital_used"].fillna(0)
df["Avg Price"] = df["Avg Price"].fillna(0)
df["Remaining Capital"] = df["Target Capital"] - df["capital_used"]
df["Gain/Loss %"] = df.apply(lambda row: ((row["Current Price"] - row["Avg Price"]) / row["Avg Price"] * 100) if row["Avg Price"] != 0 else 0, axis=1).fillna(0)

# -------------------------
# DISPLAY TABLES
# -------------------------

st.subheader("Market Signals")
m_disp = df.copy()
for c in ["Current Price", "Buy Min", "Buy Max", "MA200"]: m_disp[c] = m_disp[c].apply(format_rupiah)
st.dataframe(m_disp[["Stock","Current Price","Buy Min","Buy Max","MA200","MA200 Distance %","MA Signal","Decision","AI Buy Signal","AI Interpretation"]])

st.subheader("Portfolio Performance")
p_disp = df.copy()
for c in ["Avg Price", "Current Price"]: p_disp[c] = p_disp[c].apply(format_rupiah)
st.dataframe(p_disp[["Stock","Avg Price","Current Price","Gain/Loss %"]])

st.subheader("Portfolio Deployment")
total_t, total_u = df["Target Capital"].sum(), df["capital_used"].sum()
st.progress(total_u/total_t if total_t > 0 else 0)
st.write(f"Capital Used: {format_rupiah(total_u)} | Remaining: {format_rupiah(total_t-total_u)}")

# -------------------------
# 🔮 THE "MIROFISH" PROBABILITY ENGINE (v1.2)
# -------------------------

def run_monte_carlo(ticker_symbol, days=30, sims=2000, start_price=None):
    try:
        h = yf.Ticker(ticker_symbol).history(period="1y")["Close"]
        if len(h) < 30: return None
        rets = h.pct_change().dropna()
        v, d = rets.std(), rets.mean() - (0.5 * v**2)
        s_price = start_price if start_price else h.iloc[-1]
        growth = np.exp(d + v * np.random.normal(0, 1, (int(days), sims)))
        paths = np.zeros_like(growth); paths[0] = s_price
        for t in range(1, int(days)): paths[t] = paths[t-1] * growth[t]
        final = paths[-1]
        return {"p90": np.percentile(final, 10), "p50": np.percentile(final, 50), "p10": np.percentile(final, 90), "paths": paths}
    except: return None

st.divider()
st.subheader("🔮 Probability & Scenario Engine")
sim_col1, sim_col2, sim_col3 = st.columns(3)
with sim_col1: sim_s = st.selectbox("Stock for Analysis", df["Stock"])
with sim_col2: sim_d = st.number_input("Days ahead", min_value=1, value=30)
with sim_col3: 
    curr_v = float(df[df["Stock"] == sim_s]["Current Price"].iloc[0])
    trig_v = st.number_input("What if price hits this tomorrow?", value=curr_v)

if st.button("🚀 Run Probabilistic Discovery"):
    t_sym = df.loc[df["Stock"] == sim_s, "Ticker"].iloc[0]
    res_base = run_monte_carlo(t_sym, sim_d)
    res_shift = run_monte_carlo(t_sym, sim_d, start_price=trig_v)
    
    if res_base:
        c1, c2, c3 = st.columns(3)
        c1.metric("Most Possible (50%)", format_rupiah(res_base["p50"]))
        c2.metric("Conservative (90%)", format_rupiah(res_base["p90"]))
        c3.metric("Optimistic (10%)", format_rupiah(res_base["p10"]))
        st.info(f"**Scenario:** If price hits {format_rupiah(trig_v)}, the target shifts to **{format_rupiah(res_shift['p50'])}**.")
        st.line_chart(pd.DataFrame(res_base["paths"][:, :50]))

# -------------------------
# EXECUTE BUY / FUNDAMENTALS
# -------------------------

st.subheader("Execute Buy")
t_choice = st.selectbox("Stock", df["Stock"], key="b_t")
shs = st.number_input("Shares", min_value=1, step=1)
prc = st.number_input("Price", min_value=1.0)
if st.button("Record Trade"):
    supabase.table("transactions").insert({"ticker":t_choice, "shares":shs, "price":prc, "capital_used":shs*prc}).execute()
    st.success("Recorded")

@st.cache_data(ttl=3600)
def get_fundamentals(ticker):
    try:
        ti = yf.Ticker(ticker).info
        return {"Ticker": ticker, "Sector": ti.get("sector", "Unknown"), "PE": ti.get("trailingPE"), "PB": ti.get("priceToBook"), "ROE": ti.get("returnOnEquity"), "Yield": ti.get("dividendYield")}
    except: return {"Ticker":ticker, "Sector":"Unknown"}

f_df = pd.DataFrame([get_fundamentals(t) for t in portfolio["Ticker"]])
st.subheader("Fundamental Snapshot")
st.dataframe(f_df)

# -------------------------
# AI REPORT (Now with Probability Data!)
# -------------------------

st.subheader("AI Portfolio Analyst")
if st.button("Generate AI Analysis"):
    with st.spinner("Running background simulations for all stocks..."):
        # Run a quick simulation for every stock to feed the AI
        prob_summary = ""
        for _, row in df.iterrows():
            mc = run_monte_carlo(row["Ticker"], days=30, sims=1000)
            if mc:
                prob_summary += f"- {row['Stock']}: Current {format_rupiah(row['Current Price'])}, Most Likely {format_rupiah(mc['p50'])}, Bottom Range (90% prob) {format_rupiah(mc['p90'])}\n"

        prompt = f"""
        Analyst Task: Evaluate this portfolio with 'MiroFish' probabilistic logic.
        
        PROBABILISTIC OUTLOOK (30 Days):
        {prob_summary}

        FUNDAMENTALS:
        {f_df.to_string()}

        MARKET SIGNALS:
        {df.to_string()}
        
        Specific Rule: BSSR is COAL MINING (Energy).
        Analyze if the user's Buy Max (in Market Signals) is realistic compared to the 'Bottom Range' (90% prob). 
        If the Buy Max is much lower than the Bottom Range, warn the user they might never get their entry.
        """
        res = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user","content":prompt}], temperature=0.3)
        st.markdown(res.choices[0].message.content)
