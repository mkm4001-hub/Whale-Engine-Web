import streamlit as st
import os
import csv
import time
import random
import io
from datetime import datetime, timedelta
import pytz
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import mplfinance as mpf
from PIL import Image
import google.generativeai as genai
from FinMind.data import DataLoader

# 載入 V25.2 Whale Engines
from whale_engines import *

# ==========================================
# 0. 輔助函式：日K、5分K 抓取與繪圖 (含圖片轉存給 Gemini)
# ==========================================
def get_kline_charts_and_images(stock_id, target_code):
    """
    抓取 2 個月日K 與 當日 5分K
    回傳：(日K Plotly圖, 5分K Plotly圖, 日K PIL圖片, 5分K PIL圖片)
    """
    tz = pytz.timezone('Asia/Taipei')
    ticker = yf.Ticker(target_code)
    
    # 1. 抓取近 2 個月日K (約 60 天)
    df_daily = ticker.history(period="60d", interval="1d")
    if not df_daily.empty and df_daily.index.tz is not None:
        df_daily.index = df_daily.index.tz_convert(tz)
    
    # 2. 抓取當日 5 分K (抓 5d 確保連假後的第一個交易日也能取到完整的一天)
    df_5m = ticker.history(period="5d", interval="5m")
    if not df_5m.empty and df_5m.index.tz is not None:
        df_5m.index = df_5m.index.tz_convert(tz)
        latest_day = df_5m.index[-1].date()
        df_5m = df_5m[df_5m.index.date == latest_day]
        # 篩選台股交易時段 09:00 ~ 13:35
        df_5m = df_5m.between_time('09:00', '13:35')
        
    # --- 繪製網頁互動式圖表 (Plotly) ---
    def make_plotly_candle(df, title):
        if df.empty: return None
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(
            x=df.index.strftime('%Y-%m-%d %H:%M') if '5m' in title else df.index.strftime('%Y-%m-%d'),
            open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name='K線', increasing_line_color='red', decreasing_line_color='green'
        ), row=1, col=1)
        
        # 成交量
        colors = ['red' if row['Close'] >= row['Open'] else 'green' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(
            x=df.index.strftime('%Y-%m-%d %H:%M') if '5m' in title else df.index.strftime('%Y-%m-%d'),
            y=df['Volume'], marker_color=colors, name='成交量'
        ), row=2, col=1)
        
        fig.update_layout(title=title, xaxis_rangeslider_visible=False, height=400, margin=dict(l=20, r=20, t=40, b=20))
        return fig

    fig_daily = make_plotly_candle(df_daily, f"[{stock_id}] 近2個月 日K線圖")
    fig_5m = make_plotly_candle(df_5m, f"[{stock_id}] 當日 5分鐘K線走勢圖 (09:00~13:30)")

    # --- 繪製傳給 Gemini 視覺辨識用的靜態圖片 (mplfinance) ---
    def make_image_for_ai(df):
        if df.empty or len(df) < 5: return None
        df_copy = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        buf = io.BytesIO()
        mpf.plot(df_copy, type='candle', volume=True, style='charles', savefig=dict(fname=buf, dpi=100, bbox_inches='tight'))
        buf.seek(0)
        return Image.open(buf)

    img_daily = make_image_for_ai(df_daily)
    img_5m = make_image_for_ai(df_5m)

    return fig_daily, fig_5m, img_daily, img_5m


def call_gemini_audit(api_key, stock_id, system_info, img_daily, img_5m):
    """
    調用 Gemini 視覺多模態模型交叉審查
    """
    genai.configure(api_key=api_key)
    # 使用兼具速度與視覺分析能力的 Flash 模型
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    你是一位擁有 20 年經驗的台股頂級量化交易專家與資深技術分析操盤手。
    請根據我提供的【Whale Engine 量化診斷報告】以及附加的【近2個月日K圖】、【當日5分K走勢圖】，嚴格評估系統研判是否與實際圖表走勢吻合。

    【個股代號】：{stock_id}
    【量化系統診斷】：
    - 大局狀態：{system_info.get('candidate_status')}
    - 魚體位置：{system_info.get('fish_position')}
    - 機會分數：{system_info.get('opportunity_score')} / 魚頭健康分數：{system_info.get('fish_score')}
    - 實戰防守價：{system_info.get('defensive_price')} (目前價: {system_info.get('current_price')})
    - 撤退與預警風險：{system_info.get('risk_status')}
    - 系統核心策略解讀：{system_info.get('strategy_profile')}

    【請嚴格執行以下三項審查並給出結論】：
    1. 【日K中長線結構審查】：日K線的均線排列、突破型態與成交量，是否支持系統「{system_info.get('fish_position')}」與「{system_info.get('candidate_status')}」的研判？有沒有指標看不出來但肉眼可見的型態破綻？
    2. 【當日5分K短線動能比對】：盤中 09:00 至 13:30 的分時走勢中，是否出現主力當日出貨、量價背離或尾盤突襲拉抬的現象？防守價 {system_info.get('defensive_price')} 是否有實質支撐力道？
    3. 【最終交叉核實結論】：
       - 吻合度評級：(極度吻合 / 基本吻合 / 出現背離 / 嚴重衝突)
       - 實戰操盤提醒：給操盤手一句話最犀利的行動建議。
    """
    
    contents = [prompt]
    if img_daily is not None: contents.append(img_daily)
    if img_5m is not None: contents.append(img_5m)
    
    response = model.generate_content(contents)
    return response.text


# ==========================================
# 1. 查詢紀錄與帳號權限
# ==========================================
def log_query(username, stocks):
    filename = "query_logs.csv"
    file_exists = os.path.isfile(filename)
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["查詢時間", "登入帳號", "查詢股號"])
        writer.writerow([now, username, stocks])

USERS = {
    "chiu": {"password": "pwd", "role": "superuser"}, # 你的專屬最高權限帳號
    "master": {"password": "pwd", "role": "superuser"},
    "admin1": {"password": "pwd", "role": "full"},
    "admin2": {"password": "pwd", "role": "full"},
    "user1": {"password": "123", "role": "simple"},
    "user2": {"password": "123", "role": "simple"}
}

def check_login():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        st.title("🔒 GrandMaster Whale Engine V25.2")
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        if st.button("登入"):
            if username in USERS and USERS[username]["password"] == password:
                st.session_state.authenticated = True
                st.session_state.user = username
                st.session_state.role = USERS[username]["role"]
                st.rerun()
            else:
                st.error("帳號或密碼錯誤！")
        return False
    return True

if not check_login():
    st.stop()

# 側邊欄：使用者資訊與 Gemini API Key 輸入
if st.session_state.role == "superuser":
    role_display = "👑 最高管理者 (含追蹤權限)"
elif st.session_state.role == "full":
    role_display = "🌟 完整版權限"
else:
    role_display = "👁️ 簡易版權限"

st.sidebar.write(f"歡迎回來，**{st.session_state.user}**")
st.sidebar.write(f"當前身分：{role_display}")

st.sidebar.markdown("---")
st.sidebar.write("🤖 **Gemini AI 引擎配置**")
gemini_api_key = st.sidebar.text_input(
    "請輸入 Gemini API Key", 
    type="password", 
    value=st.session_state.get("gemini_key", ""),
    help="用於啟動 K線視覺交叉審查模組"
)
if gemini_api_key:
    st.session_state["gemini_key"] = gemini_api_key

if st.session_state.role == "superuser":
    st.sidebar.markdown("---")
    st.sidebar.write("🛠️ **系統管理專區**")
    if os.path.exists("query_logs.csv"):
        with open("query_logs.csv", "rb") as f:
            st.sidebar.download_button(
                label="📥 下載所有查詢紀錄 (CSV)",
                data=f,
                file_name=f"Query_Logs_{datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

st.sidebar.markdown("---")
if st.sidebar.button("登出"):
    st.session_state.authenticated = False
    st.rerun()

# ==========================================
# 2. 網頁版主介面與執行邏輯
# ==========================================
st.title("🐋 GrandMaster Whale Engine V25.2 PRO")
st.info("💡 系統已啟用 FinMind 免費版模式，無需輸入 Token。")

mode_choice = st.radio("選擇模式", ["盤後大局透視 (包含集保大戶X光掃描)", "盤中極速模式 (純技術面)"])
stock_input = st.text_input("請輸入股票代號 (多檔請用空白分隔，例如: 2330 3034)")

if st.button("🚀 開始分析"):
    if not stock_input:
        st.warning("請輸入至少一檔股票代號！")
    else:
        log_query(st.session_state.user, stock_input)
        current_mode = 'intraday' if '盤中' in mode_choice else 'after_market'
        stock_list = list(dict.fromkeys([s.strip() for s in stock_input.split() if s.strip()]))
        
        st.info("系統運算中，請稍候...")
        progress_text = "批次掃描進度"
        my_bar = st.progress(0, text=progress_text)
        total_stocks = len(stock_list)
        
        try:
            dl = DataLoader()
            data_engine = DataEngine(dataloader=dl)
            fish_engine = FishScoreEngine()
            retreat_engine = RetreatScoreEngine()
            fundamental_engine = FundamentalEngine()
            position_engine = FishPositionEngine()
            endurance_engine = WhaleEnduranceEngine()
            warning_engine = EarlyWarningEngine()
            defense_engine = SmartMoneyDefenseEngine()
            chip_engine = ChipRadarEngine()
            xray_engine = ChipXRayEngine()
            
            for idx, stock_id in enumerate(stock_list):
                st.subheader(f"📊 [{stock_id}] 實戰分析報告 (V25.2)")
                
                try:
                    df, target_code, data_quality, rev_df, tdcc_df = data_engine.load_stock(stock_id, current_mode)
                    mkt = data_engine.load_market(target_code, data_quality['latest_price_date'])
                    data = data_engine.prepare_indicators(df, mkt)
                    data['data_quality'] = data_quality
                    
                    now = datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y-%m-%d")
                    fundamental = fundamental_engine.calculate(rev_df, now)
                    fish = fish_engine.calculate(data)
                    retreat = retreat_engine.calculate(data)
                    warning = warning_engine.calculate(data)
                    endurance = endurance_engine.calculate(data)
                    defense = defense_engine.calculate(data, market_data={"df": mkt})
                    position = position_engine.calculate(data, fish, retreat, warning, endurance, defense, fundamental)
                    chip = chip_engine.calculate(data, current_mode)
                    chip_xray = xray_engine.calculate(tdcc_df, position)
                    
                    # 抓取日K與5分K圖表
                    fig_daily, fig_5m, img_daily, img_5m = get_kline_charts_and_images(stock_id, target_code)

                    # --------- 戰情儀表板展示 ---------
                    col1, col2, col3, col4, col5 = st.columns(5)
                    col1.metric("機會分數", position["opportunity_score"])
                    col2.metric("魚頭分數", fish["fish_score"])
                    col3.metric("健康等級", fish["health_grade"])
                    col4.metric("營收 YoY", f"{fundamental['yoy']}%")
                    col5.metric("營收 MoM", f"{fundamental['mom']}%")
                    
                    st.markdown("---")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**🎯 大局狀態：** {position['candidate_status']}")
                        st.markdown(f"**🐟 魚體位置：** {position['fish_position']}")
                        st.markdown(f"**🛡️ 型態防禦：** {defense['defense_status']}")
                        st.markdown(f"**🔋 續航狀態：** {endurance['endurance_status']}")
                    with c2:
                        st.markdown(f"**🏃 綜合撤退風險：** {retreat['risk_status']}")
                        st.markdown(f"**⚠️ 綜合預警狀態：** {warning['warning_status']}")
                        st.markdown(f"**🏢 基本面標籤：** {fundamental['fund_label']}")
                        st.markdown(f"**💡 實戰評估(規則式)：** {position.get('strategy_profile', '無')}")
                        
                    st.info(f"**💰 目前價(Raw)：** `{position['current_price']}` ｜ **🛡️ 實戰防守價(ATR)：** `{position['defensive_price']}` ｜ **⚖️ 60日加權均價：** `{position['vwap60']}`")
                    
                    # 依權限顯示分頁
                    if st.session_state.role in ["superuser", "full"]:
                        tab1, tab2, tab3, tab4, tab5 = st.tabs([
                            "📈 K線圖表專區 (日K/5分K)", 
                            "🤖 Gemini 趨勢吻合度審查", 
                            "核心與基本面", 
                            "防禦與籌碼雷達", 
                            "體檢與預警明細"
                        ])
                        
                        # --- Tab 1: K線圖表專區 ---
                        with tab1:
                            if fig_daily: st.plotly_chart(fig_daily, use_container_width=True)
                            if fig_5m: st.plotly_chart(fig_5m, use_container_width=True)
                            else: st.caption("目前無當日盤中分時資料。")
                            
                        # --- Tab 2: Gemini 智能交叉審查 ---
                        with tab2:
                            st.write("### 🤖 Gemini 多模態趨勢吻合度審查")
                            if not gemini_api_key:
                                st.warning("⚠️ 請先在左側側邊欄輸入你的【Gemini API Key】即可啟動此模組！")
                            else:
                                with st.spinner("Gemini 正在讀取 2 張 K 線圖與量化數據，交叉比對中..."):
                                    system_summary = {
                                        "candidate_status": position['candidate_status'],
                                        "fish_position": position['fish_position'],
                                        "opportunity_score": position['opportunity_score'],
                                        "fish_score": fish['fish_score'],
                                        "defensive_price": position['defensive_price'],
                                        "current_price": position['current_price'],
                                        "risk_status": f"撤退[{retreat['risk_status']}] | 預警[{warning['warning_status']}]",
                                        "strategy_profile": position.get('strategy_profile', '')
                                    }
                                    try:
                                        gemini_audit_result = call_gemini_audit(
                                            gemini_api_key, stock_id, system_summary, img_daily, img_5m
                                        )
                                        st.markdown(gemini_audit_result)
                                    except Exception as ai_err:
                                        st.error(f"Gemini 連線或分析失敗: {str(ai_err)}")

                        with tab3:
                            st.write(f"**保守目標區：** {position.get('target_low', '-')} ~ {position.get('target_high', '-')}")
                            st.write(f"**剩餘空間：** +{position.get('upside_low', '-')} ~ +{position.get('upside_high', '-')}")
                            st.markdown("**【系統解讀】**")
                            st.info(position.get('position_comment', '無'))
                            
                        with tab4:
                            st.write(f"**【籌碼續航力】當前狀態：** {endurance['endurance_status']}")
                            for msg in endurance.get('endurance_messages', []): st.caption(f"- {msg}")
                            st.write(f"**【型態防禦雷達】當前狀態：** {defense['defense_status']}")
                            for sig in defense.get('defense_signals', []): st.caption(f"- {sig}")
                            st.write(f"**【盤後法人透視】當前狀態：** {chip.get('chip_status', '無資料')}")
                            for msg in chip.get('chip_messages', []): st.caption(f"- {msg}")

                        with tab5:
                            col_a, col_b = st.columns(2)
                            with col_a:
                                st.write("**【魚頭體檢】**")
                                for item, status in fish["health_checks"]:
                                    mark = "✅" if status is True else "❌" if status is False else "❓"
                                    st.caption(f"{mark} {item}")
                            with col_b:
                                st.write("**【撤退檢查】**")
                                for item, status in retreat["retreat_checks"]:
                                    mark = "❌" if status is True else "✅" if status is False else "❓"
                                    st.caption(f"{mark} {item}")
                                st.write("**【高檔預警】**")
                                for item, status in warning["warning_checks"]:
                                    mark = "❌" if status is True else "✅" if status is False else "❓"
                                    st.caption(f"{mark} {item}")
                    else:
                        # 簡易版
                        st.markdown(f"**系統解讀：** {position.get('position_comment', '無')}")
                        st.markdown(f"**防守價：** {position['defensive_price']}")
                        st.markdown(f"**綜合風險狀態：** 撤退 [{retreat['risk_status']}] | 預警 [{warning['warning_status']}]")
                        
                    st.divider()
                    
                    my_bar.progress((idx + 1) / total_stocks, text=f"{progress_text} (正在處理: {stock_id}...)")
                    if idx < total_stocks - 1:
                        time.sleep(random.uniform(1.5, 3.0))
                        
                except Exception as e:
                    st.error(f"分析 {stock_id} 時發生錯誤: {str(e)}")
                    
            my_bar.progress(1.0, text="批次掃描完成！")
            st.success("全部分析完成！")
        except Exception as e:
            st.error(f"系統啟動失敗。錯誤訊息: {str(e)}")
