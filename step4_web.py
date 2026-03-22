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
# 📡 函數區：抓取名單與歷史資料 (極速快取)
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
    # 👇 這裡就是剛剛斷尾的地方，已經幫您修復補上 .mean() 了！
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
# 🚀 主畫面：三頁籤設計
# ==========================================
tab1, tab2, tab3 = st.tabs(["📊 第一步：策略選股雷達", "📰 第二步：AI 新聞深度解讀", "📈 第三步：歷史勝率回測引擎"])

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
                        st.write(res.choices[0].message.content)
                    except Exception as e:
                        st.error(f"❌ 分析失敗：{e}")
            else:
                st.warning("找不到新聞。")

# ------------------------------------------
# 頁籤 3：歷史勝率回測引擎 (⭐ 近 1 年實戰版)
# ------------------------------------------
with tab3:
    st.subheader("⏱️ 策略時光機：近 1 年真實數據回測")
    st.markdown("""
    **【回測邏輯說明】**
    * 🎯 **進場：** 嚴格遵守您左側設定的所有參數（KD、MACD、布林通道）。
    * 🟢 **停利 (均值回歸)：** 買進後，當股價反彈碰到「布林中軌」即獲利了結。
    * 🔴 **停損 (保護本金)：** 買進後，若帳面虧損達 10%，立刻停損出場。
    """)
    
    target_stock_bt = st.text_input("輸入要回測的股票代號 (例如: 2330)：", "2330", key="bt_input")
    
    if st.button("⏳ 啟動 1 年歷史回測", type="primary"):
        with st.spinner(f"正在向歷史資料庫調閱 {target_stock_bt} 過去 1 年的每一筆交易..."):
            stock_id = f"{target_stock_bt}.TW" if len(target_stock_bt) == 4 else target_stock_bt
            df_bt = get_stock_history(stock_id, period="1y")
            
            if df_bt.empty:
                st.error("⚠️ 抓不到這檔股票的資料，可能是代號錯誤或上市未滿 1 年。")
            else:
                df_bt = calculate_indicators(df_bt.copy(), kd_days, macd_fast, macd_slow, bb_days, bb_std)
                df_bt = df_bt.dropna() 
                
                trades = []
                in_position = False
                buy_price = 0
                buy_date = None
                
                for date, row in df_bt.iterrows():
                    if not in_position:
                        vol_ok = (row['Volume'] / 1000) >= set_volume
                        k_ok = k_range[0] <= row['K'] <= k_range[1]
                        d_ok = d_range[0] <= row['D'] <= d_range[1]
                        
                        macd_ok = True
                        if filter_macd == "🔴 大於 0 (紅柱)": macd_ok = row['MACD'] > 0
                        elif filter_macd == "🟢 小於 0 (綠柱)": macd_ok = row['MACD'] < 0
                        
                        bb_ok = True
                        if filter_bb == "📉 觸碰/跌破『下軌』": bb_ok = row['Close'] <= row['Lower_BB']
                        elif filter_bb == "➖ 站上『中軌』": bb_ok = row['Close'] >= row['Middle_BB']
                        elif filter_bb == "📈 突破『上軌』": bb_ok = row['Close'] >= row['Upper_BB']
                        
                        if vol_ok and k_ok and d_ok and macd_ok and bb_ok:
                            in_position = True
                            buy_price = row['Close']
                            buy_date = date.strftime('%Y-%m-%d')
                    else:
                        if row['Close'] >= row['Middle_BB']: 
                            ret = (row['Close'] - buy_price) / buy_price
                            trades.append({'進場日': buy_date, '出場日': date.strftime('%Y-%m-%d'), '進場價': round(buy_price, 2), '出場價': round(row['Close'], 2), '報酬率': ret, '結果': '🟢 停利'})
                            in_position = False
                        elif row['Close'] <= buy_price * 0.9: 
                            ret = (row['Close'] - buy_price) / buy_price
                            trades.append({'進場日': buy_date, '出場日': date.strftime('%Y-%m-%d'), '進場價': round(buy_price, 2), '出場價': round(row['Close'], 2), '報酬率': ret, '結果': '🔴 停損'})
                            in_position = False
                
                if len(trades) > 0:
                    trades_df = pd.DataFrame(trades)
                    total_trades = len(trades_df)
                    winning_trades = len(trades_df[trades_df['報酬率'] > 0])
                    win_rate = (winning_trades / total_trades) * 100
                    avg_return = trades_df['報酬率'].mean() * 100
                    
                    st.success("✅ 回測計算完成！以下是您專屬策略的真實戰報：")
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("🎯 歷史真實勝率", f"{win_rate:.1f} %")
                    col2.metric("💰 每次平均報酬率", f"{avg_return:.2f} %")
                    col3.metric("🔄 過去 1 年觸發次數", f"{total_trades} 次")
                    
                    st.markdown("#### 📜 詳細交易對帳單")
                    trades_df['報酬率'] = trades_df['報酬率'].apply(lambda x: f"{x*100:.2f}%")
                    st.dataframe(trades_df, use_container_width=True)
                else:
                    st.warning("😅 在過去 1 年內，這檔股票【從來沒有】同時符合您左側設定的所有嚴格條件。建議您放寬左側參數再試一次！")
