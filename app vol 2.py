import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from supabase import create_client
import datetime
from groq import Groq
import traceback

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
# AUDIT & DATA FUNCTIONS
# -------------------------

@st.cache_data(ttl=3600)
def get_fundamentals(ticker):
    try:
        ti = yf.Ticker(ticker).info
        return {
            "Ticker": ticker, 
            "Sector": ti.get("sector", "Unknown"), 
            "PE": ti.get("trailingPE"), 
            "PB": ti.get("priceToBook"), 
            "ROE": ti.get("returnOnEquity"), 
            "Yield": ti.get("dividendYield")
        }
    except Exception as e:
        return {"Ticker": ticker, "Sector": "Error Fetching", "Error_Detail": str(e)}

@st.cache_data(ttl=300)
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        if hist.empty:
            return 0.0, 0.0, 0.0
        price = hist["Close"].iloc[-1]
        ma200 = hist["Close"].rolling(200).mean().iloc[-1] if len(hist) >= 200 else price
        month_change = ((hist["Close"].iloc[-1] - hist["Close"].iloc[-22]) / hist["Close"].iloc[-22] * 100) if len(hist) >= 22 else 0.0
        return price, ma200, month_change
    except Exception as e:
        return 0.0, 0.0, 0.0

def get_peer_performance(peers):
    perf = []
    for p in peers:
        try:
            hist = yf.Ticker(p).history(period="1mo")
            if not hist.empty:
                close_prices = hist["Close"]
                change = ((close_prices.iloc[-1] - close_prices.iloc[0]) / close_prices.iloc[0] * 100)
                perf.append(change)
        except:
            continue
    return sum(perf)/len(perf) if perf else 0

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

# Process Market Signals
prices, ma200_list, distance_list, ma_signal_list, peer_perf, stock_perf = [], [], [], [], [], []
for ticker in df["Ticker"]:
    p, m, c = get_stock_data(ticker)
    dist = ((p - m) / m * 100) if m != 0 else 0.0
    peer_c = get_peer_performance(peer_groups.get(ticker,[]))
    sig = "OVEREXTENDED" if dist > 15 else "WAIT" if dist > 8 else "WATCH" if dist > 2 else "BUY" if dist > -3 else "STRONG BUY"
    prices.append(p); ma200_list.append(m); distance_list.append(dist); ma_signal_list.append(sig); peer_perf.append(peer_c); stock_perf.append(c)

df["Current Price"], df["MA200"], df["MA200 Distance %"], df["MA Signal"], df["Peer 1M %"], df["Stock 1M %"] = prices, ma200_list, distance_list, ma_signal_list, peer_perf, stock_perf

# Logic: Decision & Signal
def decision(row):
    if row["Current Price"] <= row["Buy Max"] and row["Current Price"] >= row["Buy Min"]: return "BUY ZONE"
    return "STRONG BUY" if row["Current Price"] < row["Buy Min"] else "WAIT"
df["Decision"] = df.apply(decision, axis=1)

def ai_signal(row):
    if row["Decision"]=="BUY ZONE" and row["MA Signal"] in ["BUY","STRONG BUY"]: return "BUY"
    if row["Decision"]=="WAIT" and row["Peer 1M %"]>0: return "WATCH"
    return "WAIT"
df["AI Buy Signal"] = df.apply(ai_signal, axis=1)

# Transactions Logic
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
st.dataframe(m_disp[["Stock","Current Price","Buy Min","Buy Max","MA Signal","Decision","AI Buy Signal"]])

st.subheader("Portfolio Performance")
p_disp = df.copy()
for c in ["Avg Price", "Current Price"]: p_disp[c] = p_disp[c].apply(format_rupiah)
st.dataframe(p_disp[["Stock","Avg Price","Current Price","Gain/Loss %"]])

# -------------------------
# 🔮 MONTE CARLO ENGINE (Target Aware)
# -------------------------

def run_monte_carlo(ticker_symbol, days=30, sims=2000, start_price=None, target_price=None):
    try:
        h = yf.download(ticker_symbol, period="1y", progress=False, multi_level_index=False)["Close"]
        if h.empty or len(h) < 30: return None
        
        rets = h.pct_change().dropna()
        v = rets.std()
        d = rets.mean() - (0.5 * v**2)
        s_price = start_price if start_price else h.iloc[-1]
        
        growth = np.exp(d + v * np.random.normal(0, 1, (int(days), sims)))
        paths = np.zeros_like(growth)
        paths[0] = s_price
        for t in range(1, int(days)):
            paths[t] = paths[t-1] * growth[t]
            
        # Analysis logic
        final_prices = paths[-1]
        results = {
            "p90": np.percentile(final_prices, 10), 
            "p50": np.percentile(final_prices, 50), 
            "p10": np.percentile(final_prices, 90), 
            "paths": paths
        }

        # Filtering logic for target
        if target_price:
            # Check if target is above or below current price to determine "touch" logic
            if target_price > s_price:
                hit_mask = np.any(paths >= target_price, axis=0)
            else:
                hit_mask = np.any(paths <= target_price, axis=0)
            
            results["hit_paths"] = paths[:, hit_mask]
            results["miss_paths"] = paths[:, ~hit_mask]
            results["hit_count"] = np.sum(hit_mask)
            results["hit_prob"] = (np.sum(hit_mask) / sims) * 100
            
        return results
    except Exception as e:
        st.error(f"Audit Detail for {ticker_symbol}: {str(e)}")
        return None

# Section: Probability & Scenario Engine
st.divider()
st.subheader("🔮 Probability & Scenario Engine")
sim_col1, sim_col2, sim_col3 = st.columns(3)
with sim_col1: sim_s = st.selectbox("Stock for Analysis", df["Stock"])
with sim_col2: sim_d = st.number_input("Days ahead", min_value=1, value=30)
with sim_col3: 
    row_match = df[df["Stock"] == sim_s]
    curr_v = float(row_match["Current Price"].iloc[0]) if not row_match.empty else 0.0
    trig_v = st.number_input("Price Target to Touch", value=curr_v)

if st.button("🚀 Run Target Analysis"):
    t_sym = df.loc[df["Stock"] == sim_s, "Ticker"].iloc[0]
    with st.spinner(f"Analyzing simulations for {sim_s}..."):
        res = run_monte_carlo(t_sym, sim_d, target_price=trig_v)
        
        if res:
            c1, c2, c3 = st.columns(3)
            c1.metric("Most Possible (50%)", format_rupiah(res["p50"]))
            c2.metric("Probability to Hit Target", f"{res['hit_prob']:.1f}%")
            c3.metric("Simulations hitting Target", f"{res['hit_count']} paths")

            tab1, tab2 = st.tabs(["🎯 Paths hitting Target", "📉 All Simulation Paths"])
            
            with tab1:
                if res['hit_count'] > 0:
                    st.write(f"Showing {min(50, res['hit_count'])} simulations that touched {format_rupiah(trig_v)}")
                    st.line_chart(pd.DataFrame(res['hit_paths'][:, :50]))
                else:
                    st.warning("No simulations touched this price target in the given timeframe.")
            
            with tab2:
                st.line_chart(pd.DataFrame(res['paths'][:, :50]))

# -------------------------
# FUNDAMENTALS & EXECUTE
# -------------------------

st.subheader("Fundamental Snapshot")
f_df = pd.DataFrame([get_fundamentals(t) for t in portfolio["Ticker"]])
st.dataframe(f_df)

# -------------------------
# AI REPORT
# -------------------------

st.subheader("AI Portfolio Analyst")
if st.button("Generate AI Analysis"):
    with st.spinner("Generating Strategic Brief..."):
        prob_summary = ""
        for _, row in df.iterrows():
            # AI runs hit analysis against 'Buy Max' as the default target
            mc = run_monte_carlo(row["Ticker"], days=30, sims=1000, target_price=row["Buy Max"])
            
            if mc:
                prob_summary += f"""
                SAHAM: {row['Stock']}
                - Current: {format_rupiah(row['Current Price'])}
                - Target (Buy Max): {format_rupiah(row['Buy Max'])}
                - Probabilitas Hit Target: {mc['hit_prob']:.1f}%
                - Range (90%-10%): {format_rupiah(mc['p90'])} - {format_rupiah(mc['p10'])}
                - Most Possible: {format_rupiah(mc['p50'])}
                ---
                """

        prompt = f"""
        Evaluasi strategis untuk BBRI, PTBA, TLKM, BSSR.
        
        DATA SIMULASI:
        {prob_summary}
        {df.to_string()}
        
        FORMAT ANALISIS (4 Poin):
        1. Rentang Harga & Probabilitas: Sajikan rentang dan harga 'Most Possible'.
        2. Skenario Pergeseran (Shift/Hit): Sebutkan probabilitas harga menyentuh 'Buy Max' (Target) dalam 30 hari.
        3. Prospek 1 Bulan: Insight teknikal dan sentimen.
        4. Posisi Investasi: Analisis apakah Risky, Noise, atau Performing Well berdasarkan Avg Price.
        """
        
        try:
            res = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", 
                messages=[{"role": "user", "content": prompt}], 
                temperature=0.1
            )
            st.markdown(res.choices[0].message.content)
        except Exception as e:
            st.error(f"AI Error: {e}")
