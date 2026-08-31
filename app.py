import streamlit as st
import os
import csv
from datetime import datetime
import pytz
from FinMind.data import DataLoader

# ==========================================
# 載入我們獨立存放的 Whale Engines
# ==========================================
from whale_engines import *

# ==========================================
# 0. 查詢紀錄功能 (將資料寫入 CSV 檔案)
# ==========================================
def log_query(username, stocks):
    filename = "query_logs.csv"
    file_exists = os.path.isfile(filename)
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    
    # 寫入 CSV，使用 utf-8-sig 確保 Excel 打開不會亂碼
    with open(filename, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["查詢時間", "登入帳號", "查詢股號"]) # 建立標題列
        writer.writerow([now, username, stocks])

# ==========================================
# 1. 帳號密碼與權限分級系統 (三層架構)
# ==========================================
# superuser: 完整報告 + 下載查詢紀錄
# full: 完整報告 (無下載權限)
# simple: 簡易報告 (無下載權限)
USERS = {
    "chiu": {"password": "gshock2500!!", "role": "superuser"}, # 唯一擁有追蹤權限的帳號
    "chi01": {"password": "Cc2468500!!", "role": "full"},      # 完整版帳號 1
    "abs0401": {"password": "study01!", "role": "full"},      # 完整版帳號 2
    "user1": {"password": "123", "role": "simple"},     # 簡易版帳號 1
    "user2": {"password": "123", "role": "simple"}      # 簡易版帳號 2
}

def check_login():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        st.title("🔒 GrandMaster Whale Engine")
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

# ==========================================
# 側邊欄：使用者資訊與管理員專區
# ==========================================
# 根據權限顯示不同的身分標籤
if st.session_state.role == "superuser":
    role_display = "👑 最高管理者 (含追蹤權限)"
elif st.session_state.role == "full":
    role_display = "🌟 完整版權限"
else:
    role_display = "👁️ 簡易版權限"

st.sidebar.write(f"歡迎回來，**{st.session_state.user}**")
st.sidebar.write(f"當前身分：{role_display}")

# 【權限控管】僅有 superuser (最高管理者) 可見下載日誌區塊
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
st.title("🐋 GrandMaster Whale Engine V24.9 PRO")
st.info("💡 系統已啟用 FinMind 免費版模式，無需輸入 Token。")

mode_choice = st.radio("選擇模式", ["盤後大局透視 (嚴格資料對齊)", "盤中極速模式 (純技術面)"])
stock_input = st.text_input("請輸入股票代號 (多檔請用空白分隔，例如: 2330 3034)")

if st.button("🚀 開始分析"):
    if not stock_input:
        st.warning("請輸入至少一檔股票代號！")
    else:
        # 記錄這筆查詢到 CSV 中 (所有人查詢都會被記錄)
        log_query(st.session_state.user, stock_input)
        
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
                    
                    # ==========================================
                    # 3. 根據權限顯示不同深度的報告
                    # ==========================================
                    # 【權限控管】superuser 與 full 都可以看到完整的戰情儀表板
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
                                
                            st.write(f"**【盤後籌碼透視】當前狀態：** {chip.get('chip_status', '無資料')}")
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
                        
                    st.divider()
                except Exception as e:
                    st.error(f"分析 {stock_id} 時發生錯誤: {str(e)}")
                    
            st.success("全部分析完成！")
        except Exception as e:
            st.error(f"系統啟動失敗。錯誤訊息: {str(e)}")
