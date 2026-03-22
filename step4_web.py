import streamlit as st
import yfinance as yf
import pandas as pd
import time
import requests
import random
import urllib3
import xml.etree.ElementTree as ET
import urllib.parse
from openai import OpenAI 

# 關閉不安全連線警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="老闆的專屬選股雷達", layout="wide")
st.title("📊 專屬 AI 策略選股雷達 & 歷史回測中心 (🚀 旗艦版)")

# ==========================================
# 📡 函數區：抓取名單與歷史資料
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

@st.cache_data(ttl=43200, show_spinner=False)
def get_stock_history(stock_id, period="6mo"):
    try:
        df = yf.Ticker(stock_id).history(period=period)
        if not df.empty: return df
    except:
        pass
    return pd.DataFrame()

# ⭐ 新增函數：抓取夜盤與美股關鍵數據
@st.cache_data(ttl=3600, show_spinner=False)
def get_overnight_market_data():
    tickers = {
        '台積電 ADR (台股風向球)': 'TSM', 
        '費城半導體 (科技硬體)': '^SOX', 
        '納斯達克 (美股科技)': '^IXIC', 
        '道瓊工業 (美股傳產)': '^DJI'
    }
    results = {}
    for name, ticker in tickers.items():
        try:
            df = yf.Ticker(ticker).history(period="5d")
            if len(df) >= 2:
                last_close = df['Close'].iloc[-1]
                prev_close = df['Close'].iloc[-2]
                pct_change = ((last_close - prev_close) / prev_close) * 100
                results[name] = {
                    "收盤價": round(last_close, 2), 
                    "漲跌幅": round(pct_change, 2)
                }
        except:
            pass
    return results

def get_stock_news(stock_name):
    query = urllib.parse.quote(f"{stock_name} 台灣 股票")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ce
