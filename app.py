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
# 1. 帳號密碼與權限分級系統
# ==========================================
# 你可以在這裡設定帳號、密碼，以及他的權限 ('full' 代表完整版, 'simple' 代表簡易版)
USERS = {
    "chiu": {"password": "gshock2500!", "role": "full"},
    "abs0401": {"password": "study01!", "role": "full"},
    "other01": {"password": "55688!!!", "role": "full"},
    "user1": {"password": "123", "role": "simple"},
    "user2": {"password": "123", "role": "simple"}
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
                st.session_state.role = USERS[username]["role"] # 記錄該使用者的權限
                st.rerun()
            else:
                st.error("帳號或密碼錯誤！")
        return False
    return True

if not check_login():
    st.stop()

# 側邊欄顯示使用者身分
role_display = "🌟 完整版權限" if st.session_state.role == "full" else "👁️ 簡易版權限"
st.sidebar.write(f"歡迎回來，**{st.session_state.user}**")
st.sidebar.write(f"當前身分：{role_display}")
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
                    if st.session_state.role == "full":
                        # --------- 【完整版】顯示邏輯 (對標 Excel 詳細內容) ---------
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("機會分數", position["opportunity_score"])
                        col2.metric("魚頭分數", fish["fish_score"])
                        col3.metric("健康等級", fish["health_grade"])
                        col4.metric("綜合撤退", retreat["retreat_score"])
                        
                        st.markdown(f"**大局狀態：** {position['candidate_status']} | **魚體位置：** {position['fish_position']}")
                        st.markdown(f"**目前價：** {position['current_price']} | **實戰防守價：** {position['defensive_price']} ({position.get('defensive_status_text', '')})")
                        st.markdown(f"**綜合風險提示：** 撤退 [{retreat['risk_status']}] | 預警 [{warning['warning_status']}]")
                        
                        # 使用 Tabs 來收納龐大的資訊，讓網頁看起來乾淨
                        tab1, tab2, tab3 = st.tabs(["核心與基本面", "防禦與籌碼雷達", "體檢與預警明細"])
                        
                        with tab1:
                            st.write(f"**保守目標區：** {position.get('target_low', '-')} ~ {position.get('target_high', '-')}")
                            st.write(f"**剩餘空間：** +{position.get('upside_low', '-')} ~ +{position.get('upside_high', '-')}")
                            st.write(f"**營收基本面判定：** {fundamental['fund_label']}")
                            st.write(f"**年增率(YoY)：** {fundamental['yoy']}% | **月增率(MoM)：** {fundamental['mom']}%")
                            st.markdown("**【系統解讀】**")
                            st.info(position.get('position_comment', '無'))
                            st.info(position.get('strategy_profile', '無'))
                            
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
                                    # 撤退檢查觸發通常是壞事(打叉)
                                    mark = "❌" if status is True else "✅" if status is False else "❓"
                                    st.caption(f"{mark} {item}")
                                st.write("**【高檔預警】**")
                                for item, status in warning["warning_checks"]:
                                    mark = "❌" if status is True else "✅" if status is False else "❓"
                                    st.caption(f"{mark} {item}")

                    else:
                        # --------- 【簡易版】顯示邏輯 (極簡版摘要) ---------
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
