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

@st.cache_data(ttl=43200, show_spinner=False)
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
# 側邊欄：控制台 (重新設計勾選邏輯)
# ==========================================
st.sidebar.header("🔑 AI 投資長授權")
ai_api_key = st.sidebar.text_input("輸入 OpenAI API 金鑰 (sk-開頭)：", type="password")
st.sidebar.markdown("---")

st.sidebar.header("🎯 掃描範圍")
scan_mode = st.sidebar.radio("雷達強度：", ["🧪 快速測試模式 (50檔)", "🔥 火力全開模式 (1700檔)"])
st.sidebar.markdown("---")

st.sidebar.header("⚙️ 篩選條件開關")
# ⭐ 新增勾選方塊，讓老闆決定哪些條件要生效
use_vol = st.sidebar.checkbox("1. 成交量過濾", value=True)
if use_vol:
    set_volume = st.sidebar.number_input("最低成交量 (張)", min_value=0, value=5000)

use_kd_below = st.sidebar.checkbox("2. KD 低位過濾 (KD < 20)", value=False)
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
# 1. 策略選股雷達 (套用勾選邏輯)
# ------------------------------------------
with tab1:
    if st.button("🚀 開始執行篩選！", type="primary"):
        passed_stocks = []
        all_stocks = get_all_tw_stocks()
        stock_database = random.sample(all_stocks, min(50, len(all_stocks))) if "測試模式" in scan_mode else all_stocks
        progress_bar = st.progress(0)
        
        for i, stock in enumerate(stock_database):
            progress_bar.progress((i + 1) / len(stock_database))
            df = get_stock_history(stock, "6mo")
            if df.empty: continue
            try:
                # 即使沒勾選也需要先算好數據，以便篩選
                df_calc = calculate_indicators(df.copy(), 
                                               kd_days if 'kd_days' in locals() else 9, 
                                               macd_fast if 'macd_fast' in locals() else 12, 
                                               macd_slow if 'macd_slow' in locals() else 26, 
                                               bb_days if 'bb_days' in locals() else 20, 
                                               bb_std if 'bb_std' in locals() else 2.0)
                latest = df_calc.iloc[-1]
                
                # ⭐ 核心篩選邏輯：只有勾選的才檢查
                if use_vol and (latest['Volume'] / 1000) < set_volume: continue
                if use_kd_below and (latest['K'] > kd_val or latest['D'] > kd_val): continue
                if use_macd_below and latest['MACD'] >= 0: continue
                if use_bb_below_mid and latest['Close'] >= latest['Middle_BB']: continue
                
                passed_stocks.append({"代號": stock.replace('.TW', '').replace('.TWO', ''), "收盤價": round(latest['Close'], 2)})
            except:
                pass
        st.success("✅ 篩選完成！")
        if passed_stocks: st.dataframe(pd.DataFrame(passed_stocks), use_container_width=True)
        else: st.error("沒有股票同時符合您「勾選」的條件。")

# ------------------------------------------
# 2. AI 新聞解讀 
# ------------------------------------------
with tab2:
    st.subheader("🤖 個股深度分析")
    target_stock_news = st.text_input("輸入股票代號：", "3231", key="news_input")
    if st.button("🧠 開始分析"):
        if not ai_api_key.startswith("sk-"): st.error("請輸入 OpenAI 金鑰！")
        else:
            with st.spinner("🌐 搜集新聞中..."): news_data = get_stock_news(target_stock_news)
            if news_data:
                prompt = f"請分析【{target_stock_news}】新聞：1. 情緒 2. 主力意圖 3. 建議\n\n{chr(10).join(news_data)}"
                try:
                    res = OpenAI(api_key=ai_api_key).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                    st.write(res.choices[0].message.content)
                except Exception as e: st.error(f"分析失敗：{e}")
            else: st.warning("找不到新聞。")

# ------------------------------------------
# 3. 歷史勝率回測 (也同步套用勾選邏輯)
# ------------------------------------------
with tab3:
    st.subheader("📈 真實數據回測")
    target_stock_bt = st.text_input("輸入代號回測：", "2330", key="bt_input")
    if st.button("⏳ 啟動回測"):
        with st.spinner("調閱 1 年資料中..."):
            stock_id = f"{target_stock_bt}.TW" if len(target_stock_bt) == 4 else target_stock_bt
            df_bt = get_stock_history(stock_id, period="1y")
            if df_bt.empty: st.error("抓不到資料。")
            else:
                df_bt = calculate_indicators(df_bt.copy(), 
                                               kd_days if 'kd_days' in locals() else 9, 
                                               macd_fast if 'macd_fast' in locals() else 12, 
                                               macd_slow if 'macd_slow' in locals() else 26, 
                                               bb_days if 'bb_days' in locals() else 20, 
                                               bb_std if 'bb_std' in locals() else 2.0).dropna()
                trades, in_position, buy_price = [], False, 0
                for date, row in df_bt.iterrows():
                    if not in_position:
                        # ⭐ 進場檢查也套用勾選開關
                        v_ok = (row['Volume']/1000) >= set_volume if use_vol else True
                        k_ok = (row['K'] <= kd_val and row['D'] <= kd_val) if use_kd_below else True
                        m_ok = row['MACD'] < 0 if use_macd_below else True
                        b_ok = row['Close'] < row['Middle_BB'] if use_bb_below_mid else True
                        
                        if v_ok and k_ok and m_ok and b_ok:
                            in_position, buy_price, buy_date = True, row['Close'], date.strftime('%Y-%m-%d')
                    else:
                        if row['Close'] >= row['Middle_BB'] or row['Close'] <= buy_price * 0.9: 
                            trades.append({'進場': buy_date, '出場': date.strftime('%Y-%m-%d'), '報酬率': f"{((row['Close'] - buy_price) / buy_price)*100:.2f}%"})
                            in_position = False
                if trades: st.dataframe(pd.DataFrame(trades))
                else: st.warning("這段時間內從未符合您的「勾選條件」。")

with tab4:
    st.subheader("🌅 晨間作戰分析")
    if st.button("☕ 生成報告"):
        if not ai_api_key.startswith("sk-"): st.error("請輸入金鑰！")
        else:
            with st.spinner("連線中..."): ov_data = get_overnight_market_data()
            if ov_data:
                st.write(ov_data)
                prompt = f"根據數據預測台股開盤建議：\n{ov_data}"
                try:
                    res = OpenAI(api_key=ai_api_key).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                    st.write(res.choices[0].message.content)
                except Exception as e: st.error(e)

with tab5:
    st.subheader("💼 我的庫存股")
    if worksheet is None: st.error("⚠️ 雲端連線失敗！")
    col1, col2 = st.columns(2)
    with col1:
        new_stock = st.text_input("➕ 新增股票")
        if st.button("加入"):
            if new_stock and new_stock not in st.session_state.my_portfolio:
                if worksheet: worksheet.append_row([new_stock])
                st.session_state.my_portfolio.append(new_stock)
                st.rerun()
    with col2:
        del_stock = st.text_input("🗑️ 刪除股票")
        if st.button("移除"):
            if del_stock in st.session_state.my_portfolio:
                if worksheet:
                    cell = worksheet.find(del_stock)
                    if cell: worksheet.delete_rows(cell.row)
                st.session_state.my_portfolio.remove(del_stock)
                st.rerun()
    if st.session_state.my_portfolio:
        portfolio_data = []
        for stock in st.session_state.my_portfolio:
            df = get_stock_history(f"{stock}.TW" if len(stock) == 4 else stock, "5d")
            if not df.empty and len(df) >= 2:
                last_price, prev_price = df['Close'].iloc[-1], df['Close'].iloc[-2]
                portfolio_data.append({"代號": stock, "最新收盤價": round(last_price, 2), "漲跌幅(%)": round(((last_price - prev_price) / prev_price) * 100, 2)})
        st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True)
        if st.button("🔥 一鍵診斷"):
            if not ai_api_key.startswith("sk-"): st.error("請輸入金鑰！")
            else:
                all_news = []
                for stock in st.session_state.my_portfolio: all_news.extend(get_stock_news(stock, limit=2))
                prompt = f"庫存總體檢：\n{chr(10).join(all_news)}"
                try:
                    res = OpenAI(api_key=ai_api_key).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                    st.write(res.choices[0].message.content)
                except Exception as e: st.error(e)
