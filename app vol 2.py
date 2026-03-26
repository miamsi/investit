import streamlit as st
import yfinance as yf
import pandas as pd
from supabase import create_client
import datetime
from groq import Groq

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import io

st.set_page_config(page_title="Investment Card Monitor", layout="wide")

def format_rupiah(value):
    if pd.isna(value):
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")

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

url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])

st.title("Investment Card Monitor")

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

# DIVIDEND HISTORY (fallback)
dividend_history = {
    "BBRI": 5,
    "PTBA": 12,
    "TLKM": 6,
    "BSSR": 10
}

ex_dates = {
    "BBRI": datetime.date(2026,4,10),
    "PTBA": datetime.date(2026,4,8),
    "TLKM": datetime.date(2026,5,15),
    "BSSR": datetime.date(2026,4,12)
}

@st.cache_data(ttl=300)
def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")

    price = hist["Close"].iloc[-1]
    ma200 = hist["Close"].rolling(200).mean().iloc[-1]
    low_52 = hist["Low"].min()

    change = (hist["Close"].iloc[-1] - hist["Close"].iloc[-22]) / hist["Close"].iloc[-22] * 100

    return price, ma200, low_52, change

prices=[]
ma200_list=[]
dist_list=[]
low_list=[]
dist_low=[]
div_yield=[]
deadline=[]
days_left=[]

for ticker, stock in zip(df["Ticker"], df["Stock"]):

    price, ma200, low, change = get_stock_data(ticker)

    distance = (price - ma200)/ma200*100
    low_distance = (price - low)/low*100

    div = dividend_history.get(stock, 0)

    ex = ex_dates.get(stock)
    if ex:
        last_buy = ex - datetime.timedelta(days=1)
        days = (last_buy - datetime.date.today()).days
    else:
        last_buy = None
        days = None

    prices.append(price)
    ma200_list.append(ma200)
    dist_list.append(distance)
    low_list.append(low)
    dist_low.append(low_distance)
    div_yield.append(div)
    deadline.append(last_buy)
    days_left.append(days)

df["Price"]=prices
df["MA200"]=ma200_list
df["MA Dist %"]=dist_list
df["52W Low"]=low_list
df["Low Dist %"]=dist_low
df["Est Div %"]=div_yield
df["Last Buy"]=deadline
df["Days Left"]=days_left

def decision(row):
    if row["Price"] >= row["Buy Min"] and row["Price"] <= row["Buy Max"]:
        return "BUY"
    if row["Price"] < row["Buy Min"]:
        return "STRONG BUY"
    return "WAIT"

df["Decision"]=df.apply(decision,axis=1)

def alternative(row):
    if row["Decision"]=="BUY":
        return "-"
    peers = peer_groups[row["Ticker"]]
    for p in peers:
        try:
            price, ma200, _, _ = get_stock_data(p)
            if (price-ma200)/ma200*100 < -3:
                return p.replace(".JK","")
        except:
            continue
    return "-"

df["Alternative"]=df.apply(alternative,axis=1)

# LOAD TRANSACTION
response=supabase.table("transactions").select("*").execute()
transactions=pd.DataFrame(response.data)

if not transactions.empty:
    summary = transactions.groupby("ticker")["capital_used"].sum().reset_index()
    df=df.merge(summary,how="left",left_on="Stock",right_on="ticker")
else:
    df["capital_used"]=0

df["capital_used"]=df["capital_used"].fillna(0)
df["Remaining"]=df["Target Capital"]-df["capital_used"]

# DISPLAY
st.subheader("Market")

view=df.copy()
view["Price"]=view["Price"].apply(format_rupiah)
view["Buy Min"]=view["Buy Min"].apply(format_rupiah)
view["Buy Max"]=view["Buy Max"].apply(format_rupiah)

st.dataframe(view[[
"Stock","Price","Buy Min","Buy Max",
"MA Dist %","Low Dist %","Est Div %",
"Days Left","Decision","Alternative"
]])

# PDF REPORT
def generate_pdf():

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    elements = []

    total_target = df["Target Capital"].sum()
    total_used = df["capital_used"].sum()
    remaining = total_target - total_used

    elements.append(Paragraph("Investment Report", styles["Title"]))
    elements.append(Spacer(1,12))

    elements.append(Paragraph(f"Total Target: {format_rupiah(total_target)}", styles["Normal"]))
    elements.append(Paragraph(f"Deployed: {format_rupiah(total_used)}", styles["Normal"]))
    elements.append(Paragraph(f"Remaining: {format_rupiah(remaining)}", styles["Normal"]))
    elements.append(Spacer(1,12))

    for _,row in df.iterrows():
        text = f"""
        {row['Stock']} | Price: {format_rupiah(row['Price'])} |
        Decision: {row['Decision']} |
        Div Est: {row['Est Div %']}% |
        Days Left: {row['Days Left']}
        """
        elements.append(Paragraph(text, styles["Normal"]))
        elements.append(Spacer(1,10))

    doc.build(elements)
    buffer.seek(0)
    return buffer

st.subheader("Export")

pdf = generate_pdf()

st.download_button(
    label="Download PDF Report",
    data=pdf,
    file_name="investment_report.pdf",
    mime="application/pdf"
)
