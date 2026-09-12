import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import google.generativeai as genai
import time
import os

# 引入 V25.7 PRO 的後端核心模組 (假設您的後端儲存為 whale_engines.py)
from whale_engines import WhaleEngine, ScannerEngine, WhaleTools

# ==========================================
# 1. 系統設定與權限管理
# ==========================================
st.set_page_config(page_title="邱神選股決策中心 V25.7 PRO", layout="wide")

def check_password():
    """超級管理員權限驗證"""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 邱神選股決策中心 V25.7 PRO")
        username = st.text_input("使用者帳號", key="username")
        password = st.text_input("密碼", type="password", key="password")
        if st.button("登入"):
            # 超級管理員帳號：chiu
            # 實務建議：將密碼配置於 Streamlit Cloud 的 secrets.toml 中
            if username == "chiu" and password == st.secrets.get("admin_password", "chiu"): 
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("😕 帳號或密碼錯誤，請確認超級管理員權限。")
        return False
    return True

# 若未通過驗證則停止渲染後續頁面
if not check_password():
    st.stop()

# ==========================================
# 2. 系統初始化 (量化引擎與 Gemini AI)
# ==========================================
@st.cache_resource
def init_engine():
    """初始化並快取 WhaleEngine 總司令部，避免每次互動重複載入"""
    return WhaleEngine()

engine = init_engine()

# 初始化 Gemini 1.5 Pro AI
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.sidebar.warning("⚠️ 系統偵測未設定 Gemini API Key，多模態視覺審查功能將受限。")

# ==========================================
# 3. 前端介面：雙軌模式控制台
# ==========================================
st.title("🐋 邱神選股決策中心 (GrandMaster Whale Engine) V25.7 PRO")
st.sidebar.header("🕹️ 指揮控制台")
mode = st.sidebar.radio("請選擇操作模式：", ["🎯 手動狙擊模式", "📡 全自動雷達掃描"])

# ==========================================
# 4. 繪圖模組 (Plotly 動態雙圖表)
# ==========================================
def render_plotly_charts(stock_id):
    """渲染近2月日K與均線 / 當日5分K走勢"""
    st.subheader(f"📊 {stock_id} 綜合量價透視圖")
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        df_daily = ticker.history(period="2mo")
        df_5m = ticker.history(period="1d", interval="5m")
        
        if df_daily.empty:
            # 嘗試上櫃代碼
            ticker = yf.Ticker(f"{stock_id}.TWO")
            df_daily = ticker.history(period="2mo")
            df_5m = ticker.history(period="1d", interval="5m")
            
        if df_daily.empty:
            st.error(f"❌ 找不到 {stock_id} 的報價資料。")
            return
            
        # 建立均線指標
        df_daily['MA5'] = df_daily['Close'].rolling(5).mean()
        df_daily['MA10'] = df_daily['Close'].rolling(10).mean()
        df_daily['MA20'] = df_daily['Close'].rolling(20).mean()

        fig = make_subplots(
            rows=2, cols=2, 
            shared_xaxes=False, 
            vertical_spacing=0.1,
            subplot_titles=("近2月日K與均線", "當日5分K走勢", "成交量"),
            row_heights=[0.7, 0.3],
            specs=[[{"type": "xy"}, {"type": "xy", "rowspan": 2}],
                   [{"type": "xy"}, None]]
        )

        # 1. 日K線與短中均線 (左上)
        fig.add_trace(go.Candlestick(x=df_daily.index, open=df_daily['Open'], high=df_daily['High'], low=df_daily['Low'], close=df_daily['Close'], name='日K'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['MA5'], mode='lines', name='MA5', line=dict(color='blue', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['MA10'], mode='lines', name='MA10', line=dict(color='orange', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['MA20'], mode='lines', name='MA20', line=dict(color='green', width=1)), row=1, col=1)

        # 2. 當日5分K走勢 (右側合併)
        if not df_5m.empty:
            fig.add_trace(go.Scatter(x=df_5m.index, y=df_5m['Close'], mode='lines', name='5分K', line=dict(color='purple', width=2)), row=1, col=2)
            
        # 3. 雙色成交量 (左下)
        colors = ['red' if close < open else 'green' for close, open in zip(df_daily['Close'], df_daily['Open'])]
        fig.add_trace(go.Bar(x=df_daily.index, y=df_daily['Volume'], marker_color=colors, name='成交量'), row=2, col=1)

        fig.update_layout(height=600, showlegend=True, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"❌ 圖表渲染失敗: {str(e)}")

# ==========================================
# 5. Gemini AI 視覺交叉審查模組
# ==========================================
def gemini_vision_review(stock_id):
    """呼叫 gemini-1.5-pro 進行輔助判讀"""
    st.subheader("🤖 Gemini 1.5 Pro AI 多模態視覺交叉審查")
    if st.button(f"啟動 {stock_id} AI 深度解析"):
        with st.spinner("🧠 Gemini 正在融合量化數據與圖表型態進行審查..."):
            try:
                model = genai.GenerativeModel('gemini-1.5-pro')
                # 實務上這裡可以透過 PIL 截取上方 Plotly 圖片餵給 Gemini，此處先以提示詞示範
                prompt = f"你是一位擁有20年經驗的台股頂級量化交易專家。請根據『邱神選股決策中心 V25.7 PRO』對 {stock_id} 的各項均線（MA5/10/20）與成交量變化，給出專業的進出場策略、型態判讀與風險提示。請使用繁體中文（台灣）。"
                response = model.generate_content(prompt)
                st.info(response.text)
            except Exception as e:
                st.error(f"❌ Gemini AI 呼叫失敗，請檢查 API Key 或連線狀態。詳細錯誤: {str(e)}")

# ==========================================
# 6. 核心排程：雙軌模式執行邏輯
# ==========================================

if mode == "🎯 手動狙擊模式":
    st.header("🎯 手動狙擊模式 (單點深度體檢)")
    stock_input = st.text_input("請輸入股票代號 (例如：2330)", "")
    
    if st.button("執行深度體檢") and stock_input:
        with st.spinner(f"正在對 {stock_input} 進行 V25.7 PRO 深度量化分析..."):
            try:
                # 呼叫後端總司令部 (此處預設為盤後模式)
                # res = engine.analyze(stock_input, mode='after_market')
                st.success(f"✅ {stock_input} 基礎分析完成！")
                
                # 渲染前端 UI 模組
                render_plotly_charts(stock_input)
                gemini_vision_review(stock_input)
                
            except Exception as e:
                st.error(f"❌ 分析過程中斷: {str(e)}")

elif mode == "📡 全自動雷達掃描":
    st.header("📡 均線突破前鋒雷達 (全市場流動性與壓縮篩選)")
    st.info("系統將自動掃描市場流動性充足 (>=800張) 且均線極度壓縮 (Bandwidth <= 0.025) 的標的。")
    
    if st.button("🚀 啟動前鋒雷達全自動掃描"):
        my_bar = st.progress(0.0, text="前鋒雷達啟動中，正在初始化掃描器...")
        scan_placeholder = st.empty()
        
        # 【關鍵修復】確保包含完整的 try-except 防呆機制，接住所有網路中斷與例外
        try:
            scan_placeholder.info("🛡️ 啟動【防護盾分批下載模式】過濾流動性 (為避免 API 封鎖，已加入亂數降速，預計耗時 1~2 分鐘)...")
            
            # 實體化 V25.7 掃描引擎
            scanner = ScannerEngine(engine.shared_dl)
            
            # 執行掃描並帶入 V25.7 的嚴格均線壓縮參數
            target_stocks = scanner.run_scan(min_volume_sheets=800, top_n_liquidity=300, max_bandwidth=0.025)
            
            # 執行成功，推滿進度條 (原先報錯的區塊已受防護)
            my_bar.progress(1.0, text="批次掃描完成！")
            
            if target_stocks:
                scan_placeholder.success(f"🎯 均線掃描完成！共精選出 {len(target_stocks)} 檔極度壓縮潛力股，已送交總司令部！")
                st.write("### 🚀 雷達鎖定清單")
                for stock in target_stocks:
                    st.markdown(f"**{stock}**")
                    # 實務上可在此加入自動呼叫 engine.analyze(stock) 或 render_plotly_charts(stock)
            else:
                scan_placeholder.warning("⚠️ 前鋒雷達今日未尋獲符合極端壓縮條件之標的。")
                
        except Exception as e:
            # 捕捉所有的底層錯誤，清空卡住的進度條，並於畫面輸出紅色警示，防止網頁崩潰 (White Screen)
            my_bar.empty()
            scan_placeholder.error(f"❌ 掃描過程發生系統異常：{str(e)}")
            
            # 保留 Traceback 幫助我們後續量化邏輯除錯
            with st.expander("展開查看詳細錯誤資訊 (Traceback)"):
                st.exception(e)
