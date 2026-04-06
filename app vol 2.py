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
        # Audit Script: Print error to console/log
        print(f"Audit Error [get_stock_data] for {ticker}: {str(e)}")
        return 0.0, 0.0, 0.0

def get_peer_performance(peers):
    perf = []
    for p in peers:
        try:
            hist = yf.Ticker(p).history(period="1mo")
            if not hist.empty:
                # Handle potential multi-index from recent yfinance versions
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

def interpret(row):
    m, a = row["Decision"], row["AI Buy Signal"]
    if m=="BUY ZONE" and a=="BUY": return "Ideal entry. Price inside buy range and momentum healthy."
    if m=="WAIT" and a=="WATCH": return "Sector momentum positive but price above buy zone."
    if m=="STRONG BUY" and a=="WAIT": return "Cheap but sector weak. Risk of falling knife."
    if m=="BUY ZONE" and a=="WAIT": return "Buy zone reached but momentum slightly overextended."
    return "Neutral condition."
df["AI Interpretation"] = df.apply(interpret, axis=1)

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
# 🔮 MONTE CARLO ENGINE (Core Function)
# -------------------------

def run_monte_carlo(ticker_symbol, days=30, sims=2000, start_price=None):
    try:
        # Audit: Track fetching start
        h = yf.download(ticker_symbol, period="1y", progress=False, multi_level_index=False)["Close"]
        
        if h.empty or len(h) < 30:
            return None
        
        rets = h.pct_change().dropna()
        v = rets.std()
        d = rets.mean() - (0.5 * v**2)
        s_price = start_price if start_price else h.iloc[-1]
        
        growth = np.exp(d + v * np.random.normal(0, 1, (int(days), sims)))
        paths = np.zeros_like(growth)
        paths[0] = s_price
        for t in range(1, int(days)):
            paths[t] = paths[t-1] * growth[t]
            
        return {
            "p90": np.percentile(paths[-1], 10), 
            "p50": np.percentile(paths[-1], 50), 
            "p10": np.percentile(paths[-1], 90), 
            "paths": paths
        }
    except Exception as e:
        # Audit Script: Detailed error reporting for Monte Carlo
        st.error(f"Audit Detail for {ticker_symbol}: {str(e)}")
        print(traceback.format_exc())
        return None

# Section 1: Manual Simulation (Visible playground)
st.divider()
st.subheader("🔮 Probability & Scenario Engine")
sim_col1, sim_col2, sim_col3 = st.columns(3)
with sim_col1: sim_s = st.selectbox("Stock for Analysis", df["Stock"])
with sim_col2: sim_d = st.number_input("Days ahead", min_value=1, value=30)
with sim_col3: 
    row_match = df[df["Stock"] == sim_s]
    curr_v = float(row_match["Current Price"].iloc[0]) if not row_match.empty else 0.0
    trig_v = st.number_input("What if price hits this tomorrow?", value=curr_v)

if st.button("🚀 Run Probabilistic Discovery"):
    t_sym = df.loc[df["Stock"] == sim_s, "Ticker"].iloc[0]
    with st.spinner(f"Auditing Data & Running Simulation for {sim_s}..."):
        res_base = run_monte_carlo(t_sym, sim_d)
        res_shift = run_monte_carlo(t_sym, sim_d, start_price=trig_v)
        
        if res_base:
            c1, c2, c3 = st.columns(3)
            c1.metric("Most Possible (50%)", format_rupiah(res_base["p50"]))
            c2.metric("Conservative (90%)", format_rupiah(res_base["p90"]))
            c3.metric("Optimistic (10%)", format_rupiah(res_base["p10"]))
            st.info(f"**Scenario Logic:** Jika harga besok menyentuh {format_rupiah(trig_v)}, maka target 'Most Possible' 30 hari bergeser ke **{format_rupiah(res_shift['p50'])}**.")
            st.line_chart(pd.DataFrame(res_base["paths"][:, :50]))

# -------------------------
# FUNDAMENTALS & EXECUTE
# -------------------------

st.subheader("Fundamental Snapshot")
f_df = pd.DataFrame([get_fundamentals(t) for t in portfolio["Ticker"]])
st.dataframe(f_df)

st.subheader("Execute Buy")
t_choice = st.selectbox("Stock", df["Stock"], key="b_t")
shs = st.number_input("Shares", min_value=1, step=1)
prc = st.number_input("Price", min_value=1.0)
if st.button("Record Trade"):
    supabase.table("transactions").insert({"ticker":t_choice, "shares":shs, "price":prc, "capital_used":shs*prc}).execute()
    st.success("Trade Recorded")

# -------------------------
# AI REPORT (PORTFOLIO-WIDE STRATEGIC BRIEF)
# -------------------------

st.subheader("AI Portfolio Analyst")
if st.button("Generate AI Analysis"):
    with st.spinner("Executing background swarm and generating 4-point analysis..."):
        prob_summary = ""
        for _, row in df.iterrows():
            mc = run_monte_carlo(row["Ticker"], days=30, sims=1000)
            mc_shift = run_monte_carlo(row["Ticker"], days=30, sims=1000, start_price=row["Buy Max"])
            
            if mc and mc_shift:
                prob_summary += f"""
                SAHAM: {row['Stock']}
                - Harga Sekarang: {format_rupiah(row['Current Price'])}
                - Avg Price User: {format_rupiah(row['Avg Price'])}
                - Target Beli (Buy Max): {format_rupiah(row['Buy Max'])}
                - Range (90%-10%): {format_rupiah(mc['p90'])} - {format_rupiah(mc['p10'])}
                - Most Possible: {format_rupiah(mc['p50'])}
                - Shift Logic (Jika kena Buy Max): {format_rupiah(mc_shift['p50'])}
                ---
                """

        prompt = f"""
        Tugas: Senior Quant Analyst. Berikan evaluasi strategis untuk BBRI, PTBA, TLKM, BSSR secara berurutan.
        
        DATA SIMULASI:
        {prob_summary}

        DATA MARKET & FUNDAMENTAL:
        {f_df.to_string()}
        {df.to_string()}
        
        WAJIB ANALISIS SETIAP SAHAM DENGAN FORMAT 4 POIN:
        1. Rentang Harga & Probabilitas: Sajikan rentang harga (Bottom 90% ke Top 10%). Tegaskan harga mana yang 'Most Possible'.
        2. Skenario Pergeseran (Shift): Jelaskan bagaimana rentang harga berubah jika harga menyentuh 'Buy Max' user menggunakan data 'Shift Logic'.
        3. Prospek 1 Bulan: Berikan insight prospek 1 bulan kedepan berdasarkan teknikal (MA200) dan sentimen pasar.
        4. Posisi Investasi: Analisis apakah posisi saat ini (berdasarkan Avg Price) termasuk Risky, Noise, atau Performing Well. Berikan alasan lugas.
        
        Note: BSSR adalah Coal Mining. Dilarang menebak rumus. Gunakan data simulasi yang diberikan.
        """
        
        try:
            res = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", 
                messages=[{"role": "system", "content": "Anda adalah analis investasi data-driven yang hanya berbicara berdasarkan data statistik yang disediakan."},
                          {"role": "user", "content": prompt}], 
                temperature=0.1
            )
            st.markdown(res.choices[0].message.content)
        except Exception as e:
            st.error(f"AI Error: {e}")
