import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import math
import os
import io
from FinMind.data import DataLoader

# ==========================================
# 1. 帳號密碼登入系統 (你可以自己修改密碼)
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
# 2. 核心運算引擎 (請將 Colab 程式碼貼於此處)
# ==========================================
# 👇👇👇 請將 Colab 裡面的 Cell 2 到 Cell 11 的內容，依序複製並貼到下面 👇👇👇

# GrandMaster Whale Engine V24.9 Pro
# Cell 2: 工具函式

class WhaleTools:
    @staticmethod
    def round_tick(price, direction='nearest'):
        if pd.isna(price) or price <= 0: return 0.0
        # 🟢 CRO確認：此為台灣證交所普通股票真實升降單位，堅守實戰口徑，拒絕 AI 幻覺
        if price < 10: tick = 0.01
        elif price < 50: tick = 0.05
        elif price < 100: tick = 0.10
        elif price < 500: tick = 0.50
        elif price < 1000: tick = 1.00
        else: tick = 5.00

        if direction == 'floor': return math.floor(price / tick + 1e-9) * tick
        elif direction == 'ceil': return math.ceil(price / tick - 1e-9) * tick
        else: return round(price / tick) * tick

    @staticmethod
    def calculate_slope(series, period=5, scale=50, adaptive_factor=1.0):
        if len(series) < period: return 0.0
        y = series.tail(period).values
        x = np.arange(len(y))
        slope, _ = np.polyfit(x, y, 1)
        avg_val = np.abs(np.mean(y))
        if avg_val == 0: avg_val = 1
        final_scale = scale * max(adaptive_factor, 0.5)
        normalized_slope = (slope / avg_val) * final_scale
        return float(np.degrees(np.arctan(normalized_slope)))

    @staticmethod
    def calculate_vwap60(df):
        return (df["Close"] * df["Volume"]).rolling(60, min_periods=1).sum() / df["Volume"].rolling(60, min_periods=1).sum()

    @staticmethod
    def calculate_obv(df):
        return (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()

    @staticmethod
    def get_vol_factor(df):
        daily_volatility = df["Close"].pct_change().std() * 100
        return max(0.5, daily_volatility)

    @staticmethod
    def calculate_rs(stock_close, market_close, period=20):
        if len(stock_close) <= period or len(market_close) <= period: return 0.0
        stock_return = (stock_close.iloc[-1] / stock_close.iloc[-period - 1]) - 1
        market_return = (market_close.iloc[-1] / market_close.iloc[-period - 1]) - 1
        return float(stock_return - market_return)

    @staticmethod
    def get_market_adaptive_factor(mkt_df):
        try:
            volatility = mkt_df["Close"].pct_change().rolling(20).std().iloc[-1] * 100
            return float(max(0.5, min(1.5, volatility / 1.0)))
        except: return 1.0

print(f"WhaleTools 載入完成 (V24.9 PRO)")
# GrandMaster Whale Engine V24.9 Pro
# Cell 3: DataEngine (🌟 導入結構化 Error Code、查詢時間追蹤)

class DataEngine:
    def __init__(self, dataloader=None):
        if dataloader is None:
            self.dl = DataLoader()
            token = os.getenv("FINMIND_TOKEN")
            if not token: raise RuntimeError("缺少 FINMIND_TOKEN")
            self.dl.login_by_token(api_token=token)
        else: self.dl = dataloader

    def load_stock(self, stock_id, mode='after_market'):
        tw_code = str(stock_id).strip() + ".TW"
        two_code = str(stock_id).strip() + ".TWO"
        print(f"載入股票資料: {stock_id} ...")

        ticker = yf.Ticker(tw_code)
        df_adj = ticker.history(period="2y", auto_adjust=True)
        df_raw = ticker.history(period="2y", auto_adjust=False)

        if df_adj.empty or len(df_adj) < 10:
            ticker = yf.Ticker(two_code)
            df_adj = ticker.history(period="2y", auto_adjust=True)
            df_raw = ticker.history(period="2y", auto_adjust=False)
            if df_adj.empty: raise ValueError(f"[empty_response] 找不到股票代號: {stock_id}")
            target_code = two_code
        else: target_code = tw_code

        df = df_adj.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            df_raw.columns = df_raw.columns.get_level_values(0)

        if df.index.tz is not None:
            df.index = df.index.tz_convert('Asia/Taipei').tz_localize(None)
            df_raw.index = df_raw.index.tz_convert('Asia/Taipei').tz_localize(None)

        df = df[df["Volume"] > 0].copy()
        df = df.dropna(subset=["Close"]).copy()
        common_idx = df.index.intersection(df_raw.index)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df.loc[common_idx, f'Raw_{col}'] = df_raw.loc[common_idx, col]

        latest_raw = df.iloc[-1]
        if pd.isna(latest_raw.get('Raw_Open')) or pd.isna(latest_raw.get('Raw_Close')):
            raise ValueError("[schema_error] 最新交易日 K 線資料不完整。")

        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz)
        latest_price_date = df.index[-1].strftime("%Y-%m-%d")

        data_quality = {
            'inst_state': 'missing', 'margin_state': 'missing', 'missing_inst_parts': [],
            'is_intraday': False, 'latest_price_date': latest_price_date,
            'inst_latest_date': '無資料', 'margin_latest_date': '無資料', 'revenue_latest_date': '無資料',
            'mkt_latest_date': '無資料', 'queried_at': now.strftime("%Y-%m-%d %H:%M:%S"),
            'errors': []
        }
        rev_df = pd.DataFrame()

        if mode == 'intraday':
            df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = df['Margin_Balance_Raw'] = np.nan
            data_quality['is_intraday'] = True
            return df, target_code, data_quality, rev_df

        start_date = (now - timedelta(days=730)).strftime("%Y-%m-%d")
        fm_end_date = now.strftime("%Y-%m-%d")

        # --- 1. 法人資料 ---
        try:
            inst_df = self.dl.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=fm_end_date)
            if not inst_df.empty:
                inst_df['date'] = pd.to_datetime(inst_df['date'])
                inst_df = inst_df.sort_values(['date', 'name']).drop_duplicates(subset=['date', 'name'])
                data_quality['inst_latest_date'] = inst_df['date'].max().strftime("%Y-%m-%d")

                if 'buy' in inst_df.columns and 'sell' in inst_df.columns:
                    inst_df['net_buy'] = pd.to_numeric(inst_df['buy'], errors='coerce') - pd.to_numeric(inst_df['sell'], errors='coerce')
                elif 'buy_sell' in inst_df.columns:
                    inst_df['net_buy'] = pd.to_numeric(inst_df['buy_sell'], errors='coerce')
                else:
                    data_quality['inst_state'] = 'schema_error'
                    data_quality['errors'].append("[schema_error] 法人API缺乏買賣欄位")
                    raise ValueError("API Schema Error")

                foreign_names = ['外資及陸資(不含外資自營商)', 'Foreign_Investor', '外資自營商', 'Foreign_Dealer_Self']
                trust_names = ['投信', 'Investment_Trust']
                dealer_names = ['自營商(自行買賣)', '自營商(避險)', 'Dealer_self', 'Dealer_Hedging', '自營商', 'Dealer']

                df_trust = inst_df[inst_df['name'].isin(trust_names)].groupby('date')['net_buy'].sum(min_count=1)
                df_foreign = inst_df[inst_df['name'].isin(foreign_names)].groupby('date')['net_buy'].sum(min_count=1)
                df_dealer = inst_df[inst_df['name'].isin(dealer_names)].groupby('date')['net_buy'].sum(min_count=1)

                df = df.join(df_trust.rename('Trust_NetBuy'), how="left")
                df = df.join(df_foreign.rename('Foreign_NetBuy'), how="left")
                df = df.join(df_dealer.rename('Dealer_NetBuy'), how="left")

                df['Inst_NetBuy'] = df['Trust_NetBuy'] + df['Foreign_NetBuy'] + df['Dealer_NetBuy']

                date_strs = inst_df['date'].dt.strftime("%Y-%m-%d")
                if latest_price_date in date_strs.values:
                    latest_trust = df.loc[df.index[-1], 'Trust_NetBuy'] if df.index[-1] in df.index else np.nan
                    latest_foreign = df.loc[df.index[-1], 'Foreign_NetBuy'] if df.index[-1] in df.index else np.nan
                    latest_dealer = df.loc[df.index[-1], 'Dealer_NetBuy'] if df.index[-1] in df.index else np.nan

                    if pd.notna(latest_trust) and pd.notna(latest_foreign) and pd.notna(latest_dealer):
                        data_quality['inst_state'] = 'complete'
                    else:
                        data_quality['inst_state'] = 'partial'
                        if pd.isna(latest_foreign): data_quality['missing_inst_parts'].append('外資')
                        if pd.isna(latest_trust): data_quality['missing_inst_parts'].append('投信')
                        if pd.isna(latest_dealer): data_quality['missing_inst_parts'].append('自營商')
                else:
                    data_quality['inst_state'] = 'stale'
                    data_quality['missing_inst_parts'] = ['外資', '投信', '自營商']
            else:
                data_quality['inst_state'] = 'empty_response'
                data_quality['errors'].append("[empty_response] 法人API回傳空表")
                df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = np.nan
        except Exception as e:
            data_quality['inst_state'] = 'network_error'
            data_quality['errors'].append(f"[network_error] 法人例外: {str(e)}")
            df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = np.nan

        # --- 2. 融資資料 ---
        try:
            margin_df = self.dl.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=fm_end_date)
            if not margin_df.empty and "MarginPurchaseTodayBalance" in margin_df.columns:
                margin_df["date"] = pd.to_datetime(margin_df["date"])
                margin_df = margin_df.sort_values("date").drop_duplicates(subset=["date"])
                data_quality['margin_latest_date'] = margin_df['date'].max().strftime("%Y-%m-%d")
                margin_df.set_index('date', inplace=True)
                df = df.join(margin_df[['MarginPurchaseTodayBalance']].rename(columns={"MarginPurchaseTodayBalance": 'Margin_Balance_Raw'}), how='left')

                if pd.notna(df.loc[df.index[-1], 'Margin_Balance_Raw']): data_quality['margin_state'] = 'complete'
                else: data_quality['margin_state'] = 'missing'
            elif margin_df.empty:
                data_quality['margin_state'] = 'empty_response'
                data_quality['errors'].append("[empty_response] 融資API回傳空表")
                df['Margin_Balance_Raw'] = np.nan
            else:
                data_quality['margin_state'] = 'schema_error'
                data_quality['errors'].append("[schema_error] 融資API缺乏必要欄位")
                df['Margin_Balance_Raw'] = np.nan
        except Exception as e:
            data_quality['margin_state'] = 'network_error'
            data_quality['errors'].append(f"[network_error] 融資例外: {str(e)}")
            df['Margin_Balance_Raw'] = np.nan

        # --- 3. 營收資料 ---
        try:
            rev_start = (now - timedelta(days=365*4)).strftime("%Y-%m-%d")
            rev_df_raw = self.dl.taiwan_stock_month_revenue(stock_id=stock_id, start_date=rev_start, end_date=fm_end_date)
            if not rev_df_raw.empty:
                rev_df_raw['date'] = pd.to_datetime(rev_df_raw['date'])
                rev_df = rev_df_raw.sort_values('date').drop_duplicates(subset=['date']).reset_index(drop=True)

                latest_rev_year = rev_df.iloc[-1]['revenue_year']
                latest_rev_month = rev_df.iloc[-1]['revenue_month']
                data_quality['revenue_latest_date'] = f"{latest_rev_year}-{latest_rev_month:02d}"
        except Exception as e:
            data_quality['errors'].append(f"[network_error] 營收例外: {str(e)}")

        return df, target_code, data_quality, rev_df

    def load_market(self, target_code):
        mkt_ticker = "^TWOII" if target_code.endswith(".TWO") else "^TWII"
        mkt = yf.Ticker(mkt_ticker).history(period="2y", auto_adjust=True)
        if mkt is None or mkt.empty:
            raise ValueError("[empty_response] 大盤資料獲取失敗或回傳空表")
        if "Close" not in mkt.columns:
            raise ValueError("[schema_error] 大盤資料缺乏 Close 欄位")

        if isinstance(mkt.columns, pd.MultiIndex): mkt.columns = mkt.columns.get_level_values(0)
        if mkt.index.tz is not None: mkt.index = mkt.index.tz_convert('Asia/Taipei').tz_localize(None)
        return mkt[mkt["Close"] > 0].copy()

    def prepare_indicators(self, df, mkt):
        df["MA5"] = df["Close"].rolling(5, min_periods=1).mean()
        df["MA10"] = df["Close"].rolling(10, min_periods=1).mean()
        df["MA20"] = df["Close"].rolling(20, min_periods=1).mean()
        df["MA60"] = df["Close"].rolling(60, min_periods=1).mean()

        df["VOL5"] = df["Volume"].rolling(5, min_periods=1).mean()
        df["VOL20"] = df["Volume"].rolling(20, min_periods=1).mean()
        df["VOL5_PRIOR"] = df["Volume"].shift(1).rolling(5, min_periods=1).mean()
        df["VOL20_PRIOR"] = df["Volume"].shift(1).rolling(20, min_periods=1).mean()

        df["Typical_Price"] = (df["High"] + df["Low"] + df["Close"]) / 3
        df["VWAP60"] = WhaleTools.calculate_vwap60(df)
        df["OBV"] = WhaleTools.calculate_obv(df)

        df["STD20"] = df["Close"].rolling(20, min_periods=1).std().fillna(0)
        df["UpperBB"] = df["MA20"] + 2 * df["STD20"]
        df["LowerBB"] = df["MA20"] - 2 * df["STD20"]
        df["Bandwidth"] = np.where(df["MA20"] == 0, 0, (df["UpperBB"] - df["LowerBB"]) / df["MA20"])

        df["EMA12"] = df["Close"].ewm(span=12, adjust=False).mean()
        df["EMA26"] = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD_Hist"] = df["EMA12"] - df["EMA26"] - (df["EMA12"] - df["EMA26"]).ewm(span=9, adjust=False).mean()

        df['Prev_Close_Adj'] = df['Close'].shift(1)
        tr1 = df['High'] - df['Low']
        tr2 = (df['High'] - df['Prev_Close_Adj']).abs()
        tr3 = (df['Low'] - df['Prev_Close_Adj']).abs()
        df['ATR14'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14, min_periods=1).mean()

        df["VSA_Ratio"] = (df["Volume"] / df["VOL20_PRIOR"].replace(0, 1).fillna(1)) / ((df["High"] - df["Low"]) / df["ATR14"].replace(0, 0.01)).replace(0, 0.01)
        df["VSA_Ratio"] = df["VSA_Ratio"].replace([np.inf, -np.inf], 0.0).fillna(0)

        high_low_diff = df["High"] - df["Low"]
        clv = np.where(high_low_diff == 0, 0.0, ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / high_low_diff)
        df["CMF"] = (clv * df["Volume"]).rolling(20, min_periods=1).sum() / df["Volume"].rolling(20, min_periods=1).sum().replace(0, 1)

        vol_factor = WhaleTools.get_vol_factor(df)
        ma20_slope = WhaleTools.calculate_slope(df["MA20"], period=5, scale=50, adaptive_factor=vol_factor)

        common_idx = df.index.intersection(mkt.index)
        market_factor = 1.0
        mkt_latest_date = mkt.index[-1].strftime("%Y-%m-%d")

        if len(common_idx) > 0:
            if df.index[-1] != mkt.index[-1]:
                rs20, rs60, market_status = 0.0, 0.0, "Stale"
            else:
                rs20 = WhaleTools.calculate_rs(df.loc[common_idx, "Close"], mkt.loc[common_idx, "Close"], period=20)
                rs60 = WhaleTools.calculate_rs(df.loc[common_idx, "Close"], mkt.loc[common_idx, "Close"], period=60)
                mkt["MA20"] = mkt["Close"].rolling(20, min_periods=1).mean()
                market_factor = WhaleTools.get_market_adaptive_factor(mkt)
                mkt_slope = WhaleTools.calculate_slope(mkt["MA20"], period=5, scale=50, adaptive_factor=market_factor)

                if (mkt["Close"].loc[common_idx].iloc[-1] > mkt["MA20"].loc[common_idx].iloc[-1] and mkt_slope > 0): market_status = "Bull"
                elif (mkt["Close"].loc[common_idx].iloc[-1] < mkt["MA20"].loc[common_idx].iloc[-1] and mkt_slope < 0): market_status = "Bear"
                else: market_status = "Neutral"
        else:
            rs20, rs60, market_status = 0.0, 0.0, "Unknown"

        return {
            "df": df, "mkt": mkt, "rs20": rs20, "rs60": rs60,
            "vol_factor": vol_factor, "ma20_slope": ma20_slope, "market_status": market_status,
            "market_factor": market_factor, "mkt_latest_date": mkt_latest_date
        }

print(f"DataEngine 載入完成 ({WHALE_VERSION})")

# 👆👆👆 貼上範圍到此結束 👆👆👆

# ==========================================
# 3. 網頁版主介面與執行邏輯 (免 Token 免費版)
# ==========================================
st.title("🐋 GrandMaster Whale Engine V24.9 PRO")

st.info("💡 系統已啟用 FinMind 免費版模式，無需輸入 Token。(注意：免費版有每小時 API 呼叫次數限制，若連線失敗可能為達到上限)")

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
            # 【關鍵修改】：直接啟用 DataLoader，不執行 login_by_token
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
                    st.error(f"分析 {stock_id} 時發生錯誤 (可能是免費額度達上限或無此代號): {str(e)}")
                    
            st.success("全部分析完成！")
        except Exception as e:
            st.error(f"系統啟動失敗。錯誤訊息: {str(e)}")
