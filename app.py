import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import google.generativeai as genai
import time
import os

# 引入 V25.7 PRO 的後端核心模組
from whale_engines import WhaleEngine, ScannerEngine, WhaleTools

# ==========================================
# 1. 系統設定與權限管理
# ==========================================
st.set_page_config(page_title="巨鯨決策中心 V25.7 PRO", layout="wide")

def check_password():
    """超級管理員權限驗證"""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 巨鯨選股決策中心 V25.7 PRO")
        username = st.text_input("使用者帳號", key="username")
        password = st.text_input("密碼", type="password", key="password")
        if st.button("登入"):
            # 預設超級管理員帳號：chiu
            if username == "chiu" and password == st.secrets.get("admin_password", "chiu"): 
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("😕 帳號或密碼錯誤，請確認超級管理員權限。")
        return False
    return True

if not check_password():
    st.stop()

# 載入 FinMind Token 至環境變數 (供後端讀取)
if "FINMIND_TOKEN" in st.secrets:
    os.environ["FINMIND_TOKEN"] = st.secrets["FINMIND_TOKEN"]

# ==========================================
# 2. 系統初始化 (載入 GitHub 集保資料與量化引擎)
# ==========================================

# ⚠️ 將這裡替換為您在 GitHub 上實際建立的儲存庫名稱 (格式: 帳號/儲存庫名稱)
# 例如，如果您建立的 Repository 叫做 WhaleEngine-TDCC-Data
GITHUB_REPO = "mkm4001-hub/請填入您的儲存庫名稱"

@st.cache_resource
def init_engine():
    """初始化並快取 WhaleEngine 總司令部，傳入 GitHub Repo 讓系統自動抓取 CSV"""
    return WhaleEngine(github_repo=GITHUB_REPO)

with st.spinner(f"⏳ 正在初始化系統並透過 API 自動掃描 GitHub ({GITHUB_REPO}) 上的集保快取資料..."):
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

# 提供手動重置快取的按鈕，週末上傳新 CSV 檔案到 GitHub 後，點擊此按鈕即可自動抓取最新資料！
if st.sidebar.button("🔄 強制重載 GitHub 集保資料"):
    st.cache_resource.clear()
    st.rerun()

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
            ticker = yf.Ticker(f"{stock_id}.TWO")
            df_daily = ticker.history(period="2mo")
            df_5m = ticker.history(period="1d", interval="5m")
            
        if df_daily.empty:
            st.error(f"❌ 找不到 {stock_id} 的報價資料。")
            return
            
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

        fig.add_trace(go.Candlestick(x=df_daily.index, open=df_daily['Open'], high=df_daily['High'], low=df_daily['Low'], close=df_daily['Close'], name='日K'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['MA5'], mode='lines', name='MA5', line=dict(color='blue', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['MA10'], mode='lines', name='MA10', line=dict(color='orange', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['MA20'], mode='lines', name='MA20', line=dict(color='green', width=1)), row=1, col=1)

        if not df_5m.empty:
            fig.add_trace(go.Scatter(x=df_5m.index, y=df_5m['Close'], mode='lines', name='5分K', line=dict(color='purple', width=2)), row=1, col=2)
            
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
                # 執行分析
                res = engine.analyze(stock_input, mode='after_market')
                
                # 判斷是否分析成功
                if "【分析失敗】" not in res.get("position", {}).get("candidate_status", ""):
                    st.success(f"✅ {stock_input} 基礎分析完成！")
                    
                    # 顯示機會與分數
                    col1, col2, col3 = st.columns(3)
                    col1.metric("健康等級", res["fish"]["health_grade"])
                    col2.metric("魚頭分數", res["fish"]["fish_score"])
                    col3.metric("實戰防守價", res["position"]["defensive_price"])
                    
                    st.info(f"💡 系統解讀：{res['position']['strategy_profile']}")
                    
                    # 渲染圖表與 AI 診斷
                    render_plotly_charts(stock_input)
                    gemini_vision_review(stock_input)
                else:
                    st.error(f"❌ {stock_input} 資料異常，無法完成分析。")
                
            except Exception as e:
                st.error(f"❌ 分析過程中斷: {str(e)}")

elif mode == "📡 全自動雷達掃描":
    st.header("📡 均線突破前鋒雷達 (全市場流動性與壓縮篩選)")
    st.info("系統將自動掃描市場流動性充足 (>=800張) 且均線極度壓縮 (Bandwidth <= 0.025) 的標的。")
    
    if st.button("🚀 啟動前鋒雷達全自動掃描"):
        my_bar = st.progress(0.0, text="前鋒雷達啟動中，正在初始化掃描器...")
        scan_placeholder = st.empty()
        
        try:
            scan_placeholder.info("🛡️ 啟動【防護盾分批下載模式】過濾流動性 (為避免 API 封鎖，已加入亂數降速，預計耗時 1~2 分鐘)...")
            
            scanner = ScannerEngine(engine.shared_dl)
            target_stocks = scanner.run_scan(min_volume_sheets=800, top_n_liquidity=300, max_bandwidth=0.025)
            
            my_bar.progress(1.0, text="批次掃描完成！")
            
            if target_stocks:
                scan_placeholder.success(f"🎯 均線掃描完成！共精選出 {len(target_stocks)} 檔極度壓縮潛力股，已送交總司令部！")
                st.write("### 🚀 雷達鎖定清單")
                for stock in target_stocks:
                    st.markdown(f"**{stock}**")
            else:
                scan_placeholder.warning("⚠️ 前鋒雷達今日未尋獲符合極端壓縮條件之標的。")
                
        except Exception as e:
            my_bar.empty()
            scan_placeholder.error(f"❌ 掃描過程發生系統異常：{str(e)}")
            with st.expander("展開查看詳細錯誤資訊 (Traceback)"):
                st.exception(e)
