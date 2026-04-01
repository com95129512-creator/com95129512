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
import gspread # 🆕 新增：用來控制 Google 試算表的套件
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="老闆的專屬選股雷達", layout="wide")
st.title("📊 專屬 AI 策略選股雷達 & 庫存戰情室 (🚀 完全體)")

# ==========================================
# 💾 雲端資料庫連線 (Google Sheets)
# ==========================================
@st.cache_resource
def init_db():
    try:
        # 嘗試從 Streamlit 保險箱拿出鑰匙
        creds_dict = json.loads(st.secrets["google_credentials"])
        gc = gspread.service_account_from_dict(creds_dict)
        # 打開老闆的試算表
        sh = gc.open("My_Stock_Portfolio")
        return sh.sheet1
    except Exception as e:
        # 如果保險箱沒設好，或是找不到表單，就回傳 None
        return None

worksheet = init_db()

# 初始化庫存名單
if 'my_portfolio' not in st.session_state:
    if worksheet:
        try:
            # 從試算表的第一欄抓取所有資料
            records = worksheet.col_values(1)
            # 過濾掉標題列 'Stock_ID' 和空白行
            st.session_state.my_portfolio = [r for r in records if r != 'Stock_ID' and r.strip() != '']
        except:
            st.session_state.my_portfolio = []
    else:
        st.session_state.my_portfolio = [] # 資料庫連線失敗時的備用空名單

# ==========================================
# 📡 函數區
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
                pct_change = ((last_close - prev_close) / prev_close) * 100
                results[name] = {"收盤價": round(last_close, 2), "漲跌幅": round(pct_change, 2)}
        except:
            pass
    return results

def get_stock_news(stock_name, limit=5):
    query = urllib.parse.quote(f"{stock_name} 台灣 股票")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        res = requests.get(url, verify=False, timeout=10)
        root = ET.fromstring(res.text)
        news_list = []
        for item in root.findall('.//item')[:limit]: 
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

st.sidebar.header("⚙️ 參數設定區")
set_volume = st.sidebar.number_input("最低成交量 (張)", min_value=0, value=5000, step=500)
kd_days = st.sidebar.number_input("KD 天數", min_value=3, value=9)
k_range = st.sidebar.slider("K 值範圍：", 0, 100, (0, 100))
d_range = st.sidebar.slider("D 值範圍：", 0, 100, (0, 100))
macd_fast = st.sidebar.number_input("MACD 快線", value=12)
macd_slow = st.sidebar.number_input("MACD 慢線", value=26)
filter_macd = st.sidebar.radio("MACD：", ["不篩選", "🔴 大於 0", "🟢 小於 0"])
bb_days = st.sidebar.number_input("布林天數", value=20)
bb_std = st.sidebar.number_input("標準差倍數", value=3.0, step=0.1)
filter_bb = st.sidebar.radio("布林位階：", ["不篩選", "📉 跌破下軌", "➖ 站上中軌", "📈 突破上軌"])

# ==========================================
# 🚀 主畫面：五頁籤設計
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 雷達掃描", "📰 個股新聞", "📈 歷史回測", "🌙 晨間會議", "💼 我的庫存股"])

with tab1:
    if st.button("🚀 開始掃描全市場！", type="primary"):
        passed_stocks = []
        all_stocks = get_all_tw_stocks()
        stock_database = random.sample(all_stocks, min(50, len(all_stocks))) if "測試模式" in scan_mode else all_stocks
        progress_bar = st.progress(0)
        
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
                if filter_macd == "🔴 大於 0" and (latest['MACD'] <= 0): continue
                if filter_macd == "🟢 小於 0" and (latest['MACD'] >= 0): continue
                if filter_bb == "📉 跌破下軌" and (latest['Close'] > latest['Lower_BB']): continue
                if filter_bb == "➖ 站上中軌" and (latest['Close'] < latest['Middle_BB']): continue
                if filter_bb == "📈 突破上軌" and (latest['Close'] < latest['Upper_BB']): continue
                passed_stocks.append({"代號": stock.replace('.TW', '').replace('.TWO', ''), "收盤價": round(latest['Close'], 2)})
            except:
                pass
        
        st.success("✅ 掃描完成！")
        if passed_stocks:
            st.dataframe(pd.DataFrame(passed_stocks), use_container_width=True)
        else:
            st.error("沒有股票符合條件。")

with tab2:
    st.subheader("🤖 個股深度分析")
    target_stock_news = st.text_input("輸入股票代號搜新聞：", "3231", key="news_input")
    if st.button("🧠 開始分析"):
        if not ai_api_key.startswith("sk-"): st.error("請輸入 OpenAI 金鑰！")
        else:
            with st.spinner("🌐 搜集新聞中..."):
                news_data = get_stock_news(target_stock_news)
            if news_data:
                prompt = f"請分析以下【{target_stock_news}】的新聞：\n1. 媒體情緒\n2. 主力意圖\n3. 實戰建議\n\n{chr(10).join(news_data)}"
                try:
                    client = OpenAI(api_key=ai_api_key)
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                    st.write(res.choices[0].message.content)
                except Exception as e:
                    st.error(f"分析失敗：{e}")
            else:
                st.warning("找不到新聞。")

with tab3:
    st.subheader("⏱️ 1 年真實數據回測")
    target_stock_bt = st.text_input("輸入要回測的代號：", "2330", key="bt_input")
    if st.button("⏳ 啟動回測", type="primary"):
        with st.spinner("調閱資料中..."):
            stock_id = f"{target_stock_bt}.TW" if len(target_stock_bt) == 4 else target_stock_bt
            df_bt = get_stock_history(stock_id, period="1y")
            if df_bt.empty: st.error("抓不到資料。")
            else:
                df_bt = calculate_indicators(df_bt.copy(), kd_days, macd_fast, macd_slow, bb_days, bb_std).dropna()
                trades, in_position, buy_price = [], False, 0
                for date, row in df_bt.iterrows():
                    if not in_position:
                        if (row['Volume']/1000) >= set_volume and (k_range[0] <= row['K'] <= k_range[1]) and (d_range[0] <= row['D'] <= d_range[1]):
                            in_position, buy_price, buy_date = True, row['Close'], date.strftime('%Y-%m-%d')
                    else:
                        if row['Close'] >= row['Middle_BB'] or row['Close'] <= buy_price * 0.9: 
                            trades.append({'進場': buy_date, '出場': date.strftime('%Y-%m-%d'), '報酬率': (row['Close'] - buy_price) / buy_price})
                            in_position = False
                if trades:
                    st.success(f"回測完成！共觸發 {len(trades)} 次。")
                    st.dataframe(pd.DataFrame(trades))
                else:
                    st.warning("從未符合進場條件。")

with tab4:
    st.subheader("🌅 夜盤與美股影響分析")
    if st.button("☕ 生成作戰報告", type="primary"):
        if not ai_api_key.startswith("sk-"): st.error("請輸入金鑰！")
        else:
            with st.spinner("連線華爾街中..."):
                ov_data = get_overnight_market_data()
            if ov_data:
                st.write(ov_data)
                prompt = f"根據昨夜美股數據預測今日台股走勢及抄底建議：\n{ov_data}"
                try:
                    client = OpenAI(api_key=ai_api_key)
                    res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                    st.write(res.choices[0].message.content)
                except Exception as e:
                    st.error(e)

# ------------------------------------------
# ⭐ 5. 永久記憶的庫存戰情室
# ------------------------------------------
with tab5:
    st.subheader("💼 專屬庫存股 (已同步至 Google 雲端)")
    if worksheet is None:
        st.error("⚠️ 雲端資料庫連線失敗！請確認 Streamlit Secrets 設定正確，且試算表已共用給機器人。")
    
    col1, col2 = st.columns(2)
    with col1:
        new_stock = st.text_input("➕ 新增股票 (輸入代號)")
        if st.button("加入名單"):
            if new_stock and new_stock not in st.session_state.my_portfolio:
                if worksheet:
                    try:
                        worksheet.append_row([new_stock]) # 寫入雲端
                    except Exception as e:
                        st.error(f"寫入雲端失敗: {e}")
                st.session_state.my_portfolio.append(new_stock)
                st.success(f"✅ {new_stock} 已存入雲端！")
                st.rerun()
                
    with col2:
        del_stock = st.text_input("🗑️ 刪除股票 (輸入代號)")
        if st.button("移出名單"):
            if del_stock in st.session_state.my_portfolio:
                if worksheet:
                    try:
                        cell = worksheet.find(del_stock) # 在雲端尋找這檔股票
                        if cell:
                            worksheet.delete_rows(cell.row) # 從雲端刪除該列
                    except Exception as e:
                        st.error(f"刪除雲端資料失敗: {e}")
                st.session_state.my_portfolio.remove(del_stock)
                st.warning(f"❌ {del_stock} 已移出名單！")
                st.rerun()

    st.markdown("---")
    
    if st.session_state.my_portfolio:
        st.markdown("### 📋 目前追蹤清單即時報價")
        portfolio_data = []
        for stock in st.session_state.my_portfolio:
            stock_id = f"{stock}.TW" if len(stock) == 4 else stock
            df = get_stock_history(stock_id, "5d")
            if not df.empty and len(df) >= 2:
                last_price = df['Close'].iloc[-1]
                prev_price = df['Close'].iloc[-2]
                change = ((last_price - prev_price) / prev_price) * 100
                portfolio_data.append({"股票代號": stock, "最新收盤價": round(last_price, 2), "單日漲跌幅(%)": round(change, 2)})
        
        if portfolio_data:
            st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True)
            
        st.markdown("### 🏥 庫存股 AI 總體檢")
        if st.button("🔥 一鍵獲取庫存 AI 診斷報告", type="primary"):
            if not ai_api_key.startswith("sk-"): 
                st.error("⚠️ 老闆，請先在左側輸入 OpenAI 金鑰！")
            else:
                with st.spinner("🌐 正在為您搜集所有庫存股的最新新聞..."):
                    all_news = []
                    for stock in st.session_state.my_portfolio:
                        stock_news = get_stock_news(stock, limit=3) 
                        all_news.extend(stock_news)
                    
                if not all_news:
                    st.warning("😅 找不到新聞。")
                else:
                    st.success("✅ 情報搜集完畢！正在交給 GPT 分析...")
                    combined_news_text = "\n".join(all_news)
                    prompt = f"你是頂尖財富顧問。以下是庫存股清單與新聞：\n{combined_news_text}\n請寫一份庫存總體檢報告：1.個股狀態掃描 2.風險與機會 3.操作建議(續抱/加碼/減碼)"
                    try:
                        client = OpenAI(api_key=ai_api_key)
                        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                        st.markdown("---")
                        st.write(res.choices[0].message.content)
                    except Exception as e:
                        st.error(f"❌ 分析失敗：{e}")
    else:
        st.info("💡 您的雲端庫存目前是空的，請從上方新增。")
