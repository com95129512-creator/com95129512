import streamlit as st
import yfinance as yf
import pandas as pd
import time, requests, random, urllib3, urllib.parse, json, gspread
import xml.etree.ElementTree as ET
from openai import OpenAI 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="老闆的專屬選股雷達", layout="wide")
st.title("📊 專屬 AI 策略選股雷達 & 庫存戰情室 (🚀 鈦合金主力版)")

# ==========================================
# 💾 雲端資料庫連線
# ==========================================
@st.cache_resource
def init_db():
    try:
        creds_dict = json.loads(st.secrets["google_credentials"])
        return gspread.service_account_from_dict(creds_dict).open("My_Stock_Portfolio").sheet1
    except: return None

worksheet = init_db()

if 'my_portfolio' not in st.session_state:
    if worksheet:
        try: st.session_state.my_portfolio = [r for r in worksheet.col_values(1) if r != 'Stock_ID' and r.strip() != '']
        except: st.session_state.my_portfolio = []
    else: st.session_state.my_portfolio = [] 

# ==========================================
# 📡 核心函數區 (內建主力名單，徹底繞過政府封鎖)
# ==========================================
@st.cache_data
def get_all_tw_stocks():
    # 老闆專屬
