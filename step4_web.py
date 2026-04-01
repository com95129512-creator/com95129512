import streamlit as st
import yfinance as yf
import pandas as pd
import time
import requests
import random
import urllib3
import urllib.parse
import json
import gspread
import xml.etree.ElementTree as ET
from openai import OpenAI 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="老闆的專屬選股雷達", layout="wide")
st.title("📊 專屬 AI 策略選股雷達 & 庫存戰情室 (🚀 彈性參數版)")

# ==========================================
# 💾 雲端資料庫連線 (Google Sheets)
# ==========================================
@st.cache_resource
def init_db():
    try:
        creds_dict = json.loads(st.secrets["google_credentials"])
        gc = gspread.service_account_from_dict(creds_dict)
        return gc.open("My_Stock_Portfolio").sheet1
    except:
        return None

worksheet = init_db()

if 'my_portfolio' not in st.session_state:
    if worksheet:
        try:
            records = worksheet.col_values(1)
            st.session_state.my_portfolio = [r for r in records if r != 'Stock_ID' and r.strip() != '']
        except:
            st.session_state.my_portfolio = []
    else:
        st.session_state.my_portfolio = [] 

# ==========================================
# 📡 核心函數區
# ==========================================
@st.cache_data(ttl=86400)
def get_all_tw_stocks():
    stock_list = []
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=headers, timeout=10, verify=False).json()
        for item in res_twse:
            if len(item.get('Code', '')) == 4 and item.get('Code', '').isdigit(): stock_list.append(f"{item.get('Code')}.TW")
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, timeout=10, verify=False).json()
        for item in res_tpex:
            code = item.get('SecuritiesCompanyCode', item.get('Code', ''))
            if len(code) == 4 and code.isdigit(): stock_list.append(f"{code}.TWO")
        return stock_list
    except:
        return ["2330.TW", "2317.TW", "3231.TW", "2603.TW", "2308.TW"]

# ⭐ 將記憶體縮短為 1 小時，確保盤中資料不會過期太久
@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_history(stock_id, period="6mo"):
    try:
        df = yf.Ticker(stock_id).history(period=period)
        if not df.empty: return df
    except:
        pass
    return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def get_overnight_market_data():
    tickers = {'台積電 ADR': 'TSM', '費城半導體': '^SOX', '納斯達克': '^IXIC', '道瓊工業': '^DJI'}
    results = {}
    for name, ticker in tickers.items():
        try:
            df = yf.Ticker(ticker).history(period="5d")
            if len(df) >= 2:
                last_close = df['Close'].iloc[-1]
                prev_close = df['Close'].iloc[-2]
                results[name] = {"收盤價": round(last_close, 2), "漲跌幅": round(((last_close - prev_close) / prev_close) * 100, 2)}
        except:
            pass
    return results

def get_stock_news(stock_name, limit=5):
    query = urllib.parse.quote(f"{stock_name} 台灣 股票")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        res = requests.get(url, verify=False, timeout=10)
        news_list = []
        for item in ET.fromstring(res.text).findall('.//item')[:limit]: 
            news_list.append(f"[{stock_name}] 日期: {item.find('pubDate').text} | 標題: {item.find('title').text}")
        return news_list
    except:
        return []

def calculate_indicators(df, kd_days, macd_fast, macd_slow, bb_days, bb_std):
    # ⭐ 強制轉換為整數，避免運算 Bug
    kd_days, macd_fast, macd_slow, bb_days = int(kd_days), int(macd_fast), int(macd_slow), int(bb_days)
    
    low_min = df['Low'].rolling(window=kd_days).min()
    high_max = df['High'].rolling(window=kd_days).max()
    df['RSV'] = 100 * ((df['Close'] - low_min) / (high_max - low_min))
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    df['MACD'] = df['Close'].ewm(span=macd_fast, adjust=False).mean() - df['Close'].ewm(span=macd_slow, adjust=False).mean()
    df['Middle_BB'] = df['Close'].rolling(window=bb_days).mean()
    df['STD'] = df['Close'].rolling(window=bb_days).std()
    df['Upper_BB'] = df['Middle_BB'] + (df['STD'] * bb_std)
    df['Lower_BB'] = df['Middle_BB'] - (df['STD'] * bb_std)
    return df

# ==========================================
# 側邊欄：控制台
# ==========================================
st.sidebar.header("🔑 AI 投資長授權")
ai_api_key = st.sidebar.text_input("輸入 OpenAI API 金鑰 (sk-開頭)：", type="password")
st.sidebar.markdown("---")

st.sidebar.header("🎯 掃描範圍")
scan_mode = st.sidebar.radio("雷達強度：", ["🧪 快速測試模式 (50檔)", "🔥 火力全開模式 (1700檔)"])
st.sidebar.markdown("---")

st.sidebar.header("⚙️ 篩選條件開關")

# ⭐ 預設參數 (不管有沒有勾選，都給定一組健康的預設值，避免程式出錯)
set_volume = 5000
kd_val = 20; kd_days = 9
macd_fast = 12; macd_slow = 26
bb_days = 20; bb_std = 2.0

use_vol = st.sidebar.checkbox("1. 成交量過濾", value=True)
if use_vol:
    set_volume = st.sidebar.number_input("最低成交量 (張)", min_value=0, value=5000)

use_kd_below = st.sidebar.checkbox("2. KD 低位過濾", value=False)
if use_kd_below:
    kd_val = st.sidebar.slider("KD 門檻值 (需低於此值)", 0, 100, 20)
    kd_days = st.sidebar.number_input("KD 計算天數", value=9)

use_macd_below = st.sidebar.checkbox("3. MACD 空方過濾 (MACD < 0)", value=False)
if use_macd_below:
    macd_fast = st.sidebar.number_input("MACD 快線", value=12)
    macd_slow = st.sidebar.number_input("MACD 慢線", value=26)

use_bb_below_mid = st.sidebar.checkbox("4. 布林中線之下 (股價 < 20MA)", value=False)
if use_bb_below_mid:
    bb_days = st.sidebar.number_input("布林(均線)天數", value=20)
    bb_std = st.sidebar.number_input("布林標準差", value=2.0)

# ==========================================
# 🚀 主畫面：五頁籤設計
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 雷達掃描", "📰 個股新聞", "📈 歷史回測", "🌙 晨間會議", "💼 我的庫存股"])

# ------------------------------------------
# 1. 策略選股雷達
# ------------------------------------------
with tab1:
    # ⭐ 新增清除記憶體的機制
    col_run, col_clear = st.columns([3, 1])
    with col_run:
        run_btn = st.button("🚀 開始執行篩選！", type="primary", use_container_width=True)
    with col_clear:
        if st.button("🔄 清除記憶體 (強制抓最新)", use_container_width=True):
            st.cache_data.clear() # 清空所有暫存資料
            st.success("✅ 記憶體已徹底清空！請重新點擊掃描按鈕。")

    if run_btn:
        passed_stocks = []
        all_stocks = get_all_tw_stocks()
        stock_database = random.sample(all_stocks, min(50, len(all_stocks))) if "測試模式" in scan_mode else all_stocks
        progress_bar = st.progress(0)
        
        for i, stock in enumerate(stock_database):
            progress_bar.progress((i + 1) / len(stock_database))
            df = get_stock_history(stock, "6mo")
            if df.empty: continue
            try:
                # 無論如何都先計算指標，參數帶入預設值或使用者設定值
                df_calc = calculate_indicators(df.copy(), kd_days, macd_fast, macd_slow, bb_days, bb_std)
                latest = df_calc.iloc[-1]
                
                # 只有打勾的條件才會進行排除 (continue)
                if use_vol and (latest['Volume'] / 1000) < set_volume: continue
                if use_kd_below and (latest['K'] > kd_val or latest['D'] > kd_val): continue
                if use_macd_below and latest['MACD'] >= 0: continue
                if use_bb_below_mid and latest['Close'] >= latest
