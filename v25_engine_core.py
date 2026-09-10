# ==============================================================================
# GrandMaster Whale Engine V25.6 Pro (邏輯閉環完全體) - 網頁端專用決策判斷核心模組
# 
# 🌟 本版本具備三大升級：
# 1. 獵豹升級：實作底部成本區位豁免權 (成本距離 <= 8%)，免除起漲誤殺
# 2. 籌碼折價因子：徹底解決基本面高分但籌碼潰散的自我矛盾 (華邦電穿幫修復)
# 3. 投信波段認養濾網：連續買超天數與 >= 100 張絕對門檻，防範冷門股與單日隔日沖雜訊
# 4. DataEngine 柔性對齊：完全拔除 YF 延遲當機 Bug，採用 T-1 柔性對齊
# ==============================================================================

import os
import sys
import time
import random
import math
import warnings
from datetime import datetime, timedelta
import pytz
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

WHALE_VERSION = "V25.6 PRO"

# Optional DataLoader import
try:
    from FinMind.data import DataLoader
except Exception:
    class DataLoader:
        def login_by_token(self, api_token): pass
        def taiwan_stock_institutional_investors(self, **kwargs): return pd.DataFrame()
        def taiwan_stock_margin_purchase_short_sale(self, **kwargs): return pd.DataFrame()
        def taiwan_stock_month_revenue(self, **kwargs): return pd.DataFrame()
        def taiwan_stock_holding_shares_per(self, **kwargs): return pd.DataFrame()
        def taiwan_stock_daily(self, **kwargs): return pd.DataFrame()

try:
    import yfinance as yf
except Exception:
    yf = None



# GrandMaster Whale Engine V25.6 Pro
# Cell 2: 工具函式

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

print(f"WhaleTools 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 3: DataEngine (🌟 完全拔除 YF 延遲當機 Bug，採用 T-1 柔性對齊)

class TDCCCacheManager:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        self.cached_dfs = {}
        self.load_cache_to_memory()

    def load_cache_to_memory(self):
        files = [f for f in os.listdir(self.cache_dir) if f.startswith('TDCC_') and f.endswith('.csv')]
        if not files:
            print("⚠️ 尚未發現集保快取資料，請記得週末先執行【TDCC 資料庫建置器】")
            return

        print("⏳ 正在將 Google Drive 集保歷史快取載入系統記憶體...")
        for f in files:
            path = os.path.join(self.cache_dir, f)
            try:
                df = pd.read_csv(path, dtype={'stock_id': str})
                df['stock_id'] = df['stock_id'].astype(str).str.strip()
                df['date'] = pd.to_datetime(df['date'])
                self.cached_dfs[f] = df
            except Exception as e:
                print(f"無法讀取快取檔 {f}: {e}")

        print(f"✅ 成功載入 {len(self.cached_dfs)} 週的集保大戶資料！")

    def get_stock_data(self, stock_id):
        if not self.cached_dfs: return pd.DataFrame()
        dfs = []
        target_id = str(stock_id).strip()
        for f, df in self.cached_dfs.items():
            stock_df = df[df['stock_id'] == target_id]
            if not stock_df.empty:
                dfs.append(stock_df)
        if dfs:
            final_df = pd.concat(dfs)
            return final_df.sort_values('date').reset_index(drop=True)
        return pd.DataFrame()

class DataEngine:
    def __init__(self, dataloader=None, tdcc_manager=None):
        if dataloader is None:
            self.dl = DataLoader()
            token = os.getenv("FINMIND_TOKEN")
            if not token: raise RuntimeError("缺少 FINMIND_TOKEN")
            self.dl.login_by_token(api_token=token)
        else: self.dl = dataloader
        self.tdcc_manager = tdcc_manager

    def load_stock(self, stock_id, mode='after_market'):
        tw_code = str(stock_id).strip() + ".TW"
        two_code = str(stock_id).strip() + ".TWO"
        print(f"載入股票資料: {stock_id} ...")

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
                if latest_price_date in date_strs.values: data_quality['inst_state'] = 'complete'
                else: data_quality['inst_state'] = 'stale'
            else:
                data_quality['inst_state'] = 'empty_response'
                df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = np.nan
        except Exception as e:
            data_quality['inst_state'] = 'network_error'
            df['Trust_NetBuy'] = df['Foreign_NetBuy'] = df['Dealer_NetBuy'] = df['Inst_NetBuy'] = np.nan

        time.sleep(random.uniform(0.3, 0.7))

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

        time.sleep(random.uniform(0.3, 0.7))

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

        try:
            if self.tdcc_manager:
                tdcc_raw = self.tdcc_manager.get_stock_data(stock_id)
                if tdcc_raw is not None and not tdcc_raw.empty:
                    tdcc_raw['level'] = tdcc_raw['level'].astype(str).str.strip()
                    grouped = tdcc_raw.groupby('date')
                    records = []

                    for d, grp in grouped:
                        valid_levels = [str(i) for i in range(1, 16)]
                        total_shares = grp[grp['level'].isin(valid_levels)]['hold_shares'].sum()
                        if total_shares == 0: continue

                        retail_levels = [str(i) for i in range(1, 10)]
                        retail_pct = grp[grp['level'].isin(retail_levels)]['percent'].sum()

                        cap_size = 'Small_Cap' if total_shares < 200000000 else 'Large_Cap'
                        if cap_size == 'Small_Cap': whale_pct = grp[grp['level'].isin(['12','13','14','15'])]['percent'].sum()
                        else: whale_pct = grp[grp['level'].isin(['15'])]['percent'].sum()

                        records.append({'date': d, 'Total_Shares': total_shares, 'Cap_Size': cap_size, 'Retail_Pct': retail_pct, 'Whale_Pct': whale_pct})

                    if records:
                        tdcc_df = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
                        data_quality['tdcc_latest_date'] = tdcc_df.iloc[-1]['date'].strftime("%Y-%m-%d")
                    else:
                        data_quality['errors'].append("[TDCC] 級距解析後無有效記錄")
                else:
                    data_quality['errors'].append("[TDCC] 快取庫中無此檔股票資料")
        except Exception as e:
            data_quality['errors'].append(f"[TDCC_Error] 快取提取例外: {str(e)}")

        return df, target_code, data_quality, rev_df, tdcc_df

    def load_market(self, target_code, latest_stock_date):
        mkt_ticker = "^TWOII" if target_code.endswith(".TWO") else "^TWII"
        mkt = yf.Ticker(mkt_ticker).history(period="2y", auto_adjust=True)

        if mkt is not None and not mkt.empty and mkt.index.tz is not None:
            mkt.index = mkt.index.tz_convert('Asia/Taipei').tz_localize(None)

        if mkt_ticker == "^TWOII":
            mkt_latest = mkt.index[-1].strftime("%Y-%m-%d") if (mkt is not None and not mkt.empty) else "1900-01-01"
            if mkt is None or mkt.empty or mkt_latest < latest_stock_date:
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

        # 🌟 V25.6 核心修復：T-1 雙重驗證法，徹底消滅 YF 延遲導致的 Stale 當機
        stock_latest = df.index[-1]
        mkt_latest = mkt.index[-1] if not mkt.empty else pd.Timestamp('1900-01-01')

        market_status = "Unknown"
        sync_msg = ""
        latest_common = None

        if not mkt.empty:
            if stock_latest == mkt_latest:
                latest_common = stock_latest
            elif len(df) > 1 and df.index[-2] == mkt_latest:
                latest_common = mkt_latest
                sync_msg = " (啟用2天比對: YF大盤延遲1天)"
            else:
                common_idx = df.index.intersection(mkt.index)
                if len(common_idx) > 0:
                    latest_common = common_idx[-1]
                    days_behind = (stock_latest - latest_common).days
                    if days_behind <= 5:
                        sync_msg = f" (啟用多日比對: 大盤延遲{days_behind}天)"
                    else:
                        market_status = "Stale"
                        sync_msg = " (大盤資料過舊)"
                else:
                    sync_msg = " (無共同交易日)"

        mkt_latest_date = (latest_common.strftime("%Y-%m-%d") + sync_msg) if latest_common else "無資料"

        if latest_common and market_status != "Stale":
            stock_close = df.loc[:latest_common, "Close"]
            market_close = mkt.loc[:latest_common, "Close"]

            if len(stock_close) >= 60 and len(market_close) >= 60:
                rs20 = WhaleTools.calculate_rs(stock_close, market_close, period=20)
                rs60 = WhaleTools.calculate_rs(stock_close, market_close, period=60)

                mkt["MA20"] = mkt["Close"].rolling(20, min_periods=1).mean()
                market_factor = WhaleTools.get_market_adaptive_factor(mkt.loc[:latest_common])
                mkt_slope = WhaleTools.calculate_slope(mkt.loc[:latest_common, "MA20"], period=5, scale=50, adaptive_factor=market_factor)

                mkt_latest_close = mkt.loc[latest_common, "Close"]
                mkt_latest_ma20 = mkt.loc[latest_common, "MA20"]

                if mkt_latest_close > mkt_latest_ma20 and mkt_slope > 0: market_status = "Bull"
                elif mkt_latest_close < mkt_latest_ma20 and mkt_slope < 0: market_status = "Bear"
                else: market_status = "Neutral"
            else:
                rs20, rs60, market_status = 0.0, 0.0, "Unknown"
        else:
            rs20, rs60 = 0.0, 0.0
            if market_status != "Stale": market_status = "Unknown"

        return {
            "df": df, "mkt": mkt, "rs20": rs20, "rs60": rs60,
            "vol_factor": vol_factor, "ma20_slope": ma20_slope, "market_status": market_status,
            "market_factor": market_factor, "mkt_latest_date": mkt_latest_date
        }

print(f"DataEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 4: FishScoreEngine

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
        elif data["market_status"] == "Bull" and latest["Close"] > latest["MA20"]: rs_score -= 5
        else: rs_score -= 10

        if rs60 > rs_limit_high: rs_score += 10
        elif rs60 > rs_limit_mid: rs_score += 7
        elif rs60 > 0: rs_score += 4
        elif data["market_status"] == "Bull" and latest["Close"] > latest["MA60"]: rs_score -= 5
        else: rs_score -= 10

        health_checks.append(("RS20 > 0 (動態門檻校準)", rs20 > 0))
        health_checks.append(("RS60 > 0", rs60 > 0))
        score += max(0, rs_score + 20)

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
            mean_bandwidth = df["Bandwidth"].shift(1).tail(20).mean()
            prev_bandwidth = df["Bandwidth"].shift(1).iloc[-1]
            is_bb_squeeze = prev_bandwidth <= (mean_bandwidth * 0.85) if mean_bandwidth > 0 else False
            if is_bb_squeeze and latest["Close"] > latest["MA20"]:
                score += 15
                health_checks.append(("布林極限壓縮後突破發動", True))
            else: health_checks.append(("布林極限壓縮後突破發動", False))
        except Exception:
            health_checks.append(("布林極限壓縮後突破發動", "Error"))
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
        rs_status = "相對大盤強勢" if rs_score >= 14 else "與大盤同步" if rs_score >= 0 else "相對弱勢"
        chip_status = "換手安定" if vwap_score >= 10 else "換手震盪" if vwap_score >= 5 else "鬆動"

        error_details = []
        if has_error:
            error_details.append(f"[Fish_Error] 大盤狀態 {market_status} 或布林通道運算失敗")

        return {
            "fish_score": round(score), "health_grade": grade,
            "trend_status": trend_status, "rs_status": rs_status, "chip_status": chip_status,
            "health_checks": health_checks, "has_error": has_error, "error_details": error_details
        }

print(f"FishScoreEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 5: RetreatScoreEngine (🌟 獵豹升級：實作底部成本區位豁免權，免除起漲誤殺)

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

        # 🌟 新增：底部豁免權判定 (成本距離 <= 8%)
        is_bottom_exempt = cost_distance <= 8.0

        grp1_score = 0
        try:
            price_change = (latest["Close"] - prev["Close"]) / prev["Close"]
            is_volume_high = latest["Volume"] > prev_vol20 * vol_breakout_limit
            is_price_stagnant = price_change < 0.02
            memory_triggered = False

            # 🌟 若具備底部豁免權，則強制關閉「10天破底記仇」機制
            if not is_bottom_exempt:
                for i in range(max(0, len(df)-11), len(df)-1):
                    if df.iloc[i]["Volume"] > df["VOL20_PRIOR"].iloc[i] * vol_breakout_limit:
                        if latest["Close"] < df.iloc[i]["Low"]: memory_triggered = True; break

            vol_str = "高檔爆量且已確認法人大賣" if is_inst_complete else "高檔爆量(法人資料未齊，無法確認)"

            if (is_volume_high and is_price_stagnant) or memory_triggered:
                # 🌟 若具備底部豁免權，則不扣除 45 分重罰，視為「良性換手吃貨」
                if not is_bottom_exempt and cost_distance > 5.0:
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
                else:
                    retreat_checks.extend([(f"{vol_str}(底部換手不扣分)", False if is_inst_complete else "Unknown"), ("爆量不漲(底部良性換手)", False)])
            else:
                retreat_checks.extend([(vol_str, False if is_inst_complete else "Unknown"), ("爆量不漲", False)])
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

        return {"retreat_score": round(retreat_score), "risk_status": risk_status, "retreat_checks": retreat_checks, "has_error": has_error, "error_details": error_details}

print(f"RetreatScoreEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 6: WhaleEnduranceEngine

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
                    score += 15
                    messages.append("[型態代理] 漲停量縮鎖死(籌碼極度安定)")
                else:
                    score += 10
                    messages.append("[型態代理] 放量換手漲停(攻擊動能強勁)")

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

        return {"endurance_score": round(score), "endurance_status": status, "endurance_messages": messages, "has_error": has_error, "error_details": error_details}

print(f"WhaleEnduranceEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 7: FundamentalEngine

class FundamentalEngine:
    def calculate(self, rev_df, current_date):
        if rev_df is None or rev_df.empty:
            return {"fund_score": 0, "fund_label": "【無營收資料】", "yoy": 0, "mom": 0, "is_high": False, "fund_state": "missing", "is_pit_embargo": False}

        rev_df['revenue'] = pd.to_numeric(rev_df['revenue'], errors='coerce')
        rev_df = rev_df.dropna(subset=['revenue'])

        if len(rev_df) < 2:
            return {"fund_score": 0, "fund_label": "【營收資料不足】", "yoy": 0, "mom": 0, "is_high": False, "fund_state": "insufficient", "is_pit_embargo": False}

        latest_rev = rev_df.iloc[-1]['revenue']
        prev_rev = rev_df.iloc[-2]['revenue']
        latest_year = rev_df.iloc[-1]['revenue_year']
        latest_month = rev_df.iloc[-1]['revenue_month']

        current_dt = pd.to_datetime(current_date)
        months_diff = (current_dt.year - latest_year) * 12 + (current_dt.month - latest_month)
        is_stale = months_diff > 2

        is_pit_embargo = False
        if current_dt.day <= 10 and months_diff in [1, 2]:
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

        if is_mom_valid and prev_rev > 0: mom = ((latest_rev - prev_rev) / prev_rev) * 100

        is_high = False
        if len(rev_df) > 0:
            recent_max = rev_df['revenue'].tail(24).max()
            if latest_rev >= recent_max * 0.99: is_high = True

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
            score, is_dual_growth = 0, False
        elif not has_yoy or not is_mom_valid:
            fund_label = f"【營收期間不連續/不足】({'+'.join(label_parts)})"
            fund_state = "insufficient"
            score, is_dual_growth = 0, False
        else:
            fund_state = "complete"
            if is_dual_growth and yoy >= 10: fund_label = f"【營收雙增護體】{embargo_warn}({'+'.join(label_parts)})"
            elif yoy >= 10:
                mom_str = "MoM回落" if mom <= 0 else ""
                fund_label = f"【YoY成長，{mom_str}】{embargo_warn}({'+'.join(label_parts)})"
            elif yoy < 0 and mom > 0: fund_label = f"【谷底回溫/轉機】{embargo_warn}({'+'.join(label_parts)})"
            else: fund_label = f"【營收動能疲弱】{embargo_warn}({'+'.join(label_parts)})"

        return {"fund_score": min(40, score), "fund_label": fund_label, "yoy": round(yoy, 2) if has_yoy else "N/A", "mom": round(mom, 2) if is_mom_valid else "N/A", "is_high": is_high, "is_dual_growth": is_dual_growth, "fund_state": fund_state, "is_pit_embargo": is_pit_embargo}

print(f"FundamentalEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 8: Fish Position Engine (🌟 微調：初升段防守價直接錨定發動K棒最低點，杜絕停損過深)

class FishPositionEngine:
    def calculate(self, data, fish, retreat, warning, endurance, defense, fundamental, chip_data, chip_xray):
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        fish_score = fish["fish_score"]
        retreat_score = retreat["retreat_score"]
        warning_score = warning["warning_score"]
        rs20, rs60, slope = data['rs20'], data["rs60"], data["ma20_slope"]
        chip_score = chip_data.get("chip_score", 0)

        fund_score = fundamental.get("fund_score", 0)
        is_dual_growth = fundamental.get("is_dual_growth", False)
        yoy_val = fundamental.get("yoy", 0)
        yoy = float(yoy_val) if yoy_val != "N/A" else 0.0
        is_pit_embargo = fundamental.get("is_pit_embargo", False)

        all_errors = data.get("data_quality", {}).get("errors", [])
        fatal_errors = [e for e in all_errors if "TDCC" not in str(e)]
        data_layer_errors = len(fatal_errors) > 0

        has_sys_error = (
            data_layer_errors or fish.get("has_error", False) or retreat.get("has_error", False) or
            warning.get("has_error", False) or endurance.get("has_error", False) or defense.get("has_error", False)
        )

        try: bias20 = ((latest["Close"] - latest["MA20"]) / latest["MA20"]) * 100
        except Exception: bias20, has_sys_error = 0, True

        if retreat_score >= 80: position, progress = "魚尾區", 85
        elif retreat_score >= 60: position, progress = "出貨區", 100
        elif fish_score >= 80 and bias20 > 15: position, progress = "主升中後段", 70
        elif fish_score >= 80 and rs20 > 0 and rs60 > 0 and bias20 <= 15: position, progress = "主升初期", 50
        elif fish_score >= 70 and slope > 1: position, progress = "魚頭形成期", 30
        else: position, progress = "築底階段", 10

        base_score = 40 if progress <= 30 else 60 if progress == 50 else 30 if progress == 70 else 10
        opportunity_score = min(100, base_score + fund_score) if progress >= 30 else base_score

        if chip_xray.get("is_surge", False):
            opportunity_score = min(100, opportunity_score + 10)

        # 🌟 實作「籌碼折價因子」
        e_score = max(0, min(100, endurance.get("endurance_score", 0) + chip_score))

        if e_score <= 30 or chip_score <= -15:
            opportunity_score = min(opportunity_score, 39)
        elif e_score <= 50:
            opportunity_score = min(opportunity_score, 59)

        has_immunity = is_dual_growth and (chip_score >= 10)
        veto_threshold = 55 if has_immunity else 60
        tech_veto = (fish_score < veto_threshold or retreat_score >= 40 or warning_score >= 40)

        data_quality = data.get("data_quality", {})
        inst_state = data_quality.get('inst_state', 'missing')
        margin_state = data_quality.get('margin_state', 'missing')
        market_status = data.get('market_status', 'Unknown')
        fund_state = fundamental.get('fund_state', 'missing')
        is_intraday = data_quality.get('is_intraday', False)

        margin_streak = 0
        if margin_state == 'complete':
            valid_margin = df['Margin_Balance_Raw'].dropna()
            if len(valid_margin) > 1:
                for val in valid_margin.diff().dropna().iloc[::-1]:
                    if val > 0: margin_streak += 1
                    else: break

        k_date = data_quality.get('latest_price_date')
        i_date = data_quality.get('inst_latest_date')
        m_date = data_quality.get('margin_latest_date')

        is_fresh_and_complete = (
            inst_state == 'complete' and margin_state == 'complete' and fund_state == 'complete' and
            market_status not in ['Unknown', 'Stale'] and
            (k_date == i_date == m_date)
        )

        missing_msg = []
        if inst_state == 'partial': missing_msg.extend(data_quality.get('missing_inst_parts', []))
        if margin_state != 'complete': missing_msg.append("融資不連貫")
        if fund_state != 'complete': missing_msg.append("營收異常或過舊")
        missing_str = "缺" + "+".join(missing_msg) if missing_msg else "資料齊全"
        margin_str = f"(融資連買{margin_streak}天)" if margin_streak > 0 else ""

        if not is_fresh_and_complete and opportunity_score > 0: opportunity_score = int(opportunity_score * 0.5)

        if opportunity_score >= 80: opportunity_level = "*****"
        elif opportunity_score >= 60: opportunity_level = "****"
        elif opportunity_score >= 40: opportunity_level = "***"
        elif opportunity_score >= 20: opportunity_level = "**"
        else: opportunity_level = "*"

        if not is_fresh_and_complete and not has_sys_error and not tech_veto and not is_intraday:
            opportunity_level = f"降級({opportunity_level})"

        position_comment = ""

        # 🌟 邏輯閉環：主標籤狀態判定網
        if has_sys_error:
            candidate_status, opportunity_score, opportunity_level = "觀察 - 系統計算異常", 0, "-"
            position_comment = "底層安全模組例外，系統強制拒絕評估"
        elif tech_veto:
            candidate_status, opportunity_score, opportunity_level = "排除", 0, "-"
            position_comment = "風險閘門未通過，不列入候選"
        elif e_score <= 30 or chip_score <= -15:
            candidate_status, opportunity_score, opportunity_level = "觀察 - 籌碼惡化", 0, "-"
            position_comment = f"[{missing_str}] {margin_str} 籌碼與動能極度惡化，系統強制剔除候選資格"
        else:
            candidate_status = "候選 - 完整大局" if is_fresh_and_complete else "觀察 - 籌碼/基本面未齊"
            if progress <= 20: position_comment = "剛脫離整理區,仍在築底階段"
            elif progress <= 40: position_comment = "魚頭形成中,適合開始觀察"
            elif progress <= 60: position_comment = "進入主升初期,趨勢開始加速"
            elif progress <= 80: position_comment = "主升中後段,報酬與風險同步增加"
            else: position_comment = "魚尾或出貨區,追價風險極高"
            position_comment = f"【{candidate_status}】 [{missing_str}] {margin_str} " + position_comment

        current_price_adj = float(latest["Close"])
        current_price_raw = float(latest.get("Raw_Close", current_price_adj))
        atr14 = float(latest.get("ATR14", current_price_adj * 0.03))
        ratio = current_price_raw / current_price_adj if current_price_adj > 0 else 1.0

        vwap60_adj = float(latest.get("VWAP60", df["MA60"].iloc[-1]))
        if pd.isna(vwap60_adj) or vwap60_adj <= 0: vwap60_adj = float(latest["MA60"]) if not pd.isna(latest["MA60"]) else current_price_adj

        cost_distance = ((current_price_adj - vwap60_adj) / vwap60_adj * 100) if vwap60_adj > 0 else 0
        heat_level = "過熱" if cost_distance > 20 else "偏熱" if cost_distance > 10 else "水下(套牢)" if cost_distance < 0 else "正常"

        if heat_level == "過熱": max_tolerance = 15.0
        elif heat_level == "偏熱": max_tolerance = 20.0
        else: max_tolerance = 25.0

        # 🌟 實作「雙軌防守價錨定體系」
        is_early_stage = (progress <= 40) or (cost_distance <= 6.0)

        if is_early_stage:
            # 軌道 A：初升發動段 (🌟 微調：直接錨定當日最低點，拔除 min 造成的防守過深)
            raw_low_adj = float(latest.get("Raw_Low", current_price_raw)) / ratio
            baseline = raw_low_adj
            defensive_price_adj = baseline
            defensive_status_text = "初升段起漲防守 (貼近低點)"
        else:
            # 軌道 B：主升成型段 (均線支撐，容忍洗盤)
            ma20_val = float(latest["MA20"]) if not pd.isna(latest["MA20"]) else current_price_adj
            valid_supports = [s for s in [ma20_val, vwap60_adj] if s < current_price_adj]
            baseline = max(valid_supports) if valid_supports else current_price_adj
            defensive_price_adj = baseline - (1.8 * atr14)
            defensive_status_text = "主升段波段防守 (均線ATR)"

        defensive_price_raw = defensive_price_adj * ratio
        is_evaluable = True

        if pd.isna(defensive_price_raw) or defensive_price_raw <= 0:
            defensive_price_exec = 0.0
            defensive_status_text = "無有效防守價 (異常)"
            is_evaluable = False
        elif ((current_price_raw - defensive_price_raw) / current_price_raw * 100) > max_tolerance:
            from __main__ import WhaleTools
            defensive_price_exec = WhaleTools.round_tick(defensive_price_raw, 'floor')
            defensive_status_text = f"防守價過深(> {max_tolerance}%)，建議改用短均線停利"
        else:
            from __main__ import WhaleTools
            defensive_price_exec = WhaleTools.round_tick(defensive_price_raw, 'floor')

        if is_evaluable:
            vol_shrink_standard = float(latest["Volume"]) < float(prev["Volume"]) * 0.5
            extreme_vol_shrink = float(latest["Volume"]) < float(df["VOL5_PRIOR"].iloc[-1]) * 0.7
            day_range = float(latest["Raw_High"]) - float(latest["Raw_Low"])
            close_pos = (current_price_raw - float(latest["Raw_Low"])) / day_range if day_range > 0 else 0.5
            vwap_breakout = (current_price_adj > float(latest["Typical_Price"])) and (float(prev["Close"]) <= float(prev["Typical_Price"]))

            ma10 = float(latest["MA10"]) if not pd.isna(latest["MA10"]) else current_price_adj
            ma20 = float(latest["MA20"]) if not pd.isna(latest["MA20"]) else current_price_adj
            near_ma10 = (abs(current_price_adj - ma10) / ma10 < 0.02) and (current_price_adj > ma10 * 0.99)
            near_ma20 = (abs(current_price_adj - ma20) / ma20 < 0.02) and (current_price_adj > ma20 * 0.99)

            trust_buy = df.get("Trust_NetBuy", pd.Series([0])).tail(3).sum() > 0
            co_buy = trust_buy and (df.get("Foreign_NetBuy", pd.Series([0])).tail(3).sum() > 0)

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

        from __main__ import WhaleTools
        upside_low = ((target_low_raw - current_price_raw) / current_price_raw * 100) if current_price_raw > 0 else 0.0
        upside_high = ((target_high_raw - current_price_raw) / current_price_raw * 100) if current_price_raw > 0 else 0.0
        target_low_exec = WhaleTools.round_tick(target_low_raw, 'floor')
        target_high_exec = WhaleTools.round_tick(target_high_raw, 'ceil')

        if not is_evaluable: base_strategy = "【防守價失效/無防守】無法核算出合理的防守區間，風險不可控"
        elif e_score <= 30 or chip_score <= -15: base_strategy = "【籌碼潰散/破線危機】主力法人無情提款或動能徹底消散，切勿接刀！"
        elif fish_score >= 70 and e_score <= 40: base_strategy = "【技術與籌碼背離】大趨勢偏多，但短線動能衰退，切勿追高！"
        elif fish_score < 70 and (retreat_score >= 60 or warning_score >= 70) and e_score < 40 and progress >= 50:
            base_strategy = "【末升段誘多】高風險+低期望值(出貨與接刀跡象已現,切勿追高)"
        elif e_score <= 40 and retreat_score >= 60: base_strategy = "【短線籌碼潰散/破線危機】短線遭遇沉重賣壓,嚴格防守!"
        elif cost_distance > 25.0 and retreat_score <= 20 and fish_score >= 70 and e_score > 50: base_strategy = "【極端妖股】風險極端(正乖離極大!空手勿追,防守沿5日線)"
        elif fish_score >= 70 and retreat_score <= 20 and warning_score < 40 and e_score >= 60 and is_dual_growth: base_strategy = "【大局完整：營收雙增核心單】低風險+高成長(多方與基本面共振完好)"
        elif fish_score >= 70 and retreat_score <= 20 and warning_score < 40 and e_score >= 60: base_strategy = "【純技術波段單】低風險+高期望值(技術籌碼共振完好,可積極操作)"
        elif fish_score >= 60 and cost_distance <= 7.0 and e_score >= 60: base_strategy = "【初升段成型】趨勢轉強且風險低(結構初展端倪,可酌量佈局)"
        elif fish_score >= 60 and retreat_score <= 20 and warning_score < 40 and cost_distance <= 8.0 and e_score >= 40: base_strategy = "【左側轉折單】低風險+高期望值(左側摸底試單,嚴守停損)"
        elif retreat_score >= 40 or warning_score >= 40: base_strategy = "【風險醞釀中】部分風險指標升高(高位鬆動跡象,建議減碼或觀望)"
        elif fish_score >= 60 and e_score < 60: base_strategy = "【技術偏多但動能不足】線型尚可但缺乏買盤點火,建議等待表態"
        else: base_strategy = "【震盪整理區】多空動能分歧且不明確(建議休養生息)"

        if market_status == 'Bear': base_strategy = f"【逆勢高風險】大盤空頭！ " + base_strategy

        if candidate_status == "觀察 - 系統計算異常": strategy_profile = f"【安全模組異常】系統強制降級。純技術面研判：{base_strategy}"
        elif candidate_status == "【分析失敗】資料異常": strategy_profile = f"【系統防呆】資料嚴重異常。純技術面研判：{base_strategy}"
        elif candidate_status == "排除": strategy_profile = f"【風險閘門排除】技術或籌碼面存在顯著風險，不建議進場操作。純技術面研判：{base_strategy}"
        elif candidate_status == "觀察 - 籌碼惡化": strategy_profile = f"【籌碼制衡降級】籌碼極差，退出候選名單。純技術面研判：{base_strategy}"
        elif not is_evaluable: strategy_profile = f"【防守價異常】無法核算合理停損區間。純技術面研判：{base_strategy}"
        else: strategy_profile = base_strategy

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

print(f"FishPositionEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 9: EarlyWarningEngine

import pandas as pd
import numpy as np

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
        except Exception as e:
            df['RSI'] = np.nan
            error_details.append(f"RSI計算錯誤: {str(e)}")
            has_error = True

        recent_high = df['High'].tail(20).max()
        is_uptrend = latest['Close'] > df['MA60'].iloc[-1]
        is_near_high = (((recent_high - latest['Close']) / latest['Close']) < 0.10) and is_uptrend

        grp1_score = 0
        try:
            if is_near_high and abs(latest['Raw_Close'] - latest['Raw_Open']) < abs(prev['Raw_Close'] - prev['Raw_Open']) and latest['Volume'] < prev['Volume']:
                grp1_score += 35
                checks.append(("高檔量縮且K線壓縮", True))
            else: checks.append(("高檔量縮且K線壓縮", False))
        except Exception as e:
            checks.append(("高檔量縮且K線壓縮", "Error"))
            error_details.append(f"[Warning_Vol] {str(e)}")

        try:
            if 'Typical_Price' in df.columns and (df['Close'].tail(3) < df['Typical_Price'].tail(3)).sum() >= 2 and is_near_high:
                grp1_score += 20
                checks.append(("連續受制當日HLC/3代理線", True))
            else: checks.append(("連續受制當日HLC/3代理線", False))
        except Exception as e:
            checks.append(("連續受制當日HLC/3代理線", "Error"))
            error_details.append(f"[Warning_HLC3] {str(e)}")

        try:
            if pd.isna(latest['RSI']): checks.append(("RSI動能頂背離現象", "Error"))
            else:
                is_price_peak = latest['Close'] >= df['Close'].tail(15).max()
                prev_peaks = df.iloc[-25:-5][df.iloc[-25:-5]['Close'] >= df.iloc[-25:-5]['Close'].rolling(5).max()]
                if is_price_peak and not prev_peaks.empty and latest['RSI'] < prev_peaks.iloc[-1]['RSI']:
                    grp1_score += 30
                    checks.append(("RSI動能頂背離現象", True))
                else: checks.append(("RSI動能頂背離現象", False))
        except Exception as e:
            checks.append(("RSI動能頂背離現象", "Error"))
            error_details.append(f"[Warning_RSI] {str(e)}")

        try:
            macd_decelerating = (latest['MACD_Hist'] > 0) and (latest['MACD_Hist'] < prev['MACD_Hist']) and (prev['MACD_Hist'] < df.iloc[-3]['MACD_Hist'])
            if is_near_high and macd_decelerating:
                grp1_score += 30
                checks.append(("MACD紅柱連縮(上漲加速度反轉)", True))
            else: checks.append(("MACD紅柱連縮(上漲加速度反轉)", False))
        except Exception as e:
            checks.append(("MACD紅柱連縮(上漲加速度反轉)", "Error"))
            error_details.append(f"[Warning_MACD] {str(e)}")

        grp1_score = min(60, grp1_score)

        grp2_score = 0
        margin_state = data.get("data_quality", {}).get("margin_state", "missing")
        if margin_state != 'complete': checks.append(("融資餘額異常增加(散戶接刀)", "Unknown"))
        else:
            try:
                recent_3_raw = df['Margin_Balance_Raw'].dropna().tail(3)
                if len(recent_3_raw) == 3 and (recent_3_raw.index == df.index[-3:]).all():
                    diffs = recent_3_raw.diff().dropna()
                    if (diffs > 0).sum() >= 2:
                        margin_inc = diffs[diffs > 0].sum()
                        vol_avg = df['VOL20_PRIOR'].iloc[-1]
                        if margin_inc > (vol_avg * 0.05):
                            checks.append(("融資餘額異常增加(散戶接刀)", True))
                            grp2_score += 20
                        else: checks.append(("融資微增(未達警戒比例)", False))
                    else: checks.append(("融資餘額異常增加(散戶接刀)", False))
                else: checks.append(("融資餘額異常增加(散戶接刀)", "Unknown"))
            except Exception as e:
                checks.append(("融資餘額異常增加(散戶接刀)", "Error"))
                error_details.append(f"[Warning_Margin] {str(e)}")

        score = min(100, grp1_score + grp2_score)

        if len(error_details) > 0: status = "系統計算異常(Unknown)"
        elif score >= 70: status = "高度警戒(A轉風險極大或散戶接刀)"
        elif score >= 30: status = "動能衰退(提防拉高出貨)"
        else: status = "動能正常(未見明顯敗象)"

        return {"warning_score": score, "warning_status": status, "warning_checks": checks, "has_error": len(error_details)>0, "error_details": error_details}

print(f"EarlyWarningEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 10: SmartMoneyDefenseEngine

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

print(f"SmartMoneyDefenseEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 11: ChipRadarEngine (🌟 微調：投信首度插旗加入 >= 100張 的絕對張數濾網，防範冷門股雜訊)

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

            df_valid_trust = df.dropna(subset=['Trust_NetBuy'])
            if len(df_valid_trust) >= 5:
                recent_5_trust = df_valid_trust['Trust_NetBuy'].tail(5) / 1000
                trust_5d_sum = recent_5_trust.sum()

                trust_consecutive_buy = 0
                for val in recent_5_trust.iloc[::-1]:
                    if val > 0: trust_consecutive_buy += 1
                    else: break

                trust_consecutive_sell = 0
                for val in recent_5_trust.iloc[::-1]:
                    if val < 0: trust_consecutive_sell += 1
                    else: break

                vol_avg_5d = df_valid_trust['Volume'].tail(5).mean() / 1000

                # 🌟 波段認養判斷 (連買 3 天，或 5 日總買超大)
                if trust_consecutive_buy >= 3 or trust_5d_sum > (vol_avg_5d * 0.1) or trust_5d_sum > 1000:
                    score += 20
                    messages.append(f"【投信波段認養】近5日大哥累計買超 {int(trust_5d_sum)} 張(連買{trust_consecutive_buy}天)，籌碼集中！")

                # 🌟 新增：「投信首度插旗」提早卡位 (前幾天沒動作，今天突然單日大買佔均量 > 5% 且絕對張數 >= 100張)
                elif trust_consecutive_buy in [1, 2] and trust_buy > (vol_avg_5d * 0.05) and trust_buy >= 100:
                    score += 20
                    messages.append(f"【投信首度插旗】大哥單日大買 {int(trust_buy)} 張(佔均量>5%)，首度表態卡位！")

                # 🌟 波段結帳判斷
                elif trust_consecutive_sell >= 2 or trust_5d_sum < -500:
                    score -= 15
                    messages.append(f"【投信波段結帳】近5日大哥累計賣超 {abs(int(trust_5d_sum))} 張(連賣{trust_consecutive_sell}天)，警戒撤退！")

                # 🌟 單日微幅調節 (豁免扣分)
                elif trust_buy < 0 and trust_5d_sum > 0:
                    messages.append(f"【投信微幅調節】單日小賣 {abs(int(trust_buy))} 張，但近5日仍偏多，持續觀察。")

                # 🌟 單日點火 (未達首度插旗標準)
                elif trust_buy > 0:
                    score += 5
                    messages.append(f"【投信單日點火】單日買超 {int(trust_buy)} 張，觀察是否形成連買。")
            else:
                # 資料不足 5 天的回退機制
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

print(f"ChipRadarEngine 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 12: ChipXRayEngine

class ChipXRayEngine:
    def calculate(self, tdcc_df, fish_score, retreat_score):
        if tdcc_df is None or tdcc_df.empty or len(tdcc_df) < 3:
            avail = len(tdcc_df) if tdcc_df is not None else 0
            return {
                "xray_status": "快取累積中",
                "xray_message": f"本地快取庫僅有 {avail} 週記錄，需累積滿 3 週即可啟動大戶 X 光透視",
                "is_surge": False
            }

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
                message = f"🔥 【S級急買突襲】大戶單週暴力掃貨 (增幅 {delta_w:.2f}%)，大戶吸籌力道為散戶退場的 {purity:.1f} 倍！隨時發動！"
                is_surge = True
                return {"xray_status": status, "xray_message": message, "is_surge": is_surge}

        is_accumulating = (w0['Whale_Pct'] > w1['Whale_Pct'] and w1['Whale_Pct'] > w2['Whale_Pct']) or (w0['Whale_Pct'] - w2['Whale_Pct'] >= 1.0)
        is_retail_leaving = (w0['Retail_Pct'] < w1['Retail_Pct'] and w1['Retail_Pct'] < w2['Retail_Pct'])

        is_distributing = (w0['Whale_Pct'] < w1['Whale_Pct'] and w1['Whale_Pct'] < w2['Whale_Pct'])
        is_retail_entering = (w0['Retail_Pct'] > w1['Retail_Pct'] and w1['Retail_Pct'] > w2['Retail_Pct'])

        pos_str = "底" if fish_score < 60 else "出貨" if retreat_score >= 60 else ""

        if is_accumulating and is_retail_leaving:
            if "底" in pos_str:
                status = "黃金坑潛伏"
                message = f"★ 【底部籌碼沉澱】大戶(連3週)默默吸籌，散戶退場，等待突破！"
            else:
                status = "大戶吸籌"
                message = f"💡 【大戶吸籌】籌碼持續集中至大戶手中，趨勢偏多。"

        elif is_distributing and is_retail_entering:
            if "出貨" in pos_str:
                status = "逃頂警報"
                message = f"☠️ 【大戶派發確認】高檔籌碼鬆動，主力連3週倒貨給散戶，嚴格防守！"
            else:
                status = "大戶派發"
                message = f"⚠️ 【大戶派發】大戶籌碼流向散戶，需提高警覺。"

        return {"xray_status": status, "xray_message": message, "is_surge": is_surge}

print(f"ChipXRayEngine (集保透視外掛) 載入完成 ({WHALE_VERSION})")

# GrandMaster Whale Engine V25.6 Pro
# Cell 13: Dashboard Report Engine

class DashboardEngine:
    def generate_report(self, stock_id, fish, retreat, position, endurance, warning, defense, chip, chip_xray, fundamental, data_quality, mode_info):
        fish_score = fish["fish_score"]
        retreat_score = retreat["retreat_score"]
        grade = fish["health_grade"]
        trend_status = fish["trend_status"]
        rs_status = fish.get("rs_status", "中性")
        chip_status = chip["chip_status"]
        risk_status = retreat["risk_status"]
        candidate_status = position["candidate_status"]
        fish_position = position["fish_position"]
        progress = position["progress"]
        opportunity_score = position["opportunity_score"]
        opportunity_level = position["opportunity_level"]
        current_price = position["current_price"]
        vwap60 = position["vwap60"]
        cost_distance = position["cost_distance"]
        target_low = position["target_low"]
        target_high = position["target_high"]
        upside_low = position["upside_low"]
        upside_high = position["upside_high"]
        heat_level = position["heat_level"]
        defensive_price = position["defensive_price"]
        defensive_text = position.get("defensive_status_text", "ATR計算")
        endurance_score = endurance["endurance_score"]
        endurance_status = endurance["endurance_status"]

        strategy_profile = position.get("strategy_profile", "")
        position_comment = position.get("position_comment", "")

        fish_check_text = ""
        for item, status in fish["health_checks"]:
            if status == "Error": mark = "⚠️錯誤"
            elif status is None: mark = "-"
            elif status: mark = "O"
            else: mark = "X"
            fish_check_text += f"{item:<25} [{mark}]\n"

        retreat_check_text = ""
        for item, status in retreat["retreat_checks"]:
            if status == "Error": mark = "⚠️錯誤"
            elif status == "Unknown": mark = "❓未知"
            elif status is None: mark = "-"
            elif status: mark = "🚨觸發"
            else: mark = "✅安全"
            retreat_check_text += f"{item:<25} [{mark}]\n"

        warning_check_text = ""
        for item, status in warning["warning_checks"]:
            if status == "Error": mark = "⚠️錯誤"
            elif status == "Unknown": mark = "❓未知"
            elif status == "NOT_APP": mark = "不適用"
            elif status is None: mark = "待更新"
            elif status: mark = "🚨觸發"
            else: mark = "✅安全"
            warning_check_text += f"{item:<25} [{mark}]\n"

        endurance_msg_text = ""
        if endurance["endurance_messages"]:
            for msg in endurance["endurance_messages"]: endurance_msg_text += f" {msg}\n"
        else: endurance_msg_text = "量價表現平穩,無異常變動\n"

        defense_msg_text = ""
        if defense["defense_signals"]:
            for msg in defense["defense_signals"]: defense_msg_text += f" {msg}\n"
        else: defense_msg_text = "未偵測到特殊防禦行為\n"

        if cost_distance < 0:
            target_display = "破線套牢區(無目標價)"
            upside_display = "上檔壓力沉重(切勿盲目抄底)"
        else:
            target_display = f"{target_low} ~ {target_high}"
            upside_display = f"+{upside_low}% ~ +{upside_high}%"

        composite_risk = f"撤退: [{risk_status}] | 預警: [{warning['warning_status']}]"

        mode_warning = ""
        if mode_info['requested'] == 'after_market' and mode_info['effective'] == 'intraday':
            mode_warning = "\n⚠️ 【系統警告】資料未達盤後更新標準，已強制降級為「盤中極速模式」！\n"

        report = f"""
==================================================
# Dashboard Final ({WHALE_VERSION}){mode_warning}
==================================================
[{stock_id}] | 狀態: {candidate_status}
【基本面】 {fundamental['fund_label']} (YoY: {fundamental['yoy']}%, MoM: {fundamental['mom']}%)
【資料對齊紀錄】 K線: {data_quality['latest_price_date']} | 法人: {data_quality['inst_latest_date']} | 集保: {data_quality.get('tdcc_latest_date', '無')}
【基準日追蹤】 營收期: {data_quality.get('revenue_latest_date', '無')} | 大盤日: {data_quality.get('mkt_latest_date', '無')} | 查詢時: {data_quality.get('queried_at', '無')}

魚頭分數: {fish_score:<3}             綜合風險狀態: {composite_risk}
機會分數: {opportunity_score:<3}             防禦狀態: {defense['defense_status']}
健康等級: {grade}
--------------------------------------------------
魚體位置: {fish_position}
進度: {progress}%                   機會等級: {opportunity_level}
--------------------------------------------------
目前價(Raw): {current_price}
實戰防守價: {defensive_price} ({defensive_text})
60日加權均價代理: {vwap60}
成本距離: {cost_distance}%
Cost Heat: {heat_level} (動態容忍上限 {position.get('max_tolerance', 0)}%)
保守目標區: {target_display}
剩餘空間: {upside_display}
--------------------------------------------------
趨勢: {trend_status} | 動能: {rs_status} | 籌碼: {chip_status}
--------------------------------------------------
【籌碼續航力分析】({chip['chip_status']})
續航總分: {min(100, endurance_score + chip['chip_score'])} / 100
當前狀態: {endurance_status}
{endurance_msg_text}
--------------------------------------------------
【集保大戶 X 光透視】 ({chip_xray['xray_status']})
 {chip_xray['xray_message']}
--------------------------------------------------
【型態防禦雷達】
{defense_msg_text}
--------------------------------------------------
【魚頭體檢】
{fish_check_text}
--------------------------------------------------
【撤退檢查】
{retreat_check_text}
--------------------------------------------------
【高檔預警】
{warning_check_text}
--------------------------------------------------
【系統解讀】
* {position_comment}
* {strategy_profile}
==================================================
"""
        print(report)
        return report

print(f"DashboardEngine 載入完成 ({WHALE_VERSION})")

class WhaleEngine:
    def __init__(self, token=None):
        # Local class references already in module scope
        self.shared_dl = DataLoader()
        token = token or os.getenv("FINMIND_TOKEN", "")
        if token:
            try: self.shared_dl.login_by_token(api_token=token)
            except Exception: pass

        tdcc_cache_dir = os.path.join(os.getcwd(), 'TDCC_Cache')
        self.tdcc_manager = TDCCCacheManager(tdcc_cache_dir)
        self.data_engine = DataEngine(dataloader=self.shared_dl, tdcc_manager=self.tdcc_manager)

        self.fish_engine = FishScoreEngine()
        self.retreat_engine = RetreatScoreEngine()
        self.fundamental_engine = FundamentalEngine()
        self.position_engine = FishPositionEngine()
        self.endurance_engine = WhaleEnduranceEngine()
        self.warning_engine = EarlyWarningEngine()
        self.defense_engine = SmartMoneyDefenseEngine()
        self.chip_engine = ChipRadarEngine()
        self.xray_engine = ChipXRayEngine()
        self.dashboard_engine = DashboardEngine()

    def analyze(self, stock_id, mode='after_market', custom_params=None, is_optimized=False):
        if custom_params is None: custom_params = {}
        try:
            print(f"\n開始分析 {stock_id}...")
            tz = pytz.timezone('Asia/Taipei')
            now = datetime.now(tz)
            requested_mode, effective_mode = mode, mode

            df, target_code, data_quality, rev_df, tdcc_df = self.data_engine.load_stock(stock_id, effective_mode)

            if df is None or df.empty or len(df) < 60: raise Exception("歷史資料不足或異常")
            if pd.isna(df["Volume"].iloc[-1]) or df["Volume"].iloc[-1] <= 0: raise Exception("無成交量")

            mkt = self.data_engine.load_market(target_code, data_quality['latest_price_date'])
            data = self.data_engine.prepare_indicators(df, mkt)

            data_quality['mkt_latest_date'] = data.get('mkt_latest_date', '無資料')
            data['data_quality'] = data_quality

            fundamental = self.fundamental_engine.calculate(rev_df, now.strftime("%Y-%m-%d"))
            fish = self.fish_engine.calculate(data, custom_params)
            retreat = self.retreat_engine.calculate(data, custom_params)
            warning = self.warning_engine.calculate(data)
            endurance = self.endurance_engine.calculate(data)
            defense = self.defense_engine.calculate(data, market_data={"df": mkt})

            chip = self.chip_engine.calculate(data, effective_mode)
            chip_xray = self.xray_engine.calculate(tdcc_df, fish["fish_score"], retreat["retreat_score"])
            position = self.position_engine.calculate(data, fish, retreat, warning, endurance, defense, fundamental, chip, chip_xray)

            all_errors = data_quality.get('errors', []) + fish.get('error_details', []) + retreat.get('error_details', []) + warning.get('error_details', []) + endurance.get('error_details', []) + defense.get('error_details', [])
            data['data_quality']['errors'] = all_errors

            mode_info = {'requested': requested_mode, 'effective': effective_mode}
            self.dashboard_engine.generate_report(stock_id, fish, retreat, position, endurance, warning, defense, chip, chip_xray, fundamental, data_quality, mode_info)

            return {
                "stock_id": stock_id, "fish": fish, "retreat": retreat, "position": position,
                "endurance": endurance, "warning": warning, "defense": defense, "chip": chip,
                "chip_xray": chip_xray, "fundamental": fundamental, "data_quality": data_quality,
                "is_optimized": is_optimized, "all_errors": all_errors, "mode_info": mode_info
            }
        except Exception as e:
            print(f"[{stock_id}] 分析過程遭遇錯誤: {str(e)}")
            return {"stock_id": stock_id, "position": {"candidate_status": "【分析失敗】資料異常"}, "all_errors": [str(e)]}




# ==============================================================================
# Cell 15: Excel Export Module (可選輸出工具)
# ==============================================================================

def format_check(status):
    if status == "Error": return "⚠️錯誤"
    elif status == "Unknown": return "❓未知"
    elif status is None: return "-"
    elif status: return "🚨觸發"
    else: return "✅安全"

def format_fish_check(status):
    if status == "Error": return "⚠️錯誤"
    elif status is None: return "-"
    elif status: return "O"
    else: return "X"

def export_v25_6_to_excel(results, output_filename=None):
    if not results:
        return None
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl 未安裝，無法匯出 Excel")
        return None

    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")

    as_of_date = datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M:%S")
    summary_ws.append([f"報表產出時間: {as_of_date}", "", "市場別: 台灣 (TSE/OTC)", "", "貨幣: TWD", "價格口徑: 實戰價"])
    summary_ws.append(["註：報表中之型態、代理等用語為量價規則式判讀，非絕對事實，請搭配實際市場籌碼服用。"])
    summary_ws.append(["*免責註記：防守價以還原價基準配上 ATR 計算後再轉回實戰價；極端除權息或系統拒絕評估時標示為無效。"])
    summary_ws.append([])

    headers = [
        "股票", "參數狀態", "大局狀態", "機會分數", "魚頭分數", "綜合撤退風險", "綜合預警狀態",
        "基本面標籤", "營收 YoY", "營收 MoM", "集保X光狀態", "型態防禦", "健康等級",
        "續航力狀態", "魚體位置", "目前價(Raw)", "實戰防守價(ATR)", "60日加權均價",
        "大戶籌碼動向", "實戰期望/風險評估", "底層錯誤追蹤", "運作模式"
    ]
    summary_ws.append(headers)

    for r in results:
        if not r or "position" not in r: continue
        pos = r.get("position", {})
        fsh = r.get("fish", {})
        ret = r.get("retreat", {})
        war = r.get("warning", {})
        endur = r.get("endurance", {})
        fund = r.get("fundamental", {})
        xray = r.get("chip_xray", {})
        defen = r.get("defense", {})
        dq = r.get("data_quality", {})
        m_inf = r.get("mode_info", {})

        row_data = [
            r.get("stock_id", "-"),
            "🌟客製優化" if r.get("is_optimized") else "🔹系統預設",
            pos.get("candidate_status", "-"),
            pos.get("opportunity_score", 0),
            fsh.get("fish_score", 0),
            ret.get("retreat_status", "-"),
            war.get("warning_status", "-"),
            fund.get("revenue_status", "-"),
            fund.get("yoy", "-"),
            fund.get("mom", "-"),
            xray.get("status", "-"),
            defen.get("defense_status", "-"),
            pos.get("health_level", "-"),
            endur.get("endurance_status", "-"),
            pos.get("fish_position", "-"),
            pos.get("current_raw_price", 0),
            pos.get("real_stop_loss_price", 0),
            pos.get("vwap60", 0),
            xray.get("movement_label", "-"),
            pos.get("risk_assessment", "-"),
            "; ".join(r.get("all_errors", [])) if r.get("all_errors") else "無",
            m_inf.get("effective", "盤後")
        ]
        summary_ws.append(row_data)

    if not output_filename:
        v_clean = WHALE_VERSION.replace(" ", "_").replace(".", "_")
        time_str = datetime.now(pytz.timezone('Asia/Taipei')).strftime("%Y%m%d")
        output_filename = f"{v_clean}_Report_{time_str}.xlsx"

    wb.save(output_filename)
    return output_filename
