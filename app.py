import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import google.generativeai as genai
import time
import os

# 引入巨鯨系統的後端核心模組
from whale_engines import WhaleEngine, WhaleTools

# 載入我們獨立建立的帳號密碼檔
try:
    from auth import ADMIN_CREDENTIALS
except ImportError:
    # 預防 auth.py 遺失的防呆
    ADMIN_CREDENTIALS = {"chiu": "chiu"}

# ==========================================
# 1. 系統設定與權限管理
# ==========================================
st.set_page_config(page_title="巨鯨系統 V25.7 PRO", layout="wide")

def check_password():
    """巨鯨系統權限驗證 (讀取 auth.py)"""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 巨鯨系統 V25.7 PRO")
        username = st.text_input("使用者帳號", key="username")
        password = st.text_input("密碼", type="password", key="password")
        if st.button("登入"):
            # 檢查使用者是否存在，以及密碼是否正確
            if username in ADMIN_CREDENTIALS and password == ADMIN_CREDENTIALS[username]: 
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("😕 帳號或密碼錯誤，請確認權限。")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 2. 系統初始化與 API 設定 (TXT 檔上傳)
# ==========================================
st.sidebar.header("⚙️ 巨鯨系統設定")

# 1. 直接綁定您的 GitHub 集保資料庫 (自動抓取 CSV)
GITHUB_REPO = "mkm4001-hub/WhaleEngine-TDCC-Data"

# 2. 讓使用者上傳 Gemini API Key (.txt)
gemini_file = st.sidebar.file_uploader("📁 上傳 Gemini API Key (.txt 檔, 選項)", type=["txt"])
st.sidebar.caption("※ 若未上傳 API Key，系統將不會進行多模態 AI 深度分析。")

gemini_key = None
if gemini_file is not None:
    gemini_key = gemini_file.getvalue().decode("utf-8").strip()
else:
    gemini_key = st.secrets.get("GEMINI_API_KEY", None)

# 3. 讓使用者上傳 FinMind Token (.txt)
finmind_file = st.sidebar.file_uploader("📁 上傳 FinMind Token (.txt 檔, 選項)", type=["txt"])
st.sidebar.caption("※ 若未上傳 Token，將自動採用免費版額度 (系統會啟動亂數模擬人類爬蟲防封鎖)。")

finmind_key = None
if finmind_file is not None:
    finmind_key = finmind_file.getvalue().decode("utf-8").strip()
else:
    finmind_key = st.secrets.get("FINMIND_TOKEN", None)


@st.cache_resource
def init_engine(fm_token):
    """初始化並快取巨鯨系統總司令部"""
    return WhaleEngine(github_repo=GITHUB_REPO, finmind_token=fm_token)

with st.spinner(f"⏳ 巨鯨系統初始化，自動掃描 GitHub ({GITHUB_REPO}) 集保庫存..."):
    engine = init_engine(finmind_key if finmind_key else None)

if st.sidebar.button("🔄 強制重載 GitHub 集保資料"):
    st.cache_resource.clear()
    st.rerun()

# ==========================================
# 3. 繪圖模組 (Plotly 動態雙圖表)
# ==========================================
def render_plotly_charts(stock_id):
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
            st.error("找不到報價資料")
            return
            
        df_daily['MA5'] = df_daily['Close'].rolling(5).mean()
        df_daily['MA10'] = df_daily['Close'].rolling(10).mean()
        df_daily['MA20'] = df_daily['Close'].rolling(20).mean()

        fig = make_subplots(
            rows=2, cols=2, shared_xaxes=False, vertical_spacing=0.1,
            subplot_titles=("近2月日K與均線", "當日5分K走勢", "成交量"),
            row_heights=[0.7, 0.3], specs=[[{"type": "xy"}, {"type": "xy", "rowspan": 2}], [{"type": "xy"}, None]]
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
# 4. Gemini AI 視覺交叉審查模組 (升級強固版)
# ==========================================
def gemini_vision_review(stock_id, current_key, res_data, pos_list, neg_list):
    if current_key:
        st.subheader("🤖 Gemini AI 深度審查 (巨鯨核心)")
        genai.configure(api_key=current_key)
        
        if st.button(f"啟動 {stock_id} AI 分析"):
            with st.spinner("🧠 巨鯨系統正在將量化特徵融合交由 AI 審查 (請稍候)..."):
                
                # 組合提示詞，加入您指定的角色設定與免責聲明要求
                pos_str = chr(10).join(['- ' + p for p in pos_list]) if pos_list else '- 無明顯正面指標'
                neg_str = chr(10).join(['- ' + n for n in neg_list]) if neg_list else '- 無明顯負面指標'
                
                prompt = f"""你是一個20年經驗的台股資深分析師，請你依照系統判定指標的狀況，與近日K線圖，最新5分K線圖進行比對，確認是否吻合，判斷邏輯為何？並依照目前趨勢，判斷未來可能走勢方向何者為大?為什麼(判斷的部分需加註警語：僅為技術面判斷，不代表真實)

【巨鯨系統判定指標狀態】
🟢 正面指標 (多方支撐):
{pos_str}

🔴 負面/風險指標 (空方壓力):
{neg_str}

【綜合量化數據】
- 目前價位: {res_data['position']['current_price']}
- 實戰防守價: {res_data['position']['defensive_price']}
- 成本距離(60日乖離): {res_data['position']['cost_distance']}%
- 系統給出的策略指引: {res_data['position']['strategy_profile']}"""

                # 強固的防呆機制：嘗試 1.5 Pro，若 404 則自動切換 1.0 Pro 備用方案
                response_text = ""
                try:
                    model = genai.GenerativeModel('gemini-1.5-pro')
                    response = model.generate_content(prompt)
                    response_text = response.text
                except Exception as e:
                    if "404" in str(e) or "not found" in str(e).lower():
                        try:
                            # 發生 404 錯誤，啟動備用穩定模型
                            st.warning("⚠️ 偵測到 Google 1.5 Pro 伺服器命名變更 (404 錯誤)，系統已自動為您切換至穩定版備用模型進行分析。")
                            fallback_model = genai.GenerativeModel('gemini-pro')
                            response = fallback_model.generate_content(prompt)
                            response_text = response.text
                        except Exception as fallback_e:
                            st.error(f"❌ 備用模型呼叫失敗: {str(fallback_e)}")
                    else:
                        st.error(f"❌ Gemini AI 發生非預期的連線錯誤: {str(e)}")
                
                if response_text:
                    st.info(response_text)
    else:
        pass 

# ==========================================
# 5. UI 輔助函數 (轉換 O/X 記號)
# ==========================================
def format_fish_check(status):
    if status == "Error": return "⚠️ 錯誤"
    elif status is True: return "✅ 達成"
    else: return "❌ 未達"

def format_alert_check(status):
    if status == "Error": return "⚠️ 錯誤"
    elif status is True: return "🚨 觸發"
    else: return "✅ 安全"

# ==========================================
# 6. 主程式：深度狙擊模式 (狀態記憶區塊)
# ==========================================
st.title("🎯 巨鯨系統 (Sniper Edition) V25.7 PRO")
st.markdown("---")

# 初始化記憶區塊 (Session State)
if 'analysis_result' not in st.session_state:
    st.session_state['analysis_result'] = None
if 'analyzed_stock' not in st.session_state:
    st.session_state['analyzed_stock'] = ""

stock_input = st.text_input("🔍 請輸入股票代號 (例如：2330)", st.session_state['analyzed_stock'])

if st.button("🚀 執行單檔深度體檢") and stock_input:
    with st.spinner(f"巨鯨系統正在對 {stock_input} 進行量化分析 (若無上傳 Token，系統將自動啟動亂數延遲防呆，請稍候)..."):
        res = engine.analyze(stock_input, mode='after_market')
        st.session_state['analysis_result'] = res
        st.session_state['analyzed_stock'] = stock_input

# 渲染邏輯
if st.session_state['analysis_result'] is not None and st.session_state['analyzed_stock'] == stock_input:
    res = st.session_state['analysis_result']
    
    if "【分析失敗】" not in res.get("position", {}).get("candidate_status", ""):
        st.success(f"✅ {stock_input} 分析完成！")
        
        p = res["position"]
        f = res["fish"]
        c = res["chip"]
        r = res["retreat"]
        w = res["warning"]
        e = res["endurance"]
        d = res["defense"]
        cx = res["chip_xray"]
        fun = res["fundamental"]
        dq = res["data_quality"]

        # ==========================================
        # 💡 多空指標自動萃取邏輯 (餵給 UI 與 AI)
        # ==========================================
        positives = []
        negatives = []
        
        # 1. 魚頭體檢 (True為正向)
        for item, status in f["health_checks"]:
            if status is True: positives.append(f"【技術】{item}")
            
        # 2. 撤退與預警 (True為負向風險)
        for item, status in r["retreat_checks"]:
            if status is True: negatives.append(f"【撤退】{item}")
        for item, status in w["warning_checks"]:
            if status is True: negatives.append(f"【預警】{item}")
            
        # 3. 防守訊號 (皆為正向)
        for sig in d["defense_signals"]:
            positives.append(f"【防禦】{sig}")
            
        # 4. 續航力 (依關鍵字自動分類)
        for msg in e["endurance_messages"]:
            if any(k in msg for k in ["強勢", "買", "壓縮爆發", "大單"]):
                positives.append(f"【動能】{msg}")
            elif any(k in msg for k in ["弱勢", "賣", "衰退", "耗盡"]):
                negatives.append(f"【動能】{msg}")
                
        # 5. 法人與集保
        for msg in c["chip_messages"]:
            if any(k in msg for k in ["買", "點火", "認養", "進駐"]):
                positives.append(f"【法人】{msg}")
            elif any(k in msg for k in ["賣", "結帳", "提款", "潰散"]):
                negatives.append(f"【法人】{msg}")
                
        if cx.get("is_surge", False) or "吸籌" in cx.get("xray_status", "") or "潛伏" in cx.get("xray_status", ""):
            positives.append(f"【集保】{cx.get('xray_message', '')}")
        elif "派發" in cx.get("xray_status", "") or "逃頂" in cx.get("xray_status", ""):
            negatives.append(f"【集保】{cx.get('xray_message', '')}")
            
        # 6. 基本面營收
        if fun.get("is_dual_growth", False):
            positives.append(f"【營收】{fun.get('fund_label', '')}")
        elif fun.get("yoy", 0) < 0 or fun.get("mom", 0) < 0:
            negatives.append(f"【營收】{fun.get('fund_label', '')}")

        # --- 區塊 1：核心 KPI 面板 ---
        st.subheader("📌 戰情核心面板")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("健康等級", f["health_grade"])
        col2.metric("機會分數", p["opportunity_score"])
        col3.metric("魚頭分數", f["fish_score"])
        col4.metric("撤退風險", r["risk_status"])

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("目前價(Raw)", p["current_price"])
        col6.metric("實戰防守價", f"{p['defensive_price']}")
        col7.metric("60日加權均價", p["vwap60"])
        col8.metric("成本距離", f"{p['cost_distance']}%")
        
        st.info(f"💡 **系統策略指引**：{p['strategy_profile']} (防守基準: {p['defensive_status_text']})")

        # --- 區塊 2：多空綜合指標看板 ---
        st.markdown("---")
        st.subheader("⚖️ 巨鯨多空力道總結 (自動彙整)")
        col_pos, col_neg = st.columns(2)
        with col_pos:
            st.success("🟢 **正面指標 (多方支撐)**")
            if positives:
                for p_ind in positives: st.markdown(f"- {p_ind}")
            else:
                st.write("- 目前無明顯多方特徵")
                
        with col_neg:
            st.error("🔴 **負面/風險指標 (空方壓力)**")
            if negatives:
                for n_ind in negatives: st.markdown(f"- {n_ind}")
            else:
                st.write("- 目前無明顯空方特徵")

        # --- 區塊 3：單機版細部指標展開 ---
        st.markdown("---")
        st.subheader("📋 深度量化指標明細")
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🐟 魚頭體檢", "🏃 撤退與預警", "🛡️ 防禦與續航", "🏦 籌碼與集保", "📊 基本資料對齊"])
        
        with tab1:
            st.write("**【技術趨勢與動能】**")
            st.write(f"趨勢: {f['trend_status']} | 動能: {f['rs_status']} | 籌碼: {f['chip_status']}")
            st.write("**【詳細檢核表】**")
            for item, status in f["health_checks"]:
                st.markdown(f"- **{item}** : {format_fish_check(status)}")

        with tab2:
            col_r, col_w = st.columns(2)
            with col_r:
                st.write(f"**【撤退檢查】(分數: {r['retreat_score']})**")
                for item, status in r["retreat_checks"]:
                    st.markdown(f"- **{item}** : {format_alert_check(status)}")
            with col_w:
                st.write(f"**【高檔預警】(狀態: {w['warning_status']})**")
                for item, status in w["warning_checks"]:
                    st.markdown(f"- **{item}** : {format_alert_check(status)}")

        with tab3:
            st.write(f"**【續航力狀態】** {e['endurance_status']} (分數: {e['endurance_score']})")
            for msg in e["endurance_messages"]:
                st.markdown(f"🔹 {msg}")
            st.write("---")
            st.write(f"**【防守雷達狀態】** {d['defense_status']}")
            if d["defense_signals"]:
                for sig in d["defense_signals"]:
                    st.markdown(f"🛡️ {sig}")
            else:
                st.markdown("未偵測到特殊防禦行為")

        with tab4:
            st.write(f"**【法人雷達】** {c['chip_status']} (加分: {c['chip_score']})")
            for msg in c["chip_messages"]:
                st.markdown(f"💼 {msg}")
            st.write("---")
            st.write(f"**【集保 X 光透視】** {cx['xray_status']}")
            st.markdown(f"🔎 {cx['xray_message']}")

        with tab5:
            st.write(f"**【基本面狀態】** {fun['fund_label']}")
            st.write(f"K線與技術面最新日: {dq.get('latest_price_date', '無')}")
            st.write(f"法人買賣超最新日: {dq.get('inst_latest_date', '無')}")
            st.write(f"集保大戶最新日: {dq.get('tdcc_latest_date', '無')}")
            
        # --- 區塊 4：圖表與 AI 審查 ---
        st.markdown("---")
        render_plotly_charts(stock_input)
        
        # 將萃取出的正負面指標，連同計算結果一起傳給 AI
        gemini_vision_review(stock_input, gemini_key, res, positives, negatives)
        
    else:
        st.error(f"❌ {stock_input} 資料異常或歷史不足，無法完成分析。")
        if res.get("all_errors"):
            st.write("底層錯誤細節：", res["all_errors"])
