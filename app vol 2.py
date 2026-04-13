import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from supabase import create_client
import datetime
from groq import Groq

# --- INITIAL CONFIG ---
st.set_page_config(page_title="Investment Card Monitor Version 1", layout="wide")

# -------------------------
# FORMATTING HELPERS
# -------------------------
def format_rupiah(value):
    if pd.isna(value) or value == 0:
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")

def format_percent(value):
    if pd.isna(value):
        return "-"
    return f"{value:.2f}".replace(".", ",") + "%"

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
# API CLIENTS
# -------------------------
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)
groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# -------------------------
# HEADER & REFRESH
# -------------------------
col1, col2 = st.columns([6,1])
with col1:
    st.title("Investment Card Monitor Version 1")
with col2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Last update: {datetime.datetime.now().strftime('%H:%M:%S')}")

# -------------------------
# PORTFOLIO & PEER GROUPS
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

# -------------------------
# DATA FETCHING FUNCTIONS
# -------------------------
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
    except Exception as e:
        st.error(f"Error fetching data for {ticker}: {e}")
        return 0.0, 0.0, 0.0

def get_peer_performance(peers):
    perf = []
    for p in peers:
        try:
            hist = yf.Ticker(p).history(period="1mo")
            if not hist.empty and len(hist) > 0:
                change = (hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100
                perf.append(change)
        except: continue
    return sum(perf)/len(perf) if perf else 0.0

# -------------------------
# MARKET DATA PROCESSING
# -------------------------
prices, ma200_list, distance_list, ma_signal_list, peer_perf, stock_perf = [], [], [], [], [], []

for ticker in df["Ticker"]:
    price, ma200, change = get_stock_data(ticker)
    distance = ((price - ma200) / ma200 * 100) if ma200 != 0 else 0.0
    peer_change = get_peer_performance(peer_groups.get(ticker,[]))

    if distance > 15: ma_signal = "OVEREXTENDED"
    elif distance > 8: ma_signal = "WAIT"
    elif distance > 2: ma_signal = "WATCH"
    elif distance > -3: ma_signal = "BUY"
    else: ma_signal = "STRONG BUY"

    prices.append(round(price,2))
    ma200_list.append(round(ma200,2))
    distance_list.append(round(distance,2))
    ma_signal_list.append(ma_signal)
    peer_perf.append(round(peer_change,2))
    stock_perf.append(round(change,2))

df["Current Price"] = prices
df["MA200"] = ma200_list
df["MA200 Distance %"] = distance_list
df["MA Signal"] = ma_signal_list
df["Peer 1M %"] = peer_perf
df["Stock 1M %"] = stock_perf

# Buy Decision
def decision(row):
    if row["Current Price"] <= row["Buy Max"] and row["Current Price"] >= row["Buy Min"]: return "BUY ZONE"
    elif row["Current Price"] < row["Buy Min"]: return "STRONG BUY"
    else: return "WAIT"
df["Decision"] = df.apply(decision, axis=1)

# AI Signal
def ai_signal(row):
    if row["Decision"]=="BUY ZONE" and row["MA Signal"] in ["BUY","STRONG BUY"]: return "BUY"
    if row["Decision"]=="WAIT" and row["Peer 1M %"]>0: return "WATCH"
    if row["MA Signal"]=="OVEREXTENDED": return "WAIT"
    return "WAIT"
df["AI Buy Signal"] = df.apply(ai_signal, axis=1)

# AI Interpretation
def interpret(row):
    m, a = row["Decision"], row["AI Buy Signal"]
    if m=="BUY ZONE" and a=="BUY": return "Ideal entry. Price inside buy range and momentum healthy."
    if m=="WAIT" and a=="WATCH": return "Sector momentum positive but price above buy zone."
    if m=="STRONG BUY" and a=="WAIT": return "Cheap but sector weak. Risk of falling knife."
    if m=="BUY ZONE" and a=="WAIT": return "Buy zone reached but momentum slightly overextended."
    return "Neutral condition."
df["AI Interpretation"] = df.apply(interpret, axis=1)

# -------------------------
# LOAD TRANSACTIONS
# -------------------------
try:
    response = supabase.table("transactions").select("*").execute()
    transactions = pd.DataFrame(response.data)
except:
    transactions = pd.DataFrame()

if not transactions.empty:
    avg_price = transactions.groupby("ticker").apply(lambda x:(x["shares"]*x["price"]).sum()/x["shares"].sum()).reset_index(name="Avg Price")
    df = df.merge(avg_price, how="left", left_on="Stock", right_on="ticker")
    summary = transactions.groupby("ticker")["capital_used"].sum().reset_index()
    df = df.merge(summary, how="left", left_on="Stock", right_on="ticker")
else:
    df["Avg Price"] = 0
    df["capital_used"] = 0

df["capital_used"] = df["capital_used"].fillna(0)
df["Avg Price"] = df["Avg Price"].fillna(0)
df["Remaining Capital"] = df["Target Capital"] - df["capital_used"]
df["Gain/Loss %"] = df.apply(lambda r: ((r["Current Price"] - r["Avg Price"]) / r["Avg Price"] * 100) if r["Avg Price"] != 0 else 0, axis=1).fillna(0)

# -------------------------
# MARKET SIGNAL TABLE
# -------------------------
st.subheader("Market Signals")
market_df = df.copy()
market_df["Current Price"] = market_df["Current Price"].apply(format_rupiah)
market_df["Buy Min"] = market_df["Buy Min"].apply(format_rupiah)
market_df["Buy Max"] = market_df["Buy Max"].apply(format_rupiah)
market_df["MA200"] = market_df["MA200"].apply(format_rupiah)
market_df["MA200 Distance %"] = market_df["MA200 Distance %"].apply(format_percent)

st.dataframe(market_df[["Stock", "Current Price", "Buy Min", "Buy Max", "MA200", "MA200 Distance %", "MA Signal", "Decision", "AI Buy Signal", "AI Interpretation"]])

# -------------------------
# PORTFOLIO TABLES
# -------------------------
col_p1, col_p2 = st.columns(2)

with col_p1:
    st.subheader("Portfolio Performance")
    perf_df = df.copy()
    perf_df["Avg Price"] = perf_df["Avg Price"].apply(format_rupiah)
    perf_df["Current Price"] = perf_df["Current Price"].apply(format_rupiah)
    perf_df["Gain/Loss %"] = perf_df["Gain/Loss %"].apply(format_percent)
    st.dataframe(perf_df[["Stock", "Avg Price", "Current Price", "Gain/Loss %"]])

with col_p2:
    st.subheader("Portfolio Deployment")
    progress_df = df[["Stock", "Target Capital", "capital_used", "Remaining Capital"]].copy()
    progress_df.columns = ["Stock", "Target", "Invested", "Remaining"]
    progress_df["Target"] = progress_df["Target"].apply(format_rupiah)
    progress_df["Invested"] = progress_df["Invested"].apply(format_rupiah)
    progress_df["Remaining"] = progress_df["Remaining"].apply(format_rupiah)
    st.dataframe(progress_df)

total_target = df["Target Capital"].sum()
total_used = df["capital_used"].sum()
progress = total_used/total_target if total_target>0 else 0

st.progress(progress)
st.write(f"Capital Used: **{format_rupiah(total_used)}** | Remaining Capital: **{format_rupiah(total_target-total_used)}**")

# -------------------------
# TRANSACTION EXECUTION & HISTORY
# -------------------------
st.divider()
col_tx1, col_tx2 = st.columns(2)

with col_tx1:
    st.subheader("Execute Buy")
    ticker_choice = st.selectbox("Stock", df["Stock"], key="exec_buy_stock")
    shares = st.number_input("Shares", min_value=1, step=1)
    price_exec = st.number_input("Execution Price", min_value=1.0, step=1.0)

    if st.button("Record Buy"):
        try:
            capital = shares * price_exec
            supabase.table("transactions").insert({
                "ticker": ticker_choice, "shares": shares, "price": price_exec, "capital_used": capital
            }).execute()
            st.success("Trade recorded successfully!")
        except Exception as e:
            st.error(f"Record error: {e}")

with col_tx2:
    st.subheader("Transaction History")
    if not transactions.empty:
        trans_df = transactions.copy()
        trans_df["capital_used"] = trans_df["capital_used"].apply(format_rupiah)
        trans_df["price"] = trans_df["price"].apply(format_rupiah)
        st.dataframe(trans_df[["ticker", "shares", "price", "capital_used", "created_at"]], height=200)
    else:
        st.write("No trades recorded yet.")

# -------------------------
# SIMULATION ENGINES
# -------------------------
st.divider()
st.subheader("🔮 Simulation & Pattern Recognition Engines")

tab_sim1, tab_sim2 = st.tabs(["📊 Daily Black Swan (Pattern Extraction)", "🛡️ Intraday Survival Swarm"])

# -- TAB 1: DAILY MONTE CARLO (V2) --
with tab_sim1:
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
            return None

    c1, c2, c3 = st.columns(3)
    with c1: sim_s = st.selectbox("Stock to Analyze", df["Stock"], key="sim_stock1")
    with c2: sim_d = st.number_input("Days to Simulate", min_value=1, value=30, key="sim_days1")
    with c3: 
        curr_v = float(df[df["Stock"]==sim_s]["Current Price"].iloc[0])
        trig_v = st.number_input("Pattern Target Price", value=curr_v, key="sim_target1")

    col_a, col_b = st.columns(2)
    with col_a: sample_limit = st.slider("Visualization Sample Size", 1, 1000, 100, key="sim_sample1")
    with col_b: chosen_indices = st.multiselect("Isolate Specific Line Indices", options=list(range(sample_limit)), default=[0])

    if st.button("🚀 Run Pattern Extraction"):
        t_sym = df.loc[df["Stock"] == sim_s, "Ticker"].iloc[0]
        with st.spinner("Extracting Black Swan and Normal patterns..."):
            res = run_monte_carlo(t_sym, sim_d, target_price=trig_v)
            if res:
                paths = res['paths']
                last_prices = paths[-1]
                
                idx_max = np.argmax(last_prices)
                idx_min = np.argmin(last_prices)
                idx_med = np.abs(last_prices - res['p50']).argmin()
                
                final_selection = list(set([idx_max, idx_min, idx_med] + chosen_indices))
                pattern_paths = paths[:, final_selection]
                
                labels = []
                for idx in final_selection:
                    if idx == idx_max: labels.append(f"Line {idx} (MAX/MOON)")
                    elif idx == idx_min: labels.append(f"Line {idx} (MIN/CRASH)")
                    elif idx == idx_med: labels.append(f"Line {idx} (MEDIAN)")
                    else: labels.append(f"Line {idx} (USER SELECTION)")

                m1, m2, m3 = st.columns(3)
                m1.metric("Prob. to Hit Target", format_percent(res['hit_prob']))
                m2.metric("P50 (Most Likely)", format_rupiah(res["p50"]))
                m3.metric("Sample Hits", f"{np.sum(res['hit_mask'][:sample_limit])} / {sample_limit}")

                ptab1, ptab2 = st.tabs(["🎯 Pattern Analysis", "📊 Full Sample Cloud"])
                with ptab1:
                    st.write(f"Comparing the 'Black Swan' extremes against the 'Median' path for {sim_s}")
                    st.line_chart(pd.DataFrame(pattern_paths, columns=labels))
                with ptab2:
                    st.line_chart(pd.DataFrame(paths[:, :sample_limit]))

# -- TAB 2: INTRADAY SURVIVAL SWARM --
with tab_sim2:
    @st.cache_data(ttl=60)
    def get_live_data(ticker):
        try:
            return yf.Ticker(ticker).history(period="1d", interval="1h")["Close"]
        except: return pd.Series()

    @st.cache_data(ttl=3600)
    def get_historical_vol(ticker):
        try:
            h = yf.Ticker(ticker).history(period="5d", interval="1h")["Close"]
            returns = h.pct_change().dropna()
            return returns.mean(), returns.std()
        except: return 0, 0.02

    def run_survival_sim(ticker, tolerance, sims=1000, total_hours=7):
        actual_prices = get_live_data(ticker)
        if actual_prices.empty: return None, None, 0
        hours_passed = len(actual_prices)
        current_real, first_real = actual_prices.iloc[-1], actual_prices.iloc[0]
        drift, vol = get_historical_vol(ticker)

        paths = np.zeros((total_hours, sims))
        paths[0] = first_real
        for t in range(1, total_hours):
            paths[t] = paths[t-1] * np.exp(drift + vol * np.random.normal(0, 1, sims))

        diff = np.abs(paths[hours_passed-1] - current_real) / current_real
        surviving_paths = paths[:, diff <= (tolerance / 100)]
        return surviving_paths, actual_prices, hours_passed

    sc1, sc2 = st.columns(2)
    with sc1: sv_stock = st.selectbox("Select Stock for Survival", df["Stock"], key="sv_stock")
    with sc2: tol_level = st.slider("Elimination Tolerance (%)", 0.05, 2.0, 0.2, help="Ketatnya seleksi pergerakan harga historis vs riil.")

    if st.button("🛡️ Run Survival Filter"):
        t_sym = df.loc[df["Stock"] == sv_stock, "Ticker"].iloc[0]
        surv_paths, act_prices, hrs_passed = run_survival_sim(t_sym, tol_level)
        
        if surv_paths is not None:
            num_survivors = surv_paths.shape[1]
            sm1, sm2, sm3 = st.columns(3)
            sm1.metric("Current Hour", f"Hour {hrs_passed}")
            sm2.metric("Surviving Paths", num_survivors)
            sm3.metric("Current Price", format_rupiah(act_prices.iloc[-1]))

            max_disp = min(num_survivors, 100)
            plot_df = pd.DataFrame(surv_paths[:, :max_disp])
            actual_full = act_prices.tolist() + [np.nan] * (7 - len(act_prices.tolist()))
            plot_df["ACTUAL (REAL)"] = actual_full

            st.line_chart(plot_df)
            if num_survivors > 0: st.success(f"Probabilitas Penutupan (P50): **{format_rupiah(np.percentile(surv_paths[-1], 50))}**")
            else: st.error("Semua garis tereliminasi! Coba naikkan Tolerance Level.")

# -------------------------
# FUNDAMENTALS & AI REPORT
# -------------------------
st.divider()
st.subheader("Fundamental Snapshot")

@st.cache_data(ttl=3600)
def get_fundamentals(ticker):
    try:
        info = yf.Ticker(ticker).info
        return {
            "Ticker": ticker, "Sector": info.get("sector", "Unknown"), "Price": info.get("currentPrice"),
            "PE": info.get("trailingPE"), "PB": info.get("priceToBook"), "Dividend Yield": info.get("dividendYield"),
            "ROE": info.get("returnOnEquity"), "Beta": info.get("beta")
        }
    except: return {"Ticker": ticker, "Sector": "Unknown"}

fundamentals = [get_fundamentals(t) for t in portfolio["Ticker"]]
fundamental_df = pd.DataFrame(fundamentals)
st.dataframe(fundamental_df)

st.subheader("AI Strategic Analyst")
if st.button("Generate Comprehensive AI Analysis"):
    with st.spinner("Analyzing Fundamentals, Technicals, and Probability Models..."):
        # Combine V2 Monte Carlo summary for context
        mc_summary = ""
        for _, r in df.iterrows():
            mc = run_monte_carlo(r["Ticker"], target_price=r["Buy Max"], sims=500) # Lighter sim for background context
            if mc: mc_summary += f"{r['Stock']}: Hit Prob {mc['hit_prob']:.1f}%, P50 {mc['p50']}\n"
        
        prompt = f"""
        Kamu adalah analis saham kuantitatif Indonesia. Analisis portofolio ini:

        DATA FUNDAMENTAL (SECTOR-SPECIFIC):
        {fundamental_df.to_string(index=False)}

        DATA MARKET SIGNALS & PERFORMANCE:
        {df.to_string(index=False)}
        
        DATA SIMULASI MONTE CARLO (TARGET: BUY MAX):
        {mc_summary}

        Berikan analisis lengkap yang mencakup:
        1. Analisis sektoral berdasarkan data fundamental.
        2. Evaluasi 4-Poin per saham: Range & P50, Hit Probability, Outlook 1-Bulan, dan Status Portofolio (Risky/Noise/Performing).
        3. Rekomendasi eksekusi buy/wait.
        """
        try:
            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role":"user","content":prompt}],
                temperature=0.3
            )
            st.markdown(completion.choices[0].message.content)
        except Exception as e:
            st.error(f"AI Error: {e}")
