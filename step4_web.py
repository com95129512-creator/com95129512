import streamlit as st
import yfinance as yf
import pandas as pd
import time, requests, random, urllib3, urllib.parse, json, gspread
import xml.etree.ElementTree as ET
from openai import OpenAI 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="老闆的專屬選股雷達", layout="wide")
st.title("📊 專屬 AI 策略選股雷達 & 庫存戰情室 (🚀 突破封鎖版)")

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
# 📡 核心函數區 (⭐ 跨國跳板破甲機制)
# ==========================================
@st.cache_data(ttl=86400)
def get_all_tw_stocks():
    stock_list = []
    fallback_list = ["2330.TW", "2317.TW", "2454.TW", "2382.TW", "2308.TW", "2881.TW", "2882.TW", "2891.TW", "2002.TW", "1216.TW", "2886.TW", "2884.TW", "2885.TW", "2892.TW", "2603.TW", "2880.TW", "2887.TW", "2883.TW", "5880.TW", "2890.TW", "2303.TW", "2609.TW", "2615.TW", "2412.TW", "3045.TW", "4904.TW", "2912.TW", "2357.TW", "2379.TW", "2301.TW", "2324.TW", "2353.TW", "2356.TW", "3231.TW", "2352.TW", "2377.TW", "2395.TW", "2408.TW", "2409.TW", "3481.TW", "2344.TW", "2404.TW", "2337.TW", "2338.TW", "2313.TW", "2362.TW", "2371.TW", "2385.TW", "2392.TW", "2449.TW"]
    
    try:
        twse_url = "https://api.allorigins.win/raw?url=" + urllib.parse.quote("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
        tpex_url = "https://api.allorigins.win/raw?url=" + urllib.parse.quote("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes")
        
        res_twse = requests.get(twse_url, timeout=15)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                if len(item.get('Code', '')) == 4 and item.get('Code', '').isdigit(): stock_list.append(f"{item.get('Code')}.TW")
                
        res_tpex = requests.get(tpex_url, timeout=15)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                code = item.get('SecuritiesCompanyCode', item.get('Code', ''))
                if len(code) == 4 and code.isdigit(): stock_list.append(f"{code}.TWO")
        
        if len(stock_list) > 1000: return stock_list
        else: return fallback_list
    except:
        return fallback_list

@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_history(stock_id, period="6mo"):
    for _ in range(2): 
        try:
            df = yf.Ticker(stock_id).history(period=period)
            if not df.empty and len(df) >= 30: return df
        except:
            time.sleep(random.uniform(0.1, 0.3))
    raise Exception("Fetch failed")

@st.cache_data(ttl=3600, show_spinner=False)
def get_overnight_market_data():
    tickers = {'台積電 ADR': 'TSM', '費城半導體': '^SOX', '納斯達克': '^IXIC', '道瓊工業': '^DJI'}
    results = {}
    for name, ticker in tickers.items():
        try:
            df = yf.Ticker(ticker).history(period="5d")
            if len(df) >= 2:
                last_close, prev_close = df['Close'].iloc[-1], df['Close'].iloc[-2]
                results[name] = {"收盤價": round(last_close, 2), "漲跌幅": round(((last_close - prev_close)/prev_close)*100, 2)}
        except: pass
    return results

def get_stock_news(stock_name, limit=5):
    query = urllib.parse.quote(f"{stock_name} 台灣 股票")
    try:
        res = requests.get(f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", verify=False, timeout=10)
        news_list = []
        for item in ET.fromstring(res.text).findall('.//item')[:limit]: 
            news_list.append(f"[{stock_name}] 日期: {item.find('pubDate').text} | 標題: {item.find('title').text}")
        return news_list
    except: return []

def calculate_indicators(df, kd_days, macd_fast, macd_slow, bb_days, bb_std):
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
ai_api_key = st.sidebar.text_input("輸入 OpenAI 金鑰 (sk-)：", type="password")
st.sidebar.markdown("---")

st.sidebar.header("🎯 掃描範圍")
# ⭐ 新增：500檔 中量級掃描選項
scan_mode = st.sidebar.radio("雷達強度：", ["🧪 快速測試 (50檔)", "⚡ 中量掃描 (500檔)", "🔥 火力全開 (1700檔)"])
st.sidebar.markdown("---")

st.sidebar.header("⚙️ 篩選條件開關")
set_volume = 5000; kd_val = 20; kd_days = 9; macd_fast = 12; macd_slow = 26; bb_days = 20; bb_std = 2.0

use_vol = st.sidebar.checkbox("1. 成交量過濾", value=True)
if use_vol: set_volume = st.sidebar.number_input("最低成交量 (張)", min_value=0, value=5000)

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

with tab1:
    all_stocks = get_all_tw_stocks()
    if len(all_stocks) > 1000:
        st.info(f"🟢 跨國跳板連線成功：已載入 {len(all_stocks)} 檔台股清單。")
    else:
        st.warning(f"🟡 跨國跳板受阻：已自動啟用【精選 50 檔中大型權值股】備用模式。")

    col_run, col_clear = st.columns([3, 1])
    with col_run: run_btn = st.button("🚀 啟動掃描 (每次自動清洗舊記憶)", type="primary", use_container_width=True)
    with col_clear:
        if st.button("🔄 手動清除快取", use_container_width=True):
            st.cache_data.clear()
            st.success("記憶體已清空！")

    if run_btn:
        st.cache_data.clear() 
        passed_stocks = []
        failed_count = 0 
        
        # ⭐ 新增：判斷老闆選擇的掃描數量
        if "50檔" in scan_mode:
            sample_size = 50
        elif "500檔" in scan_mode:
            sample_size = 500
        else:
            sample_size = len(all_stocks)
            
        stock_database = random.sample(all_stocks, min(sample_size, len(all_stocks)))
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, stock in enumerate(stock_database):
            progress_bar.progress((i + 1) / len(stock_database))
            status_text.text(f"📡 正在向 Yahoo 索取 {stock} 報價 ({i+1}/{len(stock_database)})...")
            
            try:
                df = get_stock_history(stock, "6mo")
            except:
                failed_count += 1
                continue
                
            try:
                latest = calculate_indicators(df.copy(), kd_days, macd_fast, macd_slow, bb_days, bb_std).iloc[-1]
                if use_vol and (latest['Volume'] / 1000) < set_volume: continue
                if use_kd_below and (latest['K'] > kd_val or latest['D'] > kd_val): continue
                if use_macd_below and latest['MACD'] >= 0: continue
                if use_bb_below_mid and latest['Close'] >= latest['Middle_BB']: continue
                passed_stocks.append({"代號": stock.replace('.TW', '').replace('.TWO', ''), "收盤價": round(latest['Close'], 2)})
            except: pass
        
        status_text.text(f"✅ 掃描完成！")
        
        st.markdown("### 📝 本次掃描診斷報告")
        col_res1, col_res2, col_res3 = st.columns(3)
        col_res1.metric("🎯 符合條件檔數", f"{len(passed_stocks)} 檔")
        col_res2.metric("🟢 成功取得報價", f"{len(stock_database) - failed_count} 檔")
        col_res3.metric("🔴 遭 Yahoo 阻擋", f"{failed_count} 檔")
        
        if passed_stocks: 
            st.dataframe(pd.DataFrame(passed_stocks), use_container_width=True)
        else: 
            st.warning("😅 目前沒有股票符合條件。這可能是條件太嚴苛，或是成功取得報價的股票太少。")

with tab2:
    st.subheader("🤖 個股深度分析")
    target_stock_news = st.text_input("輸入股票代號：", "3231", key="news_input")
    if st.button("🧠 開始分析"):
        if not ai_api_key.startswith("sk-"): st.error("請輸入金鑰！")
        else:
            with st.spinner("搜集新聞中..."): news_data = get_stock_news(target_stock_news)
            if news_data:
                try:
                    res = OpenAI(api_key=ai_api_key).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": f"分析新聞：\n{chr(10).join(news_data)}"}])
                    st.write(res.choices[0].message.content)
                except: st.error("分析失敗")
            else: st.warning("找不到新聞。")

with tab3:
    st.subheader("📈 真實數據回測")
    target_stock_bt = st.text_input("輸入代號回測：", "2330", key="bt_input")
    if st.button("⏳ 啟動回測"):
        with st.spinner("調閱 1 年資料..."):
            try:
                st.cache_data.clear()
                df_bt = get_stock_history(f"{target_stock_bt}.TW" if len(target_stock_bt) == 4 else target_stock_bt, "1y")
                df_bt = calculate_indicators(df_bt.copy(), kd_days, macd_fast, macd_slow, bb_days, bb_std).dropna()
                trades, in_position, buy_price = [], False, 0
                for date, row in df_bt.iterrows():
                    if not in_position:
                        v_ok = (row['Volume']/1000) >= set_volume if use_vol else True
                        k_ok = (row['K'] <= kd_val and row['D'] <= kd_val) if use_kd_below else True
                        m_ok = row['MACD'] < 0 if use_macd_below else True
                        b_ok = row['Close'] < row['Middle_BB'] if use_bb_below_mid else True
                        if v_ok and k_ok and m_ok and b_ok:
                            in_position, buy_price, buy_date = True, row['Close'], date.strftime('%Y-%m-%d')
                    else:
                        if row['Close'] >= row['Middle_BB'] or row['Close'] <= buy_price * 0.9: 
                            trades.append({'進場': buy_date, '出場': date.strftime('%Y-%m-%d'), '報酬率': f"{((row['Close'] - buy_price)/buy_price)*100:.2f}%"})
                            in_position = False
                if trades: st.dataframe(pd.DataFrame(trades))
                else: st.warning("從未符合條件。")
            except: st.error("抓不到資料。")

with tab4:
    st.subheader("🌅 晨間作戰分析")
    if st.button("☕ 生成報告"):
        if not ai_api_key.startswith("sk-"): st.error("請輸入金鑰！")
        else:
            with st.spinner("連線中..."): ov_data = get_overnight_market_data()
            if ov_data:
                st.write(ov_data)
                try:
                    res = OpenAI(api_key=ai_api_key).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": f"根據數據預測台股開盤：\n{ov_data}"}])
                    st.write(res.choices[0].message.content)
                except: pass

with tab5:
    st.subheader("💼 我的庫存股")
    if worksheet is None: st.error("⚠️ 雲端連線失敗！")
    col1, col2 = st.columns(2)
    with col1:
        new_stock = st.text_input("➕ 新增股票")
        if st.button("加入") and new_stock and new_stock not in st.session_state.my_portfolio:
            if worksheet: worksheet.append_row([new_stock])
            st.session_state.my_portfolio.append(new_stock)
            st.rerun()
    with col2:
        del_stock = st.text_input("🗑️ 刪除股票")
        if st.button("移除") and del_stock in st.session_state.my_portfolio:
            if worksheet:
                cell = worksheet.find(del_stock)
                if cell: worksheet.delete_rows(cell.row)
            st.session_state.my_portfolio.remove(del_stock)
            st.rerun()
            
    if st.session_state.my_portfolio:
        portfolio_data = []
        for stock in st.session_state.my_portfolio:
            try:
                df = get_stock_history(f"{stock}.TW" if len(stock) == 4 else stock, "5d")
                last_price, prev_price = df['Close'].iloc[-1], df['Close'].iloc[-2]
                portfolio_data.append({"代號": stock, "最新收盤價": round(last_price, 2), "漲跌幅(%)": round(((last_price - prev_price)/prev_price)*100, 2)})
            except: pass
        if portfolio_data: st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True)
        
        if st.button("🔥 一鍵診斷"):
            if not ai_api_key.startswith("sk-"): st.error("請輸入金鑰！")
            else:
                all_news = []
                for stock in st.session_state.my_portfolio: all_news.extend(get_stock_news(stock, limit=2))
                try:
                    res = OpenAI(api_key=ai_api_key).chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": f"庫存體檢：\n{chr(10).join(all_news)}"}])
                    st.write(res.choices[0].message.content)
                except: st.error("分析失敗")
