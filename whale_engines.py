import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import math
import time
import random
from FinMind.data import DataLoader
import warnings
warnings.filterwarnings("ignore")

WHALE_VERSION = "V25.2 PRO"

# ==========================================
# 模組 1: WhaleTools
# ==========================================
class WhaleTools:
    @staticmethod
    def round_tick(price, direction='nearest'):
        if pd.isna(price) or price <= 0: return 0.0
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
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        return (typical_price * df["Volume"]).rolling(60, min_periods=1).sum() / df["Volume"].rolling(60, min_periods=1).sum()

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


# ==========================================
# 模組 2: DataEngine (🌟 V25.2: 擬真延遲與大盤備援)
# ==========================================
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

        df_adj, df_raw = pd.DataFrame(), pd.DataFrame()
        for attempt in range(3):
            try:
                ticker = yf.Ticker(tw_code)
                df_adj = ticker.history(period="2y", auto_adjust=True)
                df_raw = ticker.history(period="2y", auto_adjust=False)
                if not df_adj.empty and len(df_adj) >= 10: break
            except: time.sleep(1)

        if df_adj.empty or len(df_adj) < 10:
            for attempt in range(3):
                try:
                    ticker = yf.Ticker(two_code)
                    df_adj = ticker.history(period="2y", auto_adjust=True)
                    df_raw = ticker.history(period="2y", auto_adjust=False)
                    if not df_adj.empty and len(df_adj) >= 10: break
                except: time.sleep(1)

            if df_adj.empty: raise ValueError(f"[empty_response] 找不到股票代號或連線失敗: {stock_id}")
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
            'tdcc_latest_date': '無資料', 'mkt_latest_date': '無資料', 'queried_at': now.strftime("%Y-%m-%d %H:%M:%S"),
            'errors': []
        }
        rev_df = pd.DataFrame()
        tdcc_df = pd.DataFrame()

        if mode == 'intraday':
            df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = df['Margin_Balance_Raw'] = np.nan
            data_quality['is_intraday'] = True
            return df, target_code, data_quality, rev_df, tdcc_df

        start_date = (now - timedelta(days=730)).strftime("%Y-%m-%d")
        fm_end_date = now.strftime("%Y-%m-%d")

        # 1. 法人資料
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
                    data_quality['inst_state'] = 'complete'
                else:
                    data_quality['inst_state'] = 'stale'
            else:
                data_quality['inst_state'] = 'empty_response'
                df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = np.nan
        except Exception as e:
            data_quality['inst_state'] = 'network_error'
            df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = np.nan

        time.sleep(random.uniform(0.2, 0.6)) # 防火牆緩衝

        # 2. 融資資料
        try:
            margin_df = self.dl.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=fm_end_date)
            if not margin_df.empty and "MarginPurchaseTodayBalance" in margin_df.columns:
                margin_df["date"] = pd.to_datetime(margin_df["date"])
                margin_df = margin_df.sort_values("date").drop_duplicates(subset=["date"])
                data_quality['margin_latest_date'] = margin_df['date'].max().strftime("%Y-%m-%d")
                margin_df.set_index('date', inplace=True)
                df = df.join(margin_df[['MarginPurchaseTodayBalance']].rename(columns={"MarginPurchaseTodayBalance": 'Margin_Balance_Raw'}), how='left')
                data_quality['margin_state'] = 'complete' if pd.notna(df.loc[df.index[-1], 'Margin_Balance_Raw']) else 'missing'
            else:
                data_quality['margin_state'] = 'empty_response'
                df['Margin_Balance_Raw'] = np.nan
        except Exception as e:
            data_quality['margin_state'] = 'network_error'
            df['Margin_Balance_Raw'] = np.nan

        time.sleep(random.uniform(0.2, 0.6)) # 防火牆緩衝

        # 3. 營收資料
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
            pass

        time.sleep(random.uniform(0.2, 0.6)) # 防火牆緩衝

        # 4. 集保戶股權分散表 (TDCC)
        try:
            tdcc_start = (now - timedelta(days=180)).strftime("%Y-%m-%d")
            tdcc_raw = self.dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date=tdcc_start, end_date=fm_end_date)

            if tdcc_raw is not None and not tdcc_raw.empty:
                cols_lower = [c.lower() for c in tdcc_raw.columns]
                tdcc_raw.columns = cols_lower

                if 'holdingshareslevel' in cols_lower: lvl_col = 'holdingshareslevel'
                elif 'size' in cols_lower: lvl_col = 'size'
                else: lvl_col = cols_lower[2]

                tdcc_raw['date'] = pd.to_datetime(tdcc_raw['date'])
                tdcc_raw['level'] = tdcc_raw[lvl_col].astype(str).str.strip()

                tdcc_raw['hold_shares'] = pd.to_numeric(tdcc_raw['hold_shares'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                tdcc_raw['percent'] = pd.to_numeric(tdcc_raw['percent'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

                grouped = tdcc_raw.groupby('date')
                records = []

                for d, grp in grouped:
                    valid_levels = [str(i) for i in range(1, 16)]
                    total_shares = grp[grp['level'].isin(valid_levels)]['hold_shares'].sum()

                    if total_shares == 0: continue

                    retail_levels = [str(i) for i in range(1, 10)]
                    retail_pct = grp[grp['level'].isin(retail_levels)]['percent'].sum()

                    cap_size = 'Small_Cap' if total_shares < 200000000 else 'Large_Cap'

                    if cap_size == 'Small_Cap':
                        whale_pct = grp[grp['level'].isin(['12','13','14','15'])]['percent'].sum()
                    else:
                        whale_pct = grp[grp['level'].isin(['15'])]['percent'].sum()

                    records.append({
                        'date': d, 'Total_Shares': total_shares, 'Cap_Size': cap_size,
                        'Retail_Pct': retail_pct, 'Whale_Pct': whale_pct
                    })

                if records:
                    tdcc_df = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
                    data_quality['tdcc_latest_date'] = tdcc_df.iloc[-1]['date'].strftime("%Y-%m-%d")
                else:
                    data_quality['errors'].append("[TDCC] 級距解析後無有效記錄")
            else:
                data_quality['errors'].append("[TDCC] API回傳空表或無資料")
        except Exception as e:
            data_quality['errors'].append(f"[TDCC_Error] 集保解析例外: {str(e)}")

        return df, target_code, data_quality, rev_df, tdcc_df

    def load_market(self, target_code, latest_stock_date):
        # 🌟 V25.2 強化：OTC 指數斷更備援機制
        mkt_ticker = "^TWOII" if target_code.endswith(".TWO") else "^TWII"
        mkt = yf.Ticker(mkt_ticker).history(period="2y", auto_adjust=True)

        if mkt is not None and not mkt.empty and mkt.index.tz is not None:
            mkt.index = mkt.index.tz_convert('Asia/Taipei').tz_localize(None)

        if mkt_ticker == "^TWOII":
            if mkt is None or mkt.empty or mkt.index[-1].strftime("%Y-%m-%d") < latest_stock_date:
                mkt = yf.Ticker("^TWII").history(period="2y", auto_adjust=True)
                if mkt is not None and not mkt.empty and mkt.index.tz is not None:
                    mkt.index = mkt.index.tz_convert('Asia/Taipei').tz_localize(None)

        if mkt is None or mkt.empty:
            raise ValueError("[empty_response] 大盤資料獲取失敗或回傳空表")
        if isinstance(mkt.columns, pd.MultiIndex): mkt.columns = mkt.columns.get_level_values(0)

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

        high_low_diff = df["High"] - df["Low"]
        vsa_raw = (df["Volume"] / df["VOL20_PRIOR"].replace(0, 1).fillna(1)) / (high_low_diff / df["ATR14"].replace(0, 0.01)).replace(0, 0.01)
        df["VSA_Ratio"] = np.where(high_low_diff == 0, 0.0, vsa_raw)
        df["VSA_Ratio"] = df["VSA_Ratio"].replace([np.inf, -np.inf], 0.0).fillna(0)

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


# ==========================================
# 模組 3: FishScoreEngine (🌟 V25.2: 1億流動性防呆)
# ==========================================
class FishScoreEngine:
    def calculate(self, data, custom_params=None):
        if custom_params is None: custom_params = {}
        df = data["df"]
        latest = df.iloc[-1]
        market_factor = data.get("market_factor", 1.0)
        score = 0
        health_checks = []
        has_error = False

        trend_score = 0
        if latest["Close"] > latest["MA20"]:
            trend_score += 10
            health_checks.append(("Close > MA20", True))
        else: health_checks.append(("Close > MA20", False))

        if latest["MA20"] > latest["MA60"]:
            trend_score += 10
            health_checks.append(("MA20 > MA60", True))
        else: health_checks.append(("MA20 > MA60", False))

        slope = data["ma20_slope"]
        if slope > 5: trend_score += 10
        elif slope > 3: trend_score += 7
        elif slope > 1: trend_score += 4
        score += trend_score

        rs_score = 0
        rs20, rs60 = data["rs20"], data["rs60"]
        rs_limit_high = custom_params.get("rs_limit_high", 0.10) * market_factor
        rs_limit_mid = (rs_limit_high / 2.0)
        if rs20 > rs_limit_high: rs_score += 10
        elif rs20 > rs_limit_mid: rs_score += 7
        elif rs20 > 0: rs_score += 4

        if rs60 > rs_limit_high: rs_score += 10
        elif rs60 > rs_limit_mid: rs_score += 7
        elif rs60 > 0: rs_score += 4

        health_checks.append(("RS20 > 0 (動態門檻校準)", rs20 > 0))
        health_checks.append(("RS60 > 0", rs60 > 0))
        score += rs_score

        vwap_score = 0
        if latest["Close"] > latest["VWAP60"]:
            adv = (latest["Close"] - latest["VWAP60"]) / latest["VWAP60"]
            if adv > 0.10: vwap_score += 15
            elif adv > 0.05: vwap_score += 10
            else: vwap_score += 5
            health_checks.append(("Close > VWAP60代理", True))
        else: health_checks.append(("Close > VWAP60代理", False))
        score += vwap_score

        try:
            prev_bandwidth_min = df["Bandwidth"].shift(1).tail(20).min()
            prev_bandwidth = df["Bandwidth"].shift(1).iloc[-1]
            is_bb_squeeze = prev_bandwidth <= (prev_bandwidth_min * 1.05) if prev_bandwidth_min > 0 else False
            if is_bb_squeeze and latest["Close"] > df["UpperBB"].shift(1).iloc[-1]:
                score += 15
                health_checks.append(("布林極限壓縮後突破上軌", True))
            else: health_checks.append(("布林極限壓縮後突破上軌", False))
        except Exception:
            health_checks.append(("布林極限壓縮後突破上軌", "Error"))
            has_error = True

        volume_score = 0
        vol_breakout_limit = max(1.05, min(1.25, 1.2 * market_factor))
        prev_vol20 = df["VOL20_PRIOR"].iloc[-1]

        if latest["Volume"] > prev_vol20 * vol_breakout_limit: volume_score += 8
        if latest["Volume"] < prev_vol20 and latest["Close"] > latest["MA20"]:
            volume_score += 7
            health_checks.append(("量縮不跌", True))
        else: health_checks.append(("量縮不跌", False))
        score += volume_score

        market_status = data["market_status"]
        if market_status == "Bull":
            score += 10
            health_checks.append(("大盤濾網(多頭)", True))
        elif market_status == "Neutral":
            score += 5
            health_checks.append(("大盤濾網(震盪)", True))
        elif market_status in ["Unknown", "Stale"]:
            health_checks.append(("大盤濾網(資料缺失/過舊)", "Error"))
            has_error = True
        else:
            health_checks.append(("大盤濾網(空頭)", False))

        if latest["Close"] * prev_vol20 > 100000000:
            score += 10
            health_checks.append(("日均成交額大於1億", True))
        else: health_checks.append(("日均成交額大於1億", False))

        score = min(100, max(0, score))
        grade = "S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D"
        trend_status = "強勢" if trend_score >= 25 else "整理" if trend_score >= 15 else "轉弱"
        rs_status = "相對大盤強勢" if rs_score >= 14 else "與大盤同步" if rs_score >= 7 else "相對弱勢"
        chip_status = "換手安定" if vwap_score >= 10 else "換手震盪" if vwap_score >= 5 else "鬆動"

        error_details = []
        if has_error:
            error_details.append(f"[Fish_Error] 大盤狀態 {market_status} 或布林通道運算失敗")

        return {
            "fish_score": round(score), "health_grade": grade,
            "trend_status": trend_status, "rs_status": rs_status, "chip_status": chip_status,
            "health_checks": health_checks, "has_error": has_error, "error_details": error_details
        }


# ==========================================
# 模組 4: RetreatScoreEngine
# ==========================================
class RetreatScoreEngine:
    def calculate(self, data, custom_params=None):
        if custom_params is None: custom_params = {}
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        retreat_checks = []
        error_details = []

        vol_breakout_limit = custom_params.get("retreat_vol_breakout", 3.0)
        bias_limit = custom_params.get("bias20_limit", 20)
        drop_tolerance = custom_params.get("drop_tolerance", -0.05)

        prev_vol20 = df["VOL20_PRIOR"].iloc[-1]
        vwap60 = float(latest.get("VWAP60", df["MA60"].iloc[-1]))
        cost_distance = ((latest["Close"] - vwap60) / vwap60 * 100) if vwap60 > 0 else 0

        data_quality = data.get("data_quality", {})
        inst_state = data_quality.get("inst_state")
        is_inst_complete = (inst_state == 'complete')

        grp1_score = 0
        try:
            price_change = (latest["Close"] - prev["Close"]) / prev["Close"]
            is_volume_high = latest["Volume"] > prev_vol20 * vol_breakout_limit
            is_price_stagnant = price_change < 0.02
            memory_triggered = False

            for i in range(max(0, len(df)-11), len(df)-1):
                if df.iloc[i]["Volume"] > df["VOL20_PRIOR"].iloc[i] * vol_breakout_limit:
                    if latest["Close"] < df.iloc[i]["Low"]: memory_triggered = True; break

            vol_str = "高檔爆量且已確認法人大賣" if is_inst_complete else "高檔爆量(法人資料未齊，無法確認)"

            if (is_volume_high and is_price_stagnant) or memory_triggered:
                if cost_distance > 5.0:
                    if is_inst_complete:
                        if latest.get("Inst_NetBuy", 0) < 0 or memory_triggered:
                            grp1_score += 45
                            retreat_checks.extend([(vol_str, True), ("爆量不漲", True)])
                        else:
                            grp1_score += 25
                            retreat_checks.extend([(vol_str, False), ("爆量不漲", True)])
                    else:
                        grp1_score += 25
                        retreat_checks.extend([(vol_str, "Unknown"), ("爆量不漲", True)])
                else: retreat_checks.extend([(f"{vol_str}(底部換手不扣分)", False if is_inst_complete else "Unknown"), ("爆量不漲(底部換手)", False)])
            else: retreat_checks.extend([(vol_str, False if is_inst_complete else "Unknown"), ("爆量不漲", False)])
        except Exception as e:
            retreat_checks.extend([(f"高檔爆量且法人大賣", "Error"), ("爆量不漲", "Error")])
            error_details.append(f"[Retreat_Vol] {str(e)}")

        try:
            vsa_ratio = float(latest.get("VSA_Ratio", 0.0))
            if vsa_ratio >= 2.5 and cost_distance > 15.0:
                grp1_score += 35
                retreat_checks.append(("【VSA高檔派發】天量小震幅滯漲", True))
            else: retreat_checks.append(("【VSA高檔派發】天量小震幅滯漲", False))
        except Exception as e:
            retreat_checks.append(("【VSA高檔派發】天量小震幅滯漲", "Error"))
            error_details.append(f"[Retreat_VSA] {str(e)}")

        try:
            if latest["Volume"] > prev_vol20 * 2 and latest["Raw_Close"] < latest["Raw_Open"]:
                grp1_score += 30
                retreat_checks.append(("爆量長黑", True))
            else: retreat_checks.append(("爆量長黑", False))
        except Exception as e:
            retreat_checks.append(("爆量長黑", "Error"))
            error_details.append(f"[Retreat_Black] {str(e)}")

        try:
            high_p, low_p, open_p, close_p = float(latest["Raw_High"]), float(latest["Raw_Low"]), float(latest["Raw_Open"]), float(latest["Raw_Close"])
            if (high_p - low_p) > 0 and ((high_p - max(close_p, open_p)) / (high_p - low_p)) > 0.5 and float(latest["Volume"]) > float(df["VOL5_PRIOR"].iloc[-1] * 1.3):
                grp1_score += 20
                retreat_checks.append(("高檔遭遇賣壓(長上影警報)", True))
            else: retreat_checks.append(("高檔遭遇賣壓(長上影警報)", False))
        except Exception as e:
            retreat_checks.append(("高檔遭遇賣壓(長上影警報)", "Error"))
            error_details.append(f"[Retreat_Shadow] {str(e)}")

        grp1_score = min(50, grp1_score)

        grp2_score = 0
        try:
            if latest["Close"] > latest["UpperBB"] and prev["Close"] > prev["UpperBB"] and latest["Raw_Close"] < latest["Raw_Open"]:
                grp2_score += 20
                retreat_checks.append(("連續觸及布林上軌且收黑(均值回歸)", True))
            else: retreat_checks.append(("連續觸及布林上軌且收黑(均值回歸)", False))
        except Exception as e:
            retreat_checks.append(("連續觸及布林上軌且收黑(均值回歸)", "Error"))
            error_details.append(f"[Retreat_BB] {str(e)}")

        try:
            if latest["Close"] >= df["Close"].tail(20).max() * 0.98 and latest.get("CMF", 0) < -0.05:
                grp2_score += 20
                retreat_checks.append(("CMF資金流出(真實量價背離)", True))
            else: retreat_checks.append(("CMF資金流出(真實量價背離)", False))
        except Exception as e:
            retreat_checks.append(("CMF資金流出(真實量價背離)", "Error"))
            error_details.append(f"[Retreat_CMF] {str(e)}")

        bias_str = f"正乖離大(>{bias_limit}%)且破線"
        try:
            bias20 = ((latest["Close"] - df["MA20"].iloc[-1]) / df["MA20"].iloc[-1]) * 100
            if bias20 > bias_limit and latest["Close"] < df["MA5"].iloc[-1]:
                grp2_score += 20
                retreat_checks.append((bias_str, True))
            else: retreat_checks.append((bias_str, False))
        except Exception as e:
            retreat_checks.append((bias_str, "Error"))
            error_details.append(f"[Retreat_Bias] {str(e)}")

        grp2_score = min(40, grp2_score)

        grp3_score = 0
        try:
            if (df["Close"].tail(3) < df["VWAP60"].tail(3)).all():
                grp3_score += 40
                retreat_checks.append(("跌破VWAP60代理", True))
            else: retreat_checks.append(("跌破VWAP60代理", False))
        except Exception as e:
            retreat_checks.append(("跌破VWAP60代理", "Error"))
            error_details.append(f"[Retreat_VWAP] {str(e)}")

        try:
            if (df["Close"].tail(3) < df["MA20"].tail(3)).all():
                grp3_score += 20
                retreat_checks.append(("跌破MA20", True))
            else: retreat_checks.append(("跌破MA20", False))
        except Exception as e:
            retreat_checks.append(("跌破MA20", "Error"))
            error_details.append(f"[Retreat_MA20] {str(e)}")

        drop_pct_val = abs(drop_tolerance) * 100
        drop_str = f"單日重挫(跌幅>={drop_pct_val:.0f}%)"
        try:
            if (latest["Close"] - prev["Close"]) / prev["Close"] <= drop_tolerance:
                grp3_score += 40
                retreat_checks.append((drop_str, True))
            else: retreat_checks.append((drop_str, False))
        except Exception as e:
            retreat_checks.append((drop_str, "Error"))
            error_details.append(f"[Retreat_Drop] {str(e)}")

        grp3_score = min(50, grp3_score)

        retreat_score = min(100, grp1_score + grp2_score + grp3_score)

        has_error = len(error_details) > 0
        if has_error: risk_status = "系統計算異常(Unknown)"
        elif retreat_score >= 80: risk_status = "主力撤退"
        elif retreat_score >= 60: risk_status = "高機率主力撤退"
        elif retreat_score >= 40: risk_status = "疑似出貨"
        elif retreat_score >= 20: risk_status = "提高警覺"
        else: risk_status = "低"

        if has_error: retreat_comment = "安全模組計算發生異常，防禦失效"
        elif retreat_score >= 80: retreat_comment = "主力撤退訊號明顯,建議盡速避險"
        elif retreat_score >= 60: retreat_comment = "疑似開始出貨,建議密切觀察"
        elif retreat_score >= 40: retreat_comment = "籌碼有鬆動跡象,提防拉高倒貨"
        elif retreat_score >= 20: retreat_comment = "部分撤退訊號出現,需提高警覺"
        else: retreat_comment = "尚未發現嚴重出貨訊號"

        return {
            "retreat_score": round(retreat_score), "risk_status": risk_status,
            "retreat_comment": retreat_comment, "retreat_checks": retreat_checks,
            "has_error": has_error, "error_details": error_details
        }


# ==========================================
# 模組 5: WhaleEnduranceEngine
# ==========================================
class WhaleEnduranceEngine:
    def calculate(self, data):
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        score = 50
        messages = []
        has_error = False
        error_details = []

        try:
            day_range = latest['Raw_High'] - latest['Raw_Low']
            if day_range > 0:
                close_pos = (latest['Raw_Close'] - latest['Raw_Low']) / day_range
                if close_pos > 0.8:
                    score += 10
                    messages.append("[型態代理] 強勢收紅(買盤意願延續至收盤)")
                elif close_pos < 0.2:
                    score -= 10
                    messages.append("[型態代理] 弱勢收低(上方賣壓沉重,防低開)")

            is_limit_line = (latest['Raw_High'] == latest['Raw_Low'] == latest['Raw_Close'])
            is_limit_up = latest['Raw_Close'] >= (prev['Raw_Close'] * 1.095)

            if is_limit_line and latest['Raw_Close'] > prev['Raw_Close']:
                 score += 15
                 messages.append("[型態代理] 強勢漲停一字線(極度鎖碼)")
            elif is_limit_line and latest['Raw_Close'] < prev['Raw_Close']:
                 score -= 15
                 messages.append("[型態代理] 弱勢跌停一字線(極度恐慌)")
            elif is_limit_up:
                if latest['Volume'] < (df['VOL5_PRIOR'].iloc[-1] * 0.7):
                    score += 10
                    messages.append("[型態代理] 漲停量縮鎖死(籌碼安定)")
                else:
                    score -= 15
                    messages.append("[型態代理] 量價背離(上漲無量,續航力存疑)")

            avg_range = (df['Raw_High'] - df['Raw_Low']).tail(5).mean()
            if avg_range > 0 and day_range < (avg_range * 0.6) and latest['Volume'] < df['VOL20_PRIOR'].iloc[-1]:
                if latest['Close'] > df['MA5'].iloc[-1]:
                    score += 15
                    messages.append("[型態代理] 波動壓縮(蓄勢待發)")

            df_last_5 = df.tail(5)
            up_vol = df_last_5[df_last_5['Raw_Close'] > df_last_5['Raw_Open']]['Volume'].sum()
            down_vol = df_last_5[df_last_5['Raw_Close'] < df_last_5['Raw_Open']]['Volume'].sum()

            if up_vol > down_vol * 1.5:
                score += 15
                messages.append("[純量價] 近期買盤量遠大於賣盤量(買氣偏多)")
            elif down_vol > up_vol * 1.5:
                score -= 15
                messages.append("[純量價] 近期賣盤量遠大於買盤量(高檔賣壓重)")
        except Exception as e:
            has_error = True
            error_details.append(f"[Endurance_Basic] {str(e)}")

        try:
            df_past_5 = df.iloc[-6:-1]
            has_extreme_shrink = (df_past_5['Volume'] < (df['VOL20_PRIOR'].iloc[-6:-1] * 0.4)).any()
            is_volume_explosion = (latest['Volume'] > (df['VOL5_PRIOR'].iloc[-1] * 2)) and (latest['Raw_Close'] > latest['Raw_Open'])
            if has_extreme_shrink and is_volume_explosion:
                score += 20
                messages.append("[型態代理] 極限壓縮爆發(量縮至極致後爆量紅K)")
        except Exception as e:
            has_error = True
            error_details.append(f"[Endurance_Breakout] {str(e)}")

        try:
            vsa_ratio = float(latest.get("VSA_Ratio", 0.0))
            vwap60 = float(latest.get("VWAP60", df["MA60"].iloc[-1]))
            cost_distance = ((latest["Close"] - vwap60) / vwap60 * 100) if vwap60 > 0 else 0

            if vsa_ratio >= 2.5 and cost_distance <= 5.0 and latest["Raw_Close"] >= latest["Raw_Open"]:
                score += 25
                messages.append("【VSA微結構代理】底部爆量吸收(大單限價吃貨推論)")
        except Exception as e:
            has_error = True
            error_details.append(f"[Endurance_VSA] {str(e)}")

        score = max(0, min(100, score))
        if has_error: status = "系統計算異常(未完成計算)"
        elif score >= 80: status = "燃料充沛(蓄勢發動)"
        elif score >= 60: status = "震盪整理(多空激戰)"
        elif score >= 40: status = "動能衰退(高位背離)"
        else: status = "燃料耗盡(賣壓湧現)"

        return {
            "endurance_score": round(score), "endurance_status": status, "endurance_messages": messages,
            "has_error": has_error, "error_details": error_details
        }


# ==========================================
# 模組 6: FundamentalEngine
# ==========================================
class FundamentalEngine:
    def calculate(self, rev_df, current_date):
        if rev_df is None or rev_df.empty:
            return {
                "fund_score": 0, "fund_label": "【無營收資料】",
                "yoy": 0, "mom": 0, "is_high": False, "fund_state": "missing",
                "is_pit_embargo": False
            }

        rev_df['revenue'] = pd.to_numeric(rev_df['revenue'], errors='coerce')
        rev_df = rev_df.dropna(subset=['revenue'])

        if len(rev_df) < 2:
            return {
                "fund_score": 0, "fund_label": "【營收資料不足】",
                "yoy": 0, "mom": 0, "is_high": False, "fund_state": "insufficient",
                "is_pit_embargo": False
            }

        latest_rev = rev_df.iloc[-1]['revenue']
        prev_rev = rev_df.iloc[-2]['revenue']
        latest_year = rev_df.iloc[-1]['revenue_year']
        latest_month = rev_df.iloc[-1]['revenue_month']

        current_dt = pd.to_datetime(current_date)
        months_diff = (current_dt.year - latest_year) * 12 + (current_dt.month - latest_month)
        is_stale = months_diff > 2

        is_pit_embargo = False
        if current_dt.day <= 10 and months_diff == 1:
            is_pit_embargo = True

        last_year_df = rev_df[(rev_df['revenue_year'] == latest_year - 1) & (rev_df['revenue_month'] == latest_month)]
        yoy = 0.0
        has_yoy = False
        if not last_year_df.empty:
            ly_rev = last_year_df.iloc[-1]['revenue']
            if ly_rev > 0:
                yoy = ((latest_rev - ly_rev) / ly_rev) * 100
                has_yoy = True

        mom = 0.0
        expected_prev_month = 12 if latest_month == 1 else latest_month - 1
        expected_prev_year = latest_year - 1 if latest_month == 1 else latest_year
        actual_prev_month = rev_df.iloc[-2]['revenue_month']
        actual_prev_year = rev_df.iloc[-2]['revenue_year']

        is_mom_valid = (expected_prev_month == actual_prev_month and expected_prev_year == actual_prev_year)

        if is_mom_valid and prev_rev > 0:
            mom = ((latest_rev - prev_rev) / prev_rev) * 100

        is_high = False
        if len(rev_df) > 0:
            recent_max = rev_df['revenue'].tail(24).max()
            if latest_rev >= recent_max * 0.99:
                is_high = True

        score = 0
        if yoy >= 30: score += 20
        elif yoy >= 10: score += 10
        if mom > 0: score += 10
        if is_high: score += 10

        label_parts = []
        if has_yoy:
            if yoy >= 30: label_parts.append("YoY高爆發")
            elif yoy >= 10: label_parts.append("YoY穩健")
            elif yoy < 0: label_parts.append("YoY衰退")
        else: label_parts.append("YoY無法比較")

        if is_mom_valid:
            if mom > 0: label_parts.append("MoM成長")
            elif mom < 0: label_parts.append("MoM衰退")
        else: label_parts.append("MoM缺月")

        if is_high: label_parts.append("創近期新高")

        is_dual_growth = has_yoy and is_mom_valid and (yoy > 0) and (mom > 0)
        embargo_warn = "(保守推估未全數公告)" if is_pit_embargo else ""

        if is_stale:
            fund_label = f"【營收資料過舊】(最後更新 {latest_year}/{latest_month})"
            fund_state = "stale"
            score = 0
            is_dual_growth = False
        elif not has_yoy or not is_mom_valid:
            fund_label = f"【營收期間不連續/不足】({'+'.join(label_parts)})"
            fund_state = "insufficient"
            score = 0
            is_dual_growth = False
        else:
            fund_state = "complete"
            if is_dual_growth and yoy >= 10:
                fund_label = f"【營收雙增護體】{embargo_warn}({'+'.join(label_parts)})"
            elif yoy >= 10:
                mom_str = "MoM回落" if mom <= 0 else ""
                fund_label = f"【YoY成長，{mom_str}】{embargo_warn}({'+'.join(label_parts)})"
            elif yoy < 0 and mom > 0:
                fund_label = f"【谷底回溫/轉機】{embargo_warn}({'+'.join(label_parts)})"
            else:
                fund_label = f"【營收動能疲弱】{embargo_warn}({'+'.join(label_parts)})"

        return {
            "fund_score": min(40, score),
            "fund_label": fund_label,
            "yoy": round(yoy, 2) if has_yoy else "N/A",
            "mom": round(mom, 2) if is_mom_valid else "N/A",
            "is_high": is_high,
            "is_dual_growth": is_dual_growth,
            "fund_state": fund_state,
            "is_pit_embargo": is_pit_embargo
        }


# ==========================================
# 模組 7: FishPositionEngine (🌟 V25.2: 動態防守與目標價)
# ==========================================
class FishPositionEngine:
    def calculate(self, data, fish, retreat, warning, endurance, defense, fundamental):
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        fish_score = fish["fish_score"]
        retreat_score = retreat["retreat_score"]
        warning_score = warning["warning_score"]
        rs20, rs60, slope = data['rs20'], data["rs60"], data["ma20_slope"]

        fund_score = fundamental.get("fund_score", 0)
        is_dual_growth = fundamental.get("is_dual_growth", False)
        yoy_val = fundamental.get("yoy", 0)
        yoy = float(yoy_val) if yoy_val != "N/A" else 0.0
        is_pit_embargo = fundamental.get("is_pit_embargo", False)

        all_errors = data.get("data_quality", {}).get("errors", [])
        fatal_errors = [e for e in all_errors if "TDCC" not in str(e)]
        data_layer_errors = len(fatal_errors) > 0

        has_sys_error = (
            data_layer_errors or
            fish.get("has_error", False) or
            retreat.get("has_error", False) or
            warning.get("has_error", False) or
            endurance.get("has_error", False) or
            defense.get("has_error", False)
        )

        try: bias20 = ((latest["Close"] - latest["MA20"]) / latest["MA20"]) * 100
        except Exception as e:
            bias20 = 0
            has_sys_error = True

        if retreat_score >= 80: position, progress = "魚尾區", 85
        elif retreat_score >= 60: position, progress = "出貨區", 100
        elif fish_score >= 80 and bias20 > 15: position, progress = "主升中後段", 70
        elif fish_score >= 80 and rs20 > 0 and rs60 > 0 and bias20 <= 15: position, progress = "主升初期", 50
        elif fish_score >= 70 and slope > 1: position, progress = "魚頭形成期", 30
        else: position, progress = "築底階段", 10

        if progress <= 30: base_score = 40
        elif progress == 50: base_score = 60
        elif progress == 70: base_score = 30
        else: base_score = 10

        if progress >= 30: opportunity_score = min(100, base_score + fund_score)
        else: opportunity_score = base_score

        tech_veto = (fish_score < 60 or retreat_score >= 40 or warning_score >= 30)

        data_quality = data.get("data_quality", {})
        inst_state = data_quality.get('inst_state', 'missing')
        margin_state = data_quality.get('margin_state', 'missing')
        market_status = data.get('market_status', 'Unknown')
        fund_state = fundamental.get('fund_state', 'missing')
        is_intraday = data_quality.get('is_intraday', False)

        margin_warning_valid = False
        margin_streak = 0
        is_margin_complete_3d = False

        if margin_state == 'complete':
            recent_3_margin = df['Margin_Balance_Raw'].dropna().tail(3)
            if len(recent_3_margin) == 3 and (recent_3_margin.index == df.index[-3:]).all():
                margin_warning_valid = True
                is_margin_complete_3d = True

            valid_margin = df['Margin_Balance_Raw'].dropna()
            if len(valid_margin) > 1:
                diffs = valid_margin.diff().dropna()
                for val in diffs.iloc[::-1]:
                    if val > 0: margin_streak += 1
                    else: break

        if not margin_warning_valid: margin_streak = 0

        is_inst_complete = (inst_state == 'complete')
        is_inst_partial = (inst_state == 'partial')

        k_date = data_quality.get('latest_price_date')
        i_date = data_quality.get('inst_latest_date')
        m_date = data_quality.get('margin_latest_date')
        latest_market_date = data_quality.get('mkt_latest_date', '無')

        is_fresh_and_complete = (
            is_inst_complete and
            is_margin_complete_3d and
            (fund_state == 'complete') and
            (market_status not in ['Unknown', 'Stale']) and
            (k_date == i_date == m_date == latest_market_date)
        )

        missing_msg = []
        if is_inst_partial: missing_msg.extend(data_quality.get('missing_inst_parts', []))
        if not is_margin_complete_3d: missing_msg.append("融資不連貫")
        if fund_state != 'complete': missing_msg.append("營收異常或過舊")
        if market_status in ['Unknown', 'Stale']: missing_msg.append("大盤狀態異常")
        if k_date != latest_market_date or i_date != latest_market_date or m_date != latest_market_date:
            missing_msg.append("基準日未對齊大盤")

        missing_str = "缺" + "+".join(missing_msg) if missing_msg else "資料齊全"
        margin_str = f"(融資連買{margin_streak}天)" if margin_streak > 0 else ""

        if not is_fresh_and_complete and opportunity_score > 0:
            opportunity_score = int(opportunity_score * 0.5)

        if opportunity_score >= 80: opportunity_level = "*****"
        elif opportunity_score >= 60: opportunity_level = "****"
        elif opportunity_score >= 40: opportunity_level = "***"
        elif opportunity_score >= 20: opportunity_level = "**"
        else: opportunity_level = "*"

        if not is_fresh_and_complete and not has_sys_error and not tech_veto and not is_intraday:
            opportunity_level = f"降級({opportunity_level})"

        position_comment = ""
        if has_sys_error:
            candidate_status = "觀察 - 系統計算異常"
            opportunity_score = 0
            opportunity_level = "-"
            position_comment = "底層安全模組例外，系統強制拒絕評估"
        elif tech_veto:
            candidate_status = "排除"
            opportunity_score = 0
            opportunity_level = "-"
            position_comment = "風險閘門未通過，不列入候選"
        elif is_intraday or inst_state in ['missing', 'schema_error', 'error']:
            candidate_status = "技術觀察(缺資料)"
            opportunity_score = 0
            opportunity_level = "-"
            position_comment = "剛脫離整理區,仍在築底階段" if progress <= 20 else "魚頭形成中,適合開始觀察"
            if progress > 40: position_comment = "技術趨勢成型,適合開始觀察"
            position_comment += " [缺乏當日籌碼]"
        else:
            if is_fresh_and_complete:
                candidate_status = "候選 - 完整大局"
            else:
                candidate_status = "觀察 - 籌碼/基本面未齊"

            if progress <= 20: position_comment = "剛脫離整理區,仍在築底階段"
            elif progress <= 40: position_comment = "魚頭形成中,適合開始觀察"
            elif progress <= 60: position_comment = "進入主升初期,趨勢開始加速"
            elif progress <= 80: position_comment = "主升中後段,報酬與風險同步增加"
            elif progress <= 90: position_comment = "魚尾區,追價風險提高"
            else: position_comment = "疑似出貨區,需提高警覺"

            position_comment = f"【{candidate_status}】 [{missing_str}] {margin_str} " + position_comment

        current_price_adj = float(latest["Close"])
        current_price_raw = float(latest.get("Raw_Close", current_price_adj))
        atr14 = float(latest.get("ATR14", current_price_adj * 0.03))

        vwap_breakout, close_pos, vol_shrink_standard, extreme_vol_shrink, near_ma10, near_ma20 = False, 0.5, False, False, False, False

        try:
            if retreat_score < 60:
                ma10, ma20 = float(latest["MA10"]), float(latest["MA20"])
                near_ma10 = (abs(current_price_adj - ma10) / ma10 < 0.02) and (current_price_adj > ma10 * 0.99)
                near_ma20 = (abs(current_price_adj - ma20) / ma20 < 0.02) and (current_price_adj > ma20 * 0.99)
                vol_shrink_standard = float(latest["Volume"]) < float(prev["Volume"]) * 0.5
                extreme_vol_shrink = float(latest["Volume"]) < float(df["VOL5_PRIOR"].iloc[-1]) * 0.7
                day_range = float(latest["Raw_High"]) - float(latest["Raw_Low"])
                close_pos = (current_price_raw - float(latest["Raw_Low"])) / day_range if day_range > 0 else 0.5
                vwap_breakout = (current_price_adj > float(latest["Typical_Price"])) and (float(prev["Close"]) <= float(prev["Typical_Price"]))
        except Exception as e:
            has_sys_error = True
            position_comment = f"【安全模組例外】價格判斷失敗: {str(e)}"
            candidate_status = "觀察 - 系統計算異常"

        trust_buy = df.get("Trust_NetBuy", pd.Series([0])).tail(3).sum() > 0
        co_buy = trust_buy and (df.get("Foreign_NetBuy", pd.Series([0])).tail(3).sum() > 0)

        vwap60_adj = float(latest.get("VWAP60", df["MA60"].iloc[-1]))
        if pd.isna(vwap60_adj) or vwap60_adj <= 0: vwap60_adj = float(latest["MA60"]) if not pd.isna(latest["MA60"]) else current_price_adj

        cost_gap = current_price_adj - vwap60_adj
        cost_distance = (cost_gap / vwap60_adj * 100) if vwap60_adj > 0 else 0

        if cost_distance > 20: heat_level = "過熱"
        elif cost_distance > 10: heat_level = "偏熱"
        elif cost_distance < 0: heat_level = "水下(套牢)"
        else: heat_level = "正常"

        can_relax_atr = is_dual_growth and (not is_pit_embargo) and (yoy >= 10) and (progress >= 30) and not tech_veto and is_fresh_and_complete

        if can_relax_atr:
            baseline = float(latest["MA10"]) if not pd.isna(latest["MA10"]) else current_price_adj
            defensive_price_adj = baseline - (2.2 * atr14)
            if heat_level == "過熱": max_tolerance = 12.0
            elif heat_level == "偏熱": max_tolerance = 15.0
            else: max_tolerance = 18.0
        else:
            ma20_val = float(latest["MA20"]) if not pd.isna(latest["MA20"]) else current_price_adj
            valid_supports = [s for s in [ma20_val, vwap60_adj] if s < current_price_adj]
            baseline = max(valid_supports) if valid_supports else current_price_adj
            defensive_price_adj = baseline - (1.8 * atr14)
            if heat_level == "過熱": max_tolerance = 8.0
            elif heat_level == "偏熱": max_tolerance = 12.0
            else: max_tolerance = 15.0

        ratio = current_price_raw / current_price_adj if current_price_adj > 0 else 1.0
        defensive_price_raw = defensive_price_adj * ratio

        is_defense_valid = True
        if pd.isna(defensive_price_raw) or defensive_price_raw <= 0:
            defensive_price_exec = 0.0
            defensive_status_text = "無有效防守價 (負值或異常)"
            is_defense_valid = False
        elif ((current_price_raw - defensive_price_raw) / current_price_raw * 100) > max_tolerance:
            defensive_price_exec = 0.0
            defensive_status_text = f"無有效防守價 (防守空間 > {max_tolerance}%)"
            is_defense_valid = False
        else:
            defensive_price_exec = WhaleTools.round_tick(defensive_price_raw, 'floor')
            defensive_status_text = "ATR動態基準計算"

        is_evaluable = False
        if (candidate_status == "候選 - 完整大局") and (not has_sys_error) and (not tech_veto) and is_defense_valid:
            is_evaluable = True

        if is_evaluable:
            if (near_ma10 or near_ma20) and (vol_shrink_standard or extreme_vol_shrink) and close_pos > 0.8:
                if vwap_breakout and co_buy and extreme_vol_shrink: position_comment = "[技術S級買點] 雙資合買極致量縮回測支撐,站上HLC/3代理!"
                elif vwap_breakout and co_buy: position_comment = "[技術S級買點] 雙資合買量縮回測,站上HLC/3代理!"
                elif vwap_breakout: position_comment = "[技術V轉買點] 量縮回測支撐且強勢越過HLC/3代理!"
                else: position_comment = "[洗盤觀察] 量縮回測均線且強勢收腳,大戶洗盤機率高"

        try:
            raw_vol_sum = df['Volume'].tail(60).sum()
            vwap60_raw = (df['Raw_Close'].tail(60) * df['Volume'].tail(60)).sum() / raw_vol_sum
        except Exception:
            vwap60_raw = current_price_raw

        atr14_raw = atr14 * ratio
        target_low_raw = vwap60_raw + (3 * atr14_raw)
        target_high_raw = vwap60_raw + (6 * atr14_raw)

        if current_price_raw >= target_low_raw:
            target_low_raw = current_price_raw + (1.5 * atr14_raw)
            target_high_raw = current_price_raw + (3.0 * atr14_raw)

        upside_low = ((target_low_raw - current_price_raw) / current_price_raw * 100) if current_price_raw > 0 else 0.0
        upside_high = ((target_high_raw - current_price_raw) / current_price_raw * 100) if current_price_raw > 0 else 0.0
        target_low_exec = WhaleTools.round_tick(target_low_raw, 'floor')
        target_high_exec = WhaleTools.round_tick(target_high_raw, 'ceil')

        e_score = max(0, min(100, endurance.get("endurance_score", 0) + data.get("chip_score", 0)))

        if defensive_price_exec <= 0 or not is_defense_valid:
            base_strategy = "【防守價失效/無防守】無法核算出合理的 ATR 防守區間或乖離過大，風險不可控"
        elif fish_score >= 70 and e_score <= 40:
            base_strategy = "【技術與籌碼背離】大趨勢偏多，但短線動能衰退，慎防獲利了結賣壓，切勿追高！"
        elif fish_score < 70 and (retreat_score >= 60 or warning_score >= 70) and e_score < 40:
            base_strategy = "【末升段誘多】高風險+低期望值(出貨與接刀跡象已現,切勿追高)"
        elif e_score <= 40 and retreat_score >= 60:
            base_strategy = "【短線籌碼潰散/破線危機】短線遭遇沉重賣壓,嚴格防守!"
        elif cost_distance > 25.0 and retreat_score <= 20 and fish_score >= 70 and e_score > 50:
            base_strategy = "【極端妖股】風險極端(正乖離極大!空手勿追,防守沿5日線)"
        elif fish_score >= 70 and (retreat_score <= 20 and warning_score < 30) and cost_distance <= max_tolerance and e_score >= 60 and fundamental.get('is_dual_growth', False):
            base_strategy = "【大局完整：營收雙增核心單】低風險+高成長(多方與基本面共振完好,可偏多波段操作)"
        elif fish_score >= 70 and (retreat_score <= 20 and warning_score < 30) and cost_distance <= max_tolerance and e_score >= 60:
            base_strategy = "【純技術波段單】低風險+高期望值(技術籌碼共振完好,可積極操作)"
        elif fish_score >= 60 and cost_distance <= 7.0 and e_score >= 60:
            base_strategy = "【初升段成型】趨勢轉強且風險低(結構初展端倪,可酌量佈局)"
        elif fish_score >= 60 and (retreat_score <= 20 and warning_score < 30) and cost_distance <= 8.0 and e_score >= 40:
            base_strategy = "【左側轉折單】低風險+高期望值(左側摸底試單,嚴守停損)"
        elif retreat_score >= 40 or warning_score >= 40:
            base_strategy = "【風險醞釀中】部分風險指標升高(高位鬆動跡象,建議減碼或觀望)"
        elif fish_score >= 60 and e_score < 60:
            base_strategy = "【技術偏多但動能不足】線型尚可但缺乏買盤點火,建議等待表態"
        else:
            base_strategy = "【震盪整理區】多空動能分歧且不明確(建議休養生息)"

        if market_status == 'Bear':
            base_strategy = f"【逆勢高風險】大盤空頭，請縮小部位！ " + base_strategy

        if candidate_status == "觀察 - 系統計算異常":
            strategy_profile = f"【安全模組異常】系統強制降級。純技術面研判：{base_strategy}"
        elif candidate_status == "【分析失敗】資料異常":
            strategy_profile = f"【系統防呆】資料嚴重異常。純技術面研判：{base_strategy}"
        elif candidate_status == "排除":
            strategy_profile = f"【風險閘門排除】不列入期望值評估。純技術面研判：{base_strategy}"
        elif not is_evaluable:
            strategy_profile = f"【{candidate_status}】缺乏大局資料。純技術面研判：{base_strategy}"
        else:
            strategy_profile = base_strategy

        return {
            "candidate_status": candidate_status, "fish_position": position, "progress": progress,
            "opportunity_score": round(opportunity_score), "opportunity_level": opportunity_level,
            "position_comment": position_comment, "strategy_profile": strategy_profile, "bias20": round(bias20, 2),
            "current_price": round(current_price_raw, 2), "vwap60": round(vwap60_raw, 2),
            "cost_distance": round(cost_distance, 2), "target_low": target_low_exec, "target_high": target_high_exec,
            "upside_low": round(upside_low, 1), "upside_high": round(upside_high, 1),
            "heat_level": heat_level, "defensive_price": defensive_price_exec, "defensive_status_text": defensive_status_text,
            "max_tolerance": max_tolerance, "is_evaluable": is_evaluable
        }


# ==========================================
# 模組 8: EarlyWarningEngine (🌟 V25.2: 放寬預警帶至10%)
# ==========================================
class EarlyWarningEngine:
    def calculate(self, data):
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        checks = []
        has_error = False
        error_details = []

        try:
            delta = df['Close'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)

            avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

            rs = avg_gain / avg_loss
            df['RSI'] = 100 - (100 / (1 + rs))

            df['RSI'] = np.where(avg_loss == 0, 100.0, df['RSI'])
            df['RSI'] = np.where((avg_loss == 0) & (avg_gain == 0), 50.0, df['RSI'])

            latest = df.iloc[-1]
            prev = df.iloc[-2]

        except Exception as e:
            df['RSI'] = np.nan
            error_details.append(f"RSI計算錯誤: {str(e)}")
            has_error = True

        recent_high = df['High'].tail(20).max()
        is_near_high = ((recent_high - latest['Close']) / latest['Close']) < 0.10

        grp1_score = 0
        try:
            if is_near_high and abs(latest['Raw_Close'] - latest['Raw_Open']) < abs(prev['Raw_Close'] - prev['Raw_Open']) and latest['Volume'] < prev['Volume']:
                grp1_score += 35
                checks.append(("高檔量縮且K線壓縮", True))
            else: checks.append(("高檔量縮且K線壓縮", False))
        except Exception as e:
            checks.append(("高檔量縮且K線壓縮", "Error"))
            error_details.append(f"[Warning_Vol] {str(e)}")
            has_error = True

        try:
            if 'Typical_Price' in df.columns and (df['Close'].tail(3) < df['Typical_Price'].tail(3)).sum() >= 2 and is_near_high:
                grp1_score += 20
                checks.append(("連續受制當日HLC/3代理線", True))
            else: checks.append(("連續受制當日HLC/3代理線", False))
        except Exception as e:
            checks.append(("連續受制當日HLC/3代理線", "Error"))
            error_details.append(f"[Warning_HLC3] {str(e)}")
            has_error = True

        try:
            if pd.isna(latest['RSI']):
                checks.append(("RSI動能頂背離現象", "Error"))
                has_error = True
            else:
                is_price_peak = latest['Close'] >= df['Close'].tail(15).max()
                prev_peaks = df.iloc[-25:-5][df.iloc[-25:-5]['Close'] >= df.iloc[-25:-5]['Close'].rolling(5).max()]
                if is_price_peak and not prev_peaks.empty:
                    prev_peak_rsi = prev_peaks.iloc[-1]['RSI']
                    if latest['RSI'] < prev_peak_rsi:
                        grp1_score += 30
                        checks.append(("RSI動能頂背離現象", True))
                    else: checks.append(("RSI動能頂背離現象", False))
                else: checks.append(("RSI動能頂背離現象", False))
        except Exception as e:
            checks.append(("RSI動能頂背離現象", "Error"))
            error_details.append(f"[Warning_RSI] {str(e)}")
            has_error = True

        try:
            macd_decelerating = (latest['MACD_Hist'] > 0) and (latest['MACD_Hist'] < prev['MACD_Hist']) and (prev['MACD_Hist'] < df.iloc[-3]['MACD_Hist'])
            if is_near_high and macd_decelerating:
                grp1_score += 30
                checks.append(("MACD紅柱連縮(上漲加速度反轉)", True))
            else: checks.append(("MACD紅柱連縮(上漲加速度反轉)", False))
        except Exception as e:
            checks.append(("MACD紅柱連縮(上漲加速度反轉)", "Error"))
            error_details.append(f"[Warning_MACD] {str(e)}")
            has_error = True

        grp1_score = min(60, grp1_score)

        grp2_score = 0
        data_quality = data.get("data_quality", {})
        margin_state = data_quality.get("margin_state", "missing")

        if margin_state != 'complete':
            checks.append(("融資餘額異常增加(散戶接刀)", "Unknown"))
        else:
            try:
                recent_3_raw = df['Margin_Balance_Raw'].dropna().tail(3)
                if len(recent_3_raw) == 3 and (recent_3_raw.index == df.index[-3:]).all():
                    margin_diff = recent_3_raw.diff().dropna()
                    if (margin_diff > 0).sum() >= 2:
                        checks.append(("融資餘額異常增加(散戶接刀)", True))
                        grp2_score += 40
                    else: checks.append(("融資餘額異常增加(散戶接刀)", False))
                else:
                    checks.append(("融資餘額異常增加(散戶接刀)", "Unknown"))
            except Exception as e:
                checks.append(("融資餘額異常增加(散戶接刀)", "Error"))
                error_details.append(f"[Warning_Margin] {str(e)}")
                has_error = True

        grp2_score = min(40, grp2_score)
        score = min(100, grp1_score + grp2_score)

        if has_error: status = "系統計算異常(Unknown)"
        elif score >= 70: status = "高度警戒(A轉風險極大或散戶接刀)"
        elif score >= 30: status = "動能衰退(提防拉高出貨)"
        else: status = "動能正常(未見明顯敗象)"

        return {
            "warning_score": score, "warning_status": status, "warning_checks": checks,
            "has_error": has_error, "error_details": error_details
        }


# ==========================================
# 模組 9: SmartMoneyDefenseEngine
# ==========================================
class SmartMoneyDefenseEngine:
    def calculate(self, data, **kwargs):
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        defense_score = 0
        signals = []
        has_error = False
        error_details = []

        try:
            if latest['Low'] < prev['Low'] and latest['Close'] > prev['Close']:
                defense_score += 30
                signals.append("【日線假破底翻紅形態】盤中破底但強勢拉回翻紅(誘空推論)")
        except Exception as e:
            has_error = True
            error_details.append(f"[Defense_Bottom] {str(e)}")

        try:
            vwap60 = float(df["VWAP60"].iloc[-1])
            if latest['Close'] < vwap60 * 1.01 and latest['Close'] > latest['Open']:
                if latest['Close'] > vwap60 * 0.99:
                    defense_score += 25
                    signals.append("【均價買盤支撐】回測60日加權均價代理重現買盤支撐")
        except Exception as e:
            has_error = True
            error_details.append(f"[Defense_VWAP] {str(e)}")

        try:
            day_range = latest['Raw_High'] - latest['Raw_Low']
            lower_shadow = min(latest['Raw_Open'], latest['Raw_Close']) - latest['Raw_Low']
            body = abs(latest['Raw_Close'] - latest['Raw_Open'])

            if day_range > 0 and lower_shadow > body * 2 and latest['Close'] > prev['Close']:
                defense_score += 20
                signals.append("【尾盤突襲/長下影線代理】下方接手力道強勁,收復日內跌幅")
        except Exception as e:
            has_error = True
            error_details.append(f"[Defense_Shadow] {str(e)}")

        try:
            recent_k = df.iloc[-5:-1]
            for i in range(len(recent_k)-1, -1, -1):
                idx = recent_k.index[i]
                k_day = recent_k.loc[idx]
                prev_k_day = df.loc[df.index[df.index.get_loc(idx)-1]]
                if k_day['Close'] > k_day['Open'] and k_day['Close'] > prev_k_day['Close'] * 1.04:
                    k_mid = (k_day['Close'] + k_day['Open']) / 2
                    if latest['Close'] < k_mid:
                        defense_score -= 30
                        signals.append(f"【跌破紅K中值】跌破近期長紅K一半,誘多推論,提防下殺")
                    else:
                        defense_score += 25
                        signals.append(f"【紅K中值防守】股價守穩近期長紅K一半,型態不破底")
                    break
        except Exception as e:
            has_error = True
            error_details.append(f"[Defense_RedK] {str(e)}")

        data_quality = data.get("data_quality", {})
        inst_valid = data_quality.get("inst_state") == 'complete'

        try:
            if inst_valid and 'Trust_NetBuy' in df.columns:
                recent_20 = df.tail(20)
                trust_buy_days = recent_20[recent_20['Trust_NetBuy'] > 0]
                if not trust_buy_days.empty:
                    total_trust_vol = trust_buy_days['Trust_NetBuy'].sum()
                    if total_trust_vol > 0:
                        trust_vwap20 = (trust_buy_days['Close'] * trust_buy_days['Trust_NetBuy']).sum() / total_trust_vol
                        price_dist = (latest['Close'] - trust_vwap20) / trust_vwap20
                        if -0.03 <= price_dist <= 0.05:
                            recent_3d_netbuy = df['Trust_NetBuy'].tail(3).sum()
                            recent_3d_min = df['Trust_NetBuy'].tail(3).min()
                            if recent_3d_netbuy > 500000 and recent_3d_min > -500000:
                                defense_score += 35
                                signals.append(f"【投信近期買進區防禦】股價逼近大哥20日買進加權價({round(trust_vwap20, 2)})且近期未見倒貨")
                            else:
                                defense_score -= 20
                                signals.append(f"【投信結帳警戒】股價逼近大哥買進價({round(trust_vwap20, 2)})但近期開始出脫")
        except Exception as e:
            has_error = True
            error_details.append(f"[Defense_Trust] {str(e)}")

        market_data = kwargs.get("market_data")
        try:
            mkt_df = market_data.get("df") if isinstance(market_data, dict) else market_data
            last_date = latest.name
            if mkt_df is not None and not mkt_df.empty and last_date in mkt_df.index:
                mkt_idx = mkt_df.index.get_loc(last_date)
                if mkt_idx > 0:
                    mkt_latest = mkt_df.iloc[mkt_idx]
                    mkt_prev = mkt_df.iloc[mkt_idx - 1]
                    mkt_drop = ((mkt_latest['Close'] - mkt_prev['Close']) / mkt_prev['Close']) * 100
                    if mkt_drop <= -1.2 and latest['Close'] >= prev['Close']:
                        defense_score += 20
                        signals.append(f"【恐慌抗跌代理】大盤重挫 {round(mkt_drop, 2)}%,逆勢守穩平盤之上!")
                    elif mkt_drop <= -0.8 and latest['Close'] >= prev['Close']:
                        defense_score += 10
                        signals.append(f"【逆勢抗跌代理】大盤下跌 {round(mkt_drop, 2)}%,個股逆勢收紅!")
        except Exception as e:
            has_error = True
            error_details.append(f"[Defense_Market] {str(e)}")

        defense_score = min(100, max(0, defense_score))
        if has_error: status = "系統計算異常(未完成計算)"
        elif defense_score == 0: status = "無明顯防守跡象"
        elif defense_score <= 40: status = "察覺初步防守(需再觀察)"
        elif defense_score <= 70: status = "防守型態確認(下檔有撐)"
        else: status = "強烈護盤型態(防守轉攻擊)"

        return {
            "defense_score": defense_score, "defense_status": status, "defense_signals": signals,
            "has_error": has_error, "error_details": error_details
        }


# ==========================================
# 模組 10: ChipRadarEngine
# ==========================================
class ChipRadarEngine:
    def calculate(self, data, mode):
        df = data["df"]
        data_quality = data.get("data_quality", {})
        inst_state = data_quality.get('inst_state', 'missing')

        if mode == 'intraday':
            return {
                "chip_score": 0, "chip_status": "未啟用(盤中極速模式)",
                "chip_messages": ["盤中模式:純技術面分析,未啟用籌碼雷達"]
            }

        if inst_state in ['missing', 'error', 'schema_error', 'empty_response', 'network_error']:
            return {
                "chip_score": 0, "chip_status": "資料缺失",
                "chip_messages": [f"籌碼資料異常({inst_state})，籌碼判定略過"]
            }

        latest = df.iloc[-1]
        score = 0
        messages = []

        vol = latest.get("Volume", 1) / 1000
        if vol <= 0: vol = 1

        trust_buy = latest.get("Trust_NetBuy", 0) / 1000
        foreign_buy = latest.get("Foreign_NetBuy", 0) / 1000
        dealer_buy = latest.get("Dealer_NetBuy", 0) / 1000
        inst_buy = latest.get("Inst_NetBuy", 0) / 1000

        is_complete = (inst_state == 'complete')

        if is_complete:
            messages.append(f"【單日籌碼明細】外資: {int(foreign_buy):+} 張 | 投信: {int(trust_buy):+} 張 | 自營: {int(dealer_buy):+} 張 | 合計: {int(inst_buy):+} 張")

            if trust_buy > (vol * 0.05) or trust_buy > 500:
                score += 20
                messages.append(f"【投信大買】當日投信買超 {int(trust_buy)} 張,大哥啟動波段認養!")
            elif trust_buy < -500:
                score -= 10
                messages.append(f"【投信結帳】當日投信賣超 {abs(int(trust_buy))} 張,留意大哥結帳!")

            if inst_buy > (vol * 0.1) and trust_buy > 0 and foreign_buy > 0 and dealer_buy > 0:
                score += 15
                messages.append(f"【法人集中吃貨】三大法人同步買超 {int(inst_buy)} 張,籌碼極度安定!")
            elif inst_buy > (vol * 0.1):
                score += 10
                messages.append(f"【法人吃貨】三大法人合計買超 {int(inst_buy)} 張,籌碼面偏多!")

            if inst_buy < -(vol * 0.1):
                score -= 20
                messages.append(f"【法人無情提款】三大法人合計大賣 {abs(int(inst_buy))} 張,提防高檔倒貨!")

            if foreign_buy < -1000 and inst_buy >= -(vol * 0.1):
                score -= 10
                messages.append(f"【外資單獨提款】外資單日大賣 {abs(int(foreign_buy))} 張,留意土洋對作賣壓!")
            elif foreign_buy > 1000 and inst_buy <= (vol * 0.1):
                score += 10
                messages.append(f"【外資單獨點火】外資單日大買 {int(foreign_buy)} 張!")

        score = max(-30, min(30, score))

        if inst_state == 'partial':
            status = "部分法人數據 (不作過度解讀)"
            f_str = f"{int(foreign_buy):+}" if pd.notna(latest.get('Foreign_NetBuy')) else "無"
            t_str = f"{int(trust_buy):+}" if pd.notna(latest.get('Trust_NetBuy')) else "無"
            d_str = f"{int(dealer_buy):+}" if pd.notna(latest.get('Dealer_NetBuy')) else "無"

            messages.append(f"【部分數據明細】外資: {f_str} 張 | 投信: {t_str} 張 | 自營: {d_str} 張")
            messages.append(f"注意：目前僅有部分法人數據 (缺 {'/'.join(data_quality.get('missing_inst_parts', []))})")
        elif score >= 10:
            status = "法人重金進駐"
        elif score <= -10:
            status = "法人籌碼潰散"
        else:
            status = "法人籌碼中立"

        return {
            "chip_score": score, "chip_status": status, "chip_messages": messages
        }


# ==========================================
# 模組 11: ChipXRayEngine (🌟 V25.2: 修正純度語法)
# ==========================================
class ChipXRayEngine:
    def calculate(self, tdcc_df, position_info):
        if tdcc_df is None or tdcc_df.empty or len(tdcc_df) < 3:
            return {"xray_status": "資料不足", "xray_message": "集保數據不足，無法進行中線判定", "is_surge": False}

        latest_3 = tdcc_df.tail(3).reset_index(drop=True)
        w0 = latest_3.iloc[2]
        w1 = latest_3.iloc[1]
        w2 = latest_3.iloc[0]

        delta_w = w0['Whale_Pct'] - w1['Whale_Pct']
        delta_r = w0['Retail_Pct'] - w1['Retail_Pct']
        cap_size = w0['Cap_Size']

        status = "籌碼中性"
        message = "無明顯大戶連續異常動向"
        is_surge = False

        surge_threshold = 1.0 if cap_size == 'Small_Cap' else 0.5

        if delta_w >= surge_threshold and delta_r < 0:
            purity = delta_w / abs(delta_r) if delta_r != 0 else 0.0
            if purity >= 0.8:
                status = "S級急買突襲"
                message = f"🔥 【S級急買突襲】大戶單週暴力掃貨 (增幅 {delta_w:.2f}%)，大戶吸籌力道為散戶退場的 {purity:.1f} 倍！散戶急退，隨時發動！"
                is_surge = True
                return {"xray_status": status, "xray_message": message, "is_surge": is_surge}

        is_accumulating = (w0['Whale_Pct'] > w1['Whale_Pct'] and w1['Whale_Pct'] > w2['Whale_Pct']) or (w0['Whale_Pct'] - w2['Whale_Pct'] >= 1.0)
        is_retail_leaving = (w0['Retail_Pct'] < w1['Retail_Pct'] and w1['Retail_Pct'] < w2['Retail_Pct'])

        is_distributing = (w0['Whale_Pct'] < w1['Whale_Pct'] and w1['Whale_Pct'] < w2['Whale_Pct'])
        is_retail_entering = (w0['Retail_Pct'] > w1['Retail_Pct'] and w1['Retail_Pct'] > w2['Retail_Pct'])

        pos = position_info.get("fish_position", "")

        if is_accumulating and is_retail_leaving:
            if "底" in pos or "形成" in pos:
                status = "黃金坑潛伏"
                message = f"★ 【底部籌碼沉澱】大戶(連3週)默默吸籌，散戶退場，等待突破！"
            else:
                status = "大戶吸籌"
                message = f"💡 【大戶吸籌】籌碼持續集中至大戶手中，趨勢偏多。"

        elif is_distributing and is_retail_entering:
            if "出貨" in pos or "魚尾" in pos:
                status = "頂峰警報"
                message = f"☠️ 【大戶派發確認】高檔籌碼鬆動，主力連3週倒貨給散戶，嚴格防守！"
            else:
                status = "大戶派發"
                message = f"⚠️ 【大戶派發】大戶籌碼流向散戶，需提高警覺。"

        return {"xray_status": status, "xray_message": message, "is_surge": is_surge}
