import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from supabase import create_client
import datetime
from groq import Groq
import traceback

# --- INITIAL CONFIG ---
st.set_page_config(page_title="Investment Card Monitor v2.2", layout="wide")

def format_rupiah(value):
    if pd.isna(value) or value == 0:
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")

# --- AUTHENTICATION ---
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

# --- API CLIENTS ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)
groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# --- DATA FETCHING FUNCTIONS ---
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
    except:
        return {"Ticker": ticker, "Sector": "Error"}

@st.cache_data(ttl=300)
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
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
            if not hist.empty:
                c = hist["Close"]
                perf.append(((c.iloc[-1] - c.iloc[0]) / c.iloc[0] * 100))
        except: continue
    return sum(perf)/len(perf) if perf else 0

# --- PORTFOLIO DEFINITION ---
portfolio = {
    "Ticker": ["BBRI.JK", "PTBA.JK", "TLKM.JK", "BSSR.JK"],
    "Stock": ["BBRI", "PTBA", "TLKM", "BSSR"],
    "Buy Min": [3400, 2200, 3500, 3600],
    "Buy Max": [3650, 2500, 3900, 4200],
    "Target Capital": [11880000, 3600000, 6080000, 5400000]
}
df = pd.DataFrame(portfolio)
peer_groups = {"BBRI.JK": ["BMRI.JK","BBCA.JK"], "PTBA.JK": ["ADRO.JK","ITMG.JK"], "TLKM.JK": ["EXCL.JK","ISAT.JK"], "BSSR.JK": ["ADRO.JK","ITMG.JK"]}

# --- MAIN APP UI ---
col1, col2 = st.columns([6,1])
with col1:
    st.title("Investment Card Monitor")
with col2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# Processing Market Data
prices, ma200_l, sig_l, peer_l = [], [], [], []
for t in df["Ticker"]:
    p, m, c = get_stock_data(t)
    dist = ((p - m) / m * 100) if m != 0 else 0.0
    pc = get_peer_performance(peer_groups.get(t,[]))
    s = "OVEREXTENDED" if dist > 15 else "WAIT" if dist > 8 else "WATCH" if dist > 2 else "BUY" if dist > -3 else "STRONG BUY"
    prices.append(p); ma200_l.append(m); sig_l.append(s); peer_l.append(pc)

df["Current Price"], df["MA200"], df["MA Signal"], df["Peer 1M %"] = prices, ma200_l, sig_l, peer_l
df["Decision"] = df.apply(lambda r: "BUY ZONE" if r["Current Price"] <= r["Buy Max"] and r["Current Price"] >= r["Buy Min"] else ("STRONG BUY" if r["Current Price"] < r["Buy Min"] else "WAIT"), axis=1)

# Transactions Sync
try:
    tx_data = supabase.table("transactions").select("*").execute().data
    tx = pd.DataFrame(tx_data)
    if not tx.empty:
        ap = tx.groupby("ticker").apply(lambda x:(x["shares"]*x["price"]).sum()/x["shares"].sum()).reset_index(name="Avg Price")
        df = df.merge(ap, how="left", left_on="Stock", right_on="ticker").fillna(0)
    else: df["Avg Price"] = 0
except: df["Avg Price"] = 0

df["Gain/Loss %"] = df.apply(lambda r: ((r["Current Price"] - r["Avg Price"]) / r["Avg Price"] * 100) if r["Avg Price"] != 0 else 0, axis=1)

# Display Metrics Table
st.subheader("Market Signals")
st.dataframe(df[["Stock","Current Price","Buy Min","Buy Max","MA Signal","Decision","Avg Price","Gain/Loss %"]])

# --- MONTE CARLO PATTERN EXTRACTION ENGINE ---
def run_monte_carlo(ticker_symbol, days=30, sims=2000, start_price=None, target_price=None):
    try:
        h = yf.download(ticker_symbol, period="1y", progress=False, multi_level_index=False)["Close"]
        if h.empty: return None
        rets = h.pct_change().dropna()
        v, d = rets.std(), rets.mean() - (0.5 * rets.std()**2)
        s_p = start_price if start_price else h.iloc[-1]
        
        growth = np.exp(d + v * np.random.normal(0, 1, (int(days), sims)))
        paths = np.zeros_like(growth); paths[0] = s_p
        for t in range(1, int(days)): paths[t] = paths[t-1] * growth[t]
        
        res = {"p50": np.percentile(paths[-1], 50), "paths": paths}
        if target_price:
            mask = np.any(paths >= target_price, axis=0) if target_price > s_p else np.any(paths <= target_price, axis=0)
            res["hit_prob"], res["hit_mask"] = (np.sum(mask)/sims)*100, mask
        return res
    except Exception as e:
        st.error(f"MC Error: {e}")
        return None

st.divider()
st.subheader("🔮 Black Swan & Pattern Recognition Engine")

c1, c2, c3 = st.columns(3)
with c1: sim_s = st.selectbox("Stock to Analyze", df["Stock"])
with c2: sim_d = st.number_input("Days to Simulate", min_value=1, value=30)
with c3: 
    curr_v = float(df[df["Stock"]==sim_s]["Current Price"].iloc[0])
    trig_v = st.number_input("Pattern Target Price", value=curr_v)

col_a, col_b = st.columns(2)
with col_a:
    sample_limit = st.slider("Visualization Sample Size", 1, 1000, 100)
with col_b:
    chosen_indices = st.multiselect("Isolate Specific Line Indices", options=list(range(sample_limit)), default=[0])

if st.button("🚀 Run Pattern Extraction"):
    t_sym = df.loc[df["Stock"] == sim_s, "Ticker"].iloc[0]
    with st.spinner("Extracting Black Swan and Normal patterns..."):
        res = run_monte_carlo(t_sym, sim_d, target_price=trig_v)
        
        if res:
            paths = res['paths']
            last_prices = paths[-1]
            
            # Extract Key Patterns
            idx_max = np.argmax(last_prices)
            idx_min = np.argmin(last_prices)
            idx_med = np.abs(last_prices - res['p50']).argmin()
            
            # Combine Auto with User selection
            final_selection = list(set([idx_max, idx_min, idx_med] + chosen_indices))
            pattern_paths = paths[:, final_selection]
            
            labels = []
            for idx in final_selection:
                if idx == idx_max: labels.append(f"Line {idx} (MAX/MOON)")
                elif idx == idx_min: labels.append(f"Line {idx} (MIN/CRASH)")
                elif idx == idx_med: labels.append(f"Line {idx} (MEDIAN)")
                else: labels.append(f"Line {idx} (USER SELECTION)")

            m1, m2, m3 = st.columns(3)
            m1.metric("Prob. to Hit Target", f"{res['hit_prob']:.1f}%")
            m2.metric("P50 (Most Likely)", format_rupiah(res["p50"]))
            m3.metric("Sample Hits", f"{np.sum(res['hit_mask'][:sample_limit])} / {sample_limit}")

            tab1, tab2 = st.tabs(["🎯 Pattern Analysis (Black Swans vs Normal)", "📊 Full Sample Cloud"])
            
            with tab1:
                st.write(f"Comparing the 'Black Swan' extremes against the 'Median' path for {sim_s}")
                st.line_chart(pd.DataFrame(pattern_paths, columns=labels))
                if res['hit_prob'] < 5:
                    st.warning("Pattern Insight: Statistically, your target is an outlier (Black Swan territory).")
                else:
                    st.info("Pattern Insight: Target is within normal historical volatility range.")

            with tab2:
                st.line_chart(pd.DataFrame(paths[:, :sample_limit]))

# --- FUNDAMENTALS & AI ---
st.divider()
st.subheader("Fundamental Snapshot")
f_df = pd.DataFrame([get_fundamentals(t) for t in portfolio["Ticker"]])
st.dataframe(f_df)

st.subheader("AI Strategic Brief")
if st.button("Generate AI Portfolio Analysis"):
    with st.spinner("Executing Strategic Analysis..."):
        summary = ""
        for _, r in df.iterrows():
            mc = run_monte_carlo(r["Ticker"], target_price=r["Buy Max"])
            if mc: summary += f"{r['Stock']}: Hit Prob {mc['hit_prob']:.1f}%, P50 {mc['p50']}\n"
        
        prompt = f"""
        Role: Senior Quantitative Investment Analyst.
        Evaluate: BBRI, PTBA, TLKM, BSSR.
        Data: {summary}
        Current Status: {df.to_string()}
        
        Provide 4-point analysis per stock:
        1. Range & P50: Statistical expected range.
        2. Hit Probability: Odds of reaching Buy Max.
        3. 1-Month Outlook: Technical & Sentiment.
        4. Portfolio Status: Risky, Noise, or Performing Well based on Avg Price.
        """
        try:
            resp = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user","content":prompt}])
            st.markdown(resp.choices[0].message.content)
        except: st.error("AI Analysis failed to generate.")
