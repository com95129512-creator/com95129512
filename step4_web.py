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
@st.cache_data(ttl=3600, show_spinner=False) # 快取 1 小時
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
            # 抓取近5天確保能跨越週末抓到最後一個交易日
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
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        res = requests.get(url, verify=False, timeout=10)
        root = ET.fromstring(res.text)
        news_list = []
        for item in root.findall('.//item')[:5]: 
            news_list.append(f"日期: {item.find('pubDate').text} | 標題: {item.find('title').text}")
        return news_list
    except:
        return []

def calculate_indicators(df, kd_days, macd_fast, macd_slow, bb_days, bb_std):
    low_min = df['Low'].rolling(window=kd_days).min()
    high_max = df['High'].rolling(window=kd_days).max()
    df['RSV'] = 100 * ((df['Close'] - low_min) / (high_max - low_min))
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    exp1 = df['Close'].ewm(span=macd_fast, adjust=False).mean()
    exp2 = df['Close'].ewm(span=macd_slow, adjust=False).mean()
    df['MACD'] = exp1 - exp2
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

st.sidebar.header("🎯 掃描範圍設定")
scan_mode = st.sidebar.radio("請選擇雷達掃描強度：", ["🧪 快速測試模式 (50檔)", "🔥 火力全開模式 (1700檔)"])
st.sidebar.markdown("---")

st.sidebar.header("⚙️ 1. 成交量設定")
set_volume = st.sidebar.number_input("最低成交量要求 (張)", min_value=0, value=5000, step=500)

st.sidebar.header("⚙️ 2. KD 指標設定")
kd_days = st.sidebar.number_input("KD 計算天數", min_value=3, value=9, step=1)
k_range = st.sidebar.slider("K 值範圍：", 0, 100, (0, 100))
d_range = st.sidebar.slider("D 值範圍：", 0, 100, (0, 100))

st.sidebar.header("⚙️ 3. MACD 指標設定")
macd_fast = st.sidebar.number_input("MACD 快線", min_value=1, value=12, step=1)
macd_slow = st.sidebar.number_input("MACD 慢線", min_value=1, value=26, step=1)
filter_macd = st.sidebar.radio("MACD 狀態：", ["不篩選", "🔴 大於 0 (紅柱)", "🟢 小於 0 (綠柱)"])

st.sidebar.header("⚙️ 4. 布林通道設定")
bb_days = st.sidebar.number_input("布林中軌天數", min_value=5, value=20, step=1)
bb_std = st.sidebar.number_input("標準差倍數", min_value=1.0, value=3.0, step=0.1)
filter_bb = st.sidebar.radio("布林通道位階：", ["不篩選", "📉 觸碰/跌破『下軌』", "➖ 站上『中軌』", "📈 突破『上軌』"])

# ==========================================
# 🚀 主畫面：四頁籤設計
# ==========================================
# ⭐ 新增第四個頁籤：晨間作戰會議
tab1, tab2, tab3, tab4 = st.tabs(["📊 第一步：策略選股", "📰 第二步：AI 新聞解讀", "📈 第三步：回測引擎", "🌙 第四步：晨間作戰會議 (夜盤)"])

# ------------------------------------------
# 頁籤 1：選股雷達
# ------------------------------------------
with tab1:
    if st.button("🚀 套用參數，開始掃描！", type="primary"):
        passed_stocks = []
        st.info("🔄 系統啟動中... (第一次約需幾分鐘，之後啟動極速掃描！)")
        all_stocks = get_all_tw_stocks()
        stock_database = random.sample(all_stocks, min(50, len(all_stocks))) if "測試模式" in scan_mode else all_stocks
        progress_bar = st.progress(0)
        start_time = time.time() 
        
        for i, stock in enumerate(stock_database):
            progress_bar.progress((i + 1) / len(stock_database))
            df = get_stock_history(stock, "6mo")
            if df.empty: continue
            
            try:
                df_calc = calculate_indicators(df.copy(), kd_days, macd_fast, macd_slow, bb_days, bb_std)
                latest = df_calc.iloc[-1]
                
                if (latest['Volume'] / 1000) < set_volume: continue
                if not (k_range[0] <= latest['K'] <= k_range[1]): continue
                if not (d_range[0] <= latest['D'] <= d_range[1]): continue
                if filter_macd == "🔴 大於 0 (紅柱)" and (latest['MACD'] <= 0): continue
                if filter_macd == "🟢 小於 0 (綠柱)" and (latest['MACD'] >= 0): continue
                if filter_bb == "📉 觸碰/跌破『下軌』" and (latest['Close'] > latest['Lower_BB']): continue
                if filter_bb == "➖ 站上『中軌』" and (latest['Close'] < latest['Middle_BB']): continue
                if filter_bb == "📈 突破『上軌』" and (latest['Close'] < latest['Upper_BB']): continue
                
                passed_stocks.append({
                    "代號": stock.replace('.TW', '').replace('.TWO', ''),
                    "收盤價": round(latest['Close'], 2),
                    "成交量": int(latest['Volume'] / 1000)
                })
            except:
                pass
                
        time_taken = round(time.time() - start_time, 1)
        st.success(f"✅ 掃描完成！花費時間：{time_taken} 秒")
        if len(passed_stocks) > 0:
            st.dataframe(pd.DataFrame(passed_stocks), use_container_width=True)
        else:
            st.error("😅 沒有股票符合條件，請放寬左側標準。")

# ------------------------------------------
# 頁籤 2：AI 新聞解讀 
# ------------------------------------------
with tab2:
    st.subheader("🤖 召喚 GPT 投資長：透視主力意圖")
    target_stock_news = st.text_input("輸入股票代號搜新聞 (例如: 3231)：", "3231", key="news_input")
    if st.button("🧠 開始 GPT 分析"):
        if not ai_api_key.startswith("sk-"): st.error("⚠️ 請在左側輸入 OpenAI 金鑰！")
        else:
            with st.spinner("🌐 搜集新聞中..."):
                news_data = get_stock_news(target_stock_news)
            if news_data:
                prompt = f"請分析以下台灣股票【{target_stock_news}】的新聞：\n1. 整體情緒(利多/利空)\n2. 背後意圖分析\n3. 實戰建議\n\n{chr(10).join(news_data)}"
                with st.spinner("🤖 分析中..."):
                    try:
                        client = OpenAI(api_key=ai_api_key)
                        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                        st.markdown("### 📝 【GPT 深度分析報告】")
                        st.write(res.
