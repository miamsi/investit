import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
from datetime import datetime
from scipy.optimize import minimize

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except:
    GROQ_AVAILABLE = False

st.set_page_config(layout="wide")

st.title("📊 IHSG Quant Investment Lab")

# -----------------------------
# LOAD DATA
# -----------------------------

@st.cache_data
def load_stock_data():
    return pd.read_csv("master_schedule_rows.csv")

@st.cache_data
def load_bonds():
    return pd.read_excel("LIST HARGA OBLIGASI PER 12 MARET 2026.xlsx")

@st.cache_data
def load_ihsg():
    df = pd.read_excel("Daftar Saham  - 20260306.xlsx")
    df["ticker"] = df["Kode"].astype(str) + ".JK"
    return df

stocks = load_stock_data()
bonds = load_bonds()
ihsg = load_ihsg()

# -----------------------------
# SIDEBAR SETTINGS
# -----------------------------

st.sidebar.header("Portfolio Settings")

capital = st.sidebar.number_input(
    "Total Capital (IDR)",
    value=100000000
)

stock_weight = st.sidebar.slider(
    "Stock Allocation %",
    0,
    100,
    60
)

bond_weight = 100 - stock_weight

stock_capital = capital * stock_weight / 100
bond_capital = capital * bond_weight / 100

# -----------------------------
# FACTOR SCORING MODEL
# -----------------------------

stocks["price_upside"] = (
    stocks["predicted_high"] - stocks["live_price_2026"]
) / stocks["live_price_2026"]

stocks["dividend_score"] = stocks["dividend_yield"] / stocks["dividend_yield"].max()
stocks["roe_score"] = stocks["roe"] / stocks["roe"].max()

stocks["value_score"] = 1 / stocks["pe_ratio"]

stocks["total_score"] = (
    stocks["price_upside"] * 0.4 +
    stocks["dividend_score"] * 0.3 +
    stocks["roe_score"] * 0.2 +
    stocks["value_score"] * 0.1
)

top_stocks = stocks.sort_values(
    "total_score",
    ascending=False
).head(10)

st.subheader("🏆 Top Quant Ranked Stocks")

st.dataframe(top_stocks)

# -----------------------------
# FETCH MARKET RETURNS
# -----------------------------

@st.cache_data
def get_returns(tickers):

    data = yf.download(
        tickers,
        period="1y",
        auto_adjust=True,
        progress=False
    )

    # yfinance may return multi-index columns
    if isinstance(data.columns, pd.MultiIndex):

        if "Adj Close" in data.columns.levels[0]:
            prices = data["Adj Close"]

        elif "Close" in data.columns.levels[0]:
            prices = data["Close"]

        else:
            prices = data.iloc[:, :len(tickers)]

    else:
        prices = data

    returns = prices.pct_change().dropna()

    return returns

returns = get_returns(top_stocks["ticker"].tolist())

# -----------------------------
# MONTE CARLO SIMULATION
# -----------------------------

def monte_carlo(returns, simulations=5000):

    mean_returns = returns.mean()
    cov = returns.cov()

    weights = np.random.dirichlet(
        np.ones(len(mean_returns)),
        simulations
    )

    portfolio_returns = []
    portfolio_volatility = []

    for w in weights:

        r = np.sum(mean_returns * w) * 252
        v = np.sqrt(np.dot(w.T, np.dot(cov * 252, w)))

        portfolio_returns.append(r)
        portfolio_volatility.append(v)

    return weights, portfolio_returns, portfolio_volatility


weights, r, v = monte_carlo(returns)

mc = pd.DataFrame({
    "return": r,
    "volatility": v
})

fig = px.scatter(
    mc,
    x="volatility",
    y="return",
    title="Monte Carlo Efficient Frontier"
)

st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# OPTIMAL PORTFOLIO
# -----------------------------

def optimize_portfolio(returns):

    mean = returns.mean()
    cov = returns.cov()

    n = len(mean)

    init_weights = np.ones(n) / n

    def portfolio_volatility(w):
        return np.sqrt(np.dot(w.T, np.dot(cov, w)))

    constraints = (
        {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    )

    bounds = tuple((0, 1) for _ in range(n))

    result = minimize(
        portfolio_volatility,
        init_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints
    )

    return result.x

optimal_weights = optimize_portfolio(returns)

portfolio = pd.DataFrame({
    "ticker": returns.columns,
    "weight": optimal_weights
})

st.subheader("⚖️ Optimal Portfolio Allocation")

st.dataframe(portfolio)

# -----------------------------
# DIVIDEND FORECAST
# -----------------------------

dividend_income = (
    top_stocks["dividend_yield"].mean() / 100
) * stock_capital

st.metric(
    "Estimated Annual Dividend",
    f"Rp {dividend_income:,.0f}"
)

# -----------------------------
# BOND ANALYSIS
# -----------------------------

bonds["END DATE"] = pd.to_datetime(bonds["END DATE"])

bonds["years_left"] = (
    bonds["END DATE"] - datetime.today()
).dt.days / 365

bonds["yield"] = bonds["YEARLY COUPON RATE"]

best_bonds = bonds.sort_values(
    "yield",
    ascending=False
).head(5)

bond_income = bond_capital * best_bonds["yield"].mean()

st.subheader("🏦 Best Bonds")

st.dataframe(best_bonds)

st.metric(
    "Bond Coupon Income",
    f"Rp {bond_income:,.0f}"
)

# -----------------------------
# PORTFOLIO SUMMARY
# -----------------------------

total_income = dividend_income + bond_income
total_return = total_income / capital

col1, col2, col3 = st.columns(3)

col1.metric(
    "Expected Annual Income",
    f"Rp {total_income:,.0f}"
)

col2.metric(
    "Portfolio Yield",
    f"{total_return*100:.2f}%"
)

col3.metric(
    "Capital",
    f"Rp {capital:,.0f}"
)

# -----------------------------
# AI ADVISOR
# -----------------------------

st.subheader("🤖 AI Portfolio Advisor")

if GROQ_AVAILABLE:

    if st.button("Generate AI Analysis"):

        try:

            client = Groq(api_key=st.secrets["GROQ_API_KEY"])

            stock_table = top_stocks[['ticker','dividend_yield','roe','pe_ratio']].head(5).to_string()
            bond_table = best_bonds[["BOND'S CODE","YEARLY COUPON RATE"]].head(5).to_string()

            prompt = f"""
Analyze this Indonesian investment portfolio.

Capital: {capital}
Stock Allocation: {stock_weight}%
Bond Allocation: {bond_weight}%

Top Stocks:
{stock_table}

Bonds:
{bond_table}

Provide:
- strengths
- risks
- improvement suggestions
"""

            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500
            )

            st.write(completion.choices[0].message.content)

        except Exception as e:
            st.error(e)

else:
    st.info("Groq library not installed. Install 'groq' to enable AI advisor.")

# -----------------------------
# STOCK PRICE VIEWER
# -----------------------------

st.subheader("📈 Stock Price Viewer")

ticker = st.selectbox(
    "Select IHSG Stock",
    ihsg["ticker"].tolist()
)

price_data = yf.download(
    ticker,
    period="1y",
    progress=False
)

if price_data.empty:
    st.warning("No price data available.")
else:

    # Handle multi-index columns from yfinance
    if isinstance(price_data.columns, pd.MultiIndex):
        price_data.columns = price_data.columns.get_level_values(0)

    if "Close" not in price_data.columns:
        st.error("Close price not found in dataset.")
    else:
        fig2 = px.line(
            price_data,
            y="Close",
            title=f"{ticker} Price Chart"
        )

        st.plotly_chart(fig2, use_container_width=True)
