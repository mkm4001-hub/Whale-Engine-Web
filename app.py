import streamlit as st
import os
from datetime import datetime
import pytz
from FinMind.data import DataLoader

# ==========================================
# 載入我們獨立存放的 Whale Engines
# ==========================================
from whale_engines import *

# ==========================================
# 1. 帳號密碼登入系統
# ==========================================
USERS = {
    "admin": "whale888",
    "vip": "2026pro"
}

def check_login():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        st.title("🔒 GrandMaster Whale Engine 登入系統")
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        if st.button("登入"):
            if username in USERS and USERS[username] == password:
                st.session_state.authenticated = True
                st.session_state.user = username
                st.rerun()
            else:
                st.error("帳號或密碼錯誤！")
        return False
    return True

if not check_login():
    st.stop()

st.sidebar.write(f"歡迎回來，**{st.session_state.user}**")
if st.sidebar.button("登出"):
    st.session_state.authenticated = False
    st.rerun()

# ==========================================
# 2. 網頁版主介面與執行邏輯 (免 Token 免費版)
# ==========================================
st.title("🐋 GrandMaster Whale Engine V24.9 PRO")
st.info("💡 系統已啟用 FinMind 免費版模式，無需輸入 Token。")

mode_choice = st.radio("選擇模式", ["盤後大局透視 (嚴格資料對齊)", "盤中極速模式 (純技術面)"])
stock_input = st.text_input("請輸入股票代號 (多檔請用空白分隔，例如: 2330 3034)")

if st.button("🚀 開始分析"):
    if not stock_input:
        st.warning("請輸入至少一檔股票代號！")
    else:
        current_mode = 'intraday' if '盤中' in mode_choice else 'after_market'
        stock_list = list(dict.fromkeys([s.strip() for s in stock_input.split() if s.strip()]))
        
        st.info("系統運算中，請稍候...")
        
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
            
            for stock_id in stock_list:
                st.subheader(f"📊 [{stock_id}] 實戰分析報告")
                
                try:
                    df, target_code, data_quality, rev_df = data_engine.load_stock(stock_id, current_mode)
                    mkt = data_engine.load_market(target_code)
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
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("機會分數", position["opportunity_score"])
                    col2.metric("魚頭分數", fish["fish_score"])
                    col3.metric("健康等級", fish["health_grade"])
                    
                    st.markdown(f"**系統解讀：** {position['position_comment']}")
                    st.markdown(f"**防守價：** {position['defensive_price']} ({position['defensive_status_text']})")
                    st.markdown(f"**綜合風險狀態：** 撤退 [{retreat['risk_status']}] | 預警 [{warning['warning_status']}]")
                    st.divider()
                except Exception as e:
                    st.error(f"分析 {stock_id} 時發生錯誤: {str(e)}")
                    
            st.success("全部分析完成！")
        except Exception as e:
            st.error(f"系統啟動失敗。錯誤訊息: {str(e)}")
