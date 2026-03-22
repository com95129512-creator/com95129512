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
st.title("📊 專屬 AI 策略選股雷達 & 新聞分析中心 (⚡ 極速版)")

# ==========================================
# 📡 函數區：抓取全台股代號
# ==========================================
@st.cache_data(ttl=86400)
def get_all_tw_stocks():
    stock_list = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
    try:
        url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res_twse = requests.get(url_twse, headers=headers, timeout=10, verify=False).json()
        for item in res_twse:
            if len(item.get('Code', '')) == 4 and item.get('Code', '').isdigit(): 
                stock_list.append(f"{item.get('Code')}.TW")
                
        url_tpex = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        res_tpex = requests.get(url_tpex, headers=headers, timeout=10, verify=False).json()
        for item in res_tpex:
            code = item.get('SecuritiesCompanyCode', item.get('Code', ''))
            if len(code) == 4 and code.isdigit():
                stock_list.append(f"{code}.TWO")
        return stock_list
    except:
        return ["2330.TW", "2317.TW", "3231.TW", "2603.TW", "2308.TW"]

# ==========================================
# ⚡ 核心升級：雲端極速記憶體 (Cache)
# ==========================================
# ttl=43200 代表記憶體會保留 12 小時。一天只要等一次，之後全部秒殺！
@st.cache_data(ttl=43200, show_spinner=False)
def get_stock_history(stock_id):
    try:
        df = yf.Ticker(stock_id).history(period="6mo")
        if not df.empty:
            return df
    except:
        pass
    return pd.DataFrame()

# ==========================================
# 📡 函數區：自動搜尋 Google 財經新聞
# ==========================================
def get_stock_news(stock_name):
    query = urllib.parse.quote(f"{stock_name} 台灣 股票")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        res = requests.get(url, verify=False, timeout=10)
        root = ET.fromstring(res.text)
        news_list = []
        for item in root.findall('.//item')[:5]: 
            title = item.find('title').text
            pubDate = item.find('pubDate').text
            news_list.append(f"日期: {pubDate} | 標題: {title}")
        return news_list
    except Exception as e:
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
# 側邊欄：控制台與 AI 密碼輸入
# ==========================================
st.sidebar.header("🔑 AI 投資長授權 (已切換至 GPT)")
ai_api_key = st.sidebar.text_input("請輸入 OpenAI API 金鑰 (sk-開頭)：", type="password")
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
# 🚀 主畫面：雙頁籤設計
# ==========================================
tab1, tab2 = st.tabs(["📊 第一步：策略選股雷達", "📰 第二步：AI 新聞深度解讀 (GPT版)"])

with tab1:
    if st.button("🚀 套用新參數，開始全網掃描！", type="primary"):
        passed_stocks = []
        st.info("🔄 系統啟動中... (若為今日首次全網掃描，建立資料庫約需 10 分鐘；第二次起將啟動 3 秒極速掃描！)")
        all_stocks = get_all_tw_stocks()
        
        stock_database = random.sample(all_stocks, min(50, len(all_stocks))) if "測試模式" in scan_mode else all_stocks
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # ⚡ 記錄開始時間，讓老闆看這速度有多狂！
        start_time = time.time() 
        
        for i, stock in enumerate(stock_database):
            progress_bar.progress((i + 1) / len(stock_database))
            status_text.text(f"📡 正在分析 {stock} ... ({i+1}/{len(stock_database)})")
            
            try:
                # ⚡ 呼叫快取記憶體，而不是每次都去找 Yahoo
                df = get_stock_history(stock)
                if df.empty: continue
                
                # 複製一份 DataFrame 避免修改到記憶體裡的原始資料
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
                    "成交量(張)": int(latest['Volume'] / 1000)
                })
            except:
                pass
                
        # 結算時間
        end_time = time.time()
        time_taken = round(end_time - start_time, 1)
        
        status_text.text(f"✅ 掃描完成！本次花費時間：{time_taken} 秒")
        if len(passed_stocks) > 0:
            st.dataframe(pd.DataFrame(passed_stocks), use_container_width=True)
            st.success("💡 記下感興趣的代號，前往【第二步：AI 新聞深度解讀】看看主力意圖！")
        else:
            st.error("😅 沒有股票符合條件，請放寬左側標準 (更改參數後再次點擊，系統將瞬間完成掃描！)。")

with tab2:
    st.subheader("🤖 召喚 GPT 投資長：透視新聞背後的主力意圖")
    target_stock = st.text_input("請輸入要分析的股票代號 (例如: 2330, 3231)：", "3231")
    
    if st.button("🧠 搜尋新聞並開始 GPT 分析", type="primary"):
        if not ai_api_key.startswith("sk-"):
            st.error("⚠️ 請確認您在左側輸入的是 OpenAI 的 API 金鑰 (sk- 開頭)！")
        else:
            with st.spinner(f"🌐 正在搜集【{target_stock}】的全網最新新聞..."):
                news_data = get_stock_news(target_stock)
                
            if not news_data:
                st.warning("😅 找不到這檔股票近期的相關新聞。")
            else:
                st.success(f"✅ 成功抓取最新新聞！正在交給 GPT 投資長解讀...")
                with st.expander("📄 點擊查看 AI 讀取的原始新聞標題"):
                    for n in news_data:
                        st.write(n)
                        
                prompt = f"""
                你是專業的台股操盤手與分析師。
                請根據以下關於台灣股票【{target_stock}】的最新新聞標題，為老闆進行深度分析。
                請用專業但口語化的語氣，重點回答以下三個問題：
                1. 新聞整體情緒：目前媒體風向是偏向利多還是利空？
                2. 背後意圖分析：這些新聞背後可能隱藏了什麼市場情緒或大戶意圖？是否有「利多出盡」或「利空淬鍊」的跡象？
                3. 老闆的實戰建議：結合新聞判斷，現在適合順勢追價、逢低佈局，還是先觀望？

                最新新聞列表：
                {chr(10).join(news_data)}
                """
                
                with st.spinner("🤖 GPT 投資長正在瘋狂運算中，請稍候..."):
                    try:
                        client = OpenAI(api_key=ai_api_key)
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": "你是一位頂級的台股量化與質化分析師。"},
                                {"role": "user", "content": prompt}
                            ]
                        )
                        st.markdown("---")
                        st.markdown("### 📝 【GPT 投資長 深度分析報告】")
                        st.write(response.choices[0].message.content)
                        
                    except Exception as e:
                        st.error(f"❌ AI 分析失敗。請確認您的 OpenAI 帳號有綁定信用卡或可用額度。錯誤訊息：{e}")
