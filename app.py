import streamlit as st
import os
import csv
import time
import random
from datetime import datetime
import pytz
from FinMind.data import DataLoader

# 載入我們獨立存放的 Whale Engines
from whale_engines import *

# ==========================================
# 0. 查詢紀錄功能 (寫入 CSV)
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

# ==========================================
# 1. 帳號密碼與權限分級系統 (三層架構)
# ==========================================
USERS = {
    "master": {"password": "pwd", "role": "superuser"}, # 唯一擁有下載查詢紀錄權限
    "admin1": {"password": "pwd", "role": "full"},      # 完整版帳號 1
    "admin2": {"password": "pwd", "role": "full"},      # 完整版帳號 2
    "user1": {"password": "123", "role": "simple"},     # 簡易版帳號 1
    "user2": {"password": "123", "role": "simple"}      # 簡易版帳號 2
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

# 側邊欄身分顯示與管理員專區
if st.session_state.role == "superuser":
    role_display = "👑 最高管理者 (含追蹤權限)"
elif st.session_state.role == "full":
    role_display = "🌟 完整版權限"
else:
    role_display = "👁️ 簡易版權限"

st.sidebar.write(f"歡迎回來，**{st.session_state.user}**")
st.sidebar.write(f"當前身分：{role_display}")

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
    else:
        st.sidebar.caption("目前尚無任何人查詢紀錄")

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
        
        st.info("系統運算中，請稍候... (已啟用防鎖隨機延遲保護)")
        
        # 建立進度條
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
                    
                    # 🌟 V25.2 修改：傳入個股最新日期給 load_market，提供 OTC 備援判斷
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
                    
                    if st.session_state.role in ["superuser", "full"]:
                        # --------- 【完整版】戰情儀表板 ---------
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
                            
                        st.info(f"**💰 目前價(Raw)：** `{position['current_price']}` ｜ **🛡️ 實戰防守價(ATR)：** `{position['defensive_price']}` *(容忍: {position.get('max_tolerance', 8.0)}%)* ｜ **⚖️ 60日加權均價：** `{position['vwap60']}`")
                        
                        if chip_xray['is_surge']:
                            st.success(f"🔥 **【集保 X 光透視】{chip_xray['xray_status']}**：{chip_xray['xray_message']}")
                        else:
                            st.info(f"🔍 **【集保 X 光透視】{chip_xray['xray_status']}**：{chip_xray['xray_message']}")
                        
                        tab1, tab2, tab3 = st.tabs(["核心與基本面", "防禦與籌碼雷達", "體檢與預警明細"])
                        
                        with tab1:
                            st.write(f"**保守目標區：** {position.get('target_low', '-')} ~ {position.get('target_high', '-')}")
                            st.write(f"**剩餘空間：** +{position.get('upside_low', '-')} ~ +{position.get('upside_high', '-')}")
                            st.markdown("**【系統解讀】**")
                            st.info(position.get('position_comment', '無'))
                            
                        with tab2:
                            st.write(f"**【籌碼續航力】當前狀態：** {endurance['endurance_status']}")
                            for msg in endurance.get('endurance_messages', []): st.caption(f"- {msg}")
                            
                            st.write(f"**【型態防禦雷達】當前狀態：** {defense['defense_status']}")
                            if defense.get('defense_signals'):
                                for sig in defense['defense_signals']: st.caption(f"- {sig}")
                            else:
                                st.caption("- 無明顯防守跡象")
                                
                            st.write(f"**【盤後法人透視】當前狀態：** {chip.get('chip_status', '無資料')}")
                            for msg in chip.get('chip_messages', []): st.caption(f"- {msg}")

                        with tab3:
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
                        # --------- 【簡易版】極簡版摘要 ---------
                        col1, col2, col3 = st.columns(3)
                        col1.metric("機會分數", position["opportunity_score"])
                        col2.metric("魚頭分數", fish["fish_score"])
                        col3.metric("健康等級", fish["health_grade"])
                        
                        st.markdown(f"**系統解讀：** {position.get('position_comment', '無')}")
                        st.markdown(f"**防守價：** {position['defensive_price']} ({position.get('defensive_status_text', '')})")
                        st.markdown(f"**綜合風險狀態：** 撤退 [{retreat['risk_status']}] | 預警 [{warning['warning_status']}]")
                        st.caption(f"🔍 **集保透視：** {chip_xray['xray_message']}")
                        
                    st.divider()
                    
                    # 🌟 V25.2 修改：每一檔股票掃描完畢，強制執行隨機緩衝延遲 (1.5 ~ 3.5秒)
                    my_bar.progress((idx + 1) / total_stocks, text=f"{progress_text} (正在處理: {stock_id}...)")
                    if idx < total_stocks - 1:
                        delay_time = random.uniform(1.5, 3.5)
                        time.sleep(delay_time)
                        
                except Exception as e:
                    st.error(f"分析 {stock_id} 時發生錯誤: {str(e)}")
                    
            my_bar.progress(1.0, text="批次掃描完成！")
            st.success("全部分析完成！")
        except Exception as e:
            st.error(f"系統啟動失敗。錯誤訊息: {str(e)}")
