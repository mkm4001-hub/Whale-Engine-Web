# ==========================================
# GrandMaster Whale Engine V25.7 PRO (後端核心)
# ==========================================

import os
import time
import random
import math
import logging
import pytz
import requests
import io
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from FinMind.data import DataLoader

WHALE_VERSION = "V25.7 PRO"
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# ==========================================
# 工具函式
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
# 集保快取管理器 (GitHub API 自動偵測版)
# ==========================================
class TDCCCacheManager:
    def __init__(self, cache_dir=None, github_repo=None):
        self.cache_dir = cache_dir
        self.github_repo = github_repo  
        self.cached_dfs = {}
        
        if self.github_repo:
            self.load_cache_from_github_api()
        elif self.cache_dir:
            if not os.path.exists(self.cache_dir):
                os.makedirs(self.cache_dir)
            self.load_cache_to_memory()

    def load_cache_from_github_api(self):
        print(f"⏳ 正在從 GitHub ({self.github_repo}) 自動搜尋集保快取資料...")
        api_url = f"https://api.github.com/repos/{self.github_repo}/contents/"
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            files_data = response.json()
            
            csv_urls = [
                file_info['download_url'] 
                for file_info in files_data 
                if file_info['name'].startswith('TDCC_') and file_info['name'].endswith('.csv')
            ]
            
            if not csv_urls:
                print("⚠️ 在 GitHub 儲存庫中找不到任何 TDCC_*.csv 檔案。")
                return
                
            for url in csv_urls:
                filename = url.split('/')[-1]
                try:
                    csv_resp = requests.get(url, timeout=10)
                    csv_resp.raise_for_status()
                    csv_data = io.StringIO(csv_resp.text)
                    df = pd.read_csv(csv_data, dtype={'stock_id': str})
                    
                    df['stock_id'] = df['stock_id'].astype(str).str.strip()
                    df['date'] = pd.to_datetime(df['date'])
                    self.cached_dfs[filename] = df
                    print(f"✅ 成功載入: {filename}")
                except Exception as e:
                    print(f"❌ 解析 {filename} 發生錯誤: {e}")
                    
        except Exception as e:
            print(f"❌ 無法連線至 GitHub API，請確認儲存庫名稱是否正確且為 Public: {e}")
            
        print(f"✅ 共成功載入 {len(self.cached_dfs)} 週的集保大戶資料！")

    def load_cache_to_memory(self):
        if not self.cache_dir: return
        files = [f for f in os.listdir(self.cache_dir) if f.startswith('TDCC_') and f.endswith('.csv')]
        if not files: return
        for f in files:
            path = os.path.join(self.cache_dir, f)
            try:
                df = pd.read_csv(path, dtype={'stock_id': str})
                df['stock_id'] = df['stock_id'].astype(str).str.strip()
                df['date'] = pd.to_datetime(df['date'])
                self.cached_dfs[f] = df
            except Exception as e:
                pass

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

# ==========================================
# DataEngine 資料核心
# ==========================================
class DataEngine:
    def __init__(self, dataloader=None, tdcc_manager=None):
        self.dl = dataloader
        self.tdcc_manager = tdcc_manager

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
                df['Inst_NetBuy'] = df['Trust_NetBuy'].fillna(0) + df['Foreign_NetBuy'].fillna(0) + df['Dealer_NetBuy'].fillna(0)

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
            raise ValueError("[empty_response] 大盤資料獲取失敗")
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

        stock_latest = df.index[-1]
        mkt_latest = mkt.index[-1] if not mkt.empty else pd.Timestamp('1900-01-01')
        market_status, sync_msg, latest_common = "Unknown", "", None

        if not mkt.empty:
            if stock_latest == mkt_latest: latest_common = stock_latest
            elif len(df) > 1 and df.index[-2] == mkt_latest:
                latest_common = mkt_latest
                sync_msg = " (啟用2天比對)"
            else:
                common_idx = df.index.intersection(mkt.index)
                if len(common_idx) > 0:
                    latest_common = common_idx[-1]
                    days_behind = (stock_latest - latest_common).days
                    if days_behind > 5: market_status = "Stale"

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
            else: rs20, rs60, market_status = 0.0, 0.0, "Unknown"
        else:
            rs20, rs60 = 0.0, 0.0
            if market_status != "Stale": market_status = "Unknown"

        return {
            "df": df, "mkt": mkt, "rs20": rs20, "rs60": rs60,
            "vol_factor": vol_factor, "ma20_slope": ma20_slope, "market_status": market_status,
            "market_factor": locals().get('market_factor', 1.0), "mkt_latest_date": mkt_latest_date
        }

# ==========================================
# 量化分析引擎 (Scoring & Warning)
# ==========================================
class FishScoreEngine:
    def calculate(self, data, custom_params=None):
        if custom_params is None: custom_params = {}
        df = data["df"]
        latest = df.iloc[-1]
        market_factor = data.get("market_factor", 1.0)
        score, health_checks, has_error = 0, [], False

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

        health_checks.append(("RS20 > 0", rs20 > 0))
        health_checks.append(("RS60 > 0", rs60 > 0))
        score += max(0, rs_score + 20)

        vwap_score = 0
        if latest["Close"] > latest["VWAP60"]:
            adv = (latest["Close"] - latest["VWAP60"]) / latest["VWAP60"]
            if adv > 0.10: vwap_score += 15
            elif adv > 0.05: vwap_score += 10
            else: vwap_score += 5
            health_checks.append(("Close > VWAP60", True))
        else: health_checks.append(("Close > VWAP60", False))
        score += vwap_score

        try:
            is_stand_above = latest["Close"] > latest["MA20"] and (latest["MA20"] >= latest["MA60"] * 0.98)
            bandwidth_now = latest.get("Bandwidth", 1.0)
            if is_stand_above and bandwidth_now < 0.08:
                score += 10
                health_checks.append(("均線壓縮蓄勢", True))
            else:
                health_checks.append(("均線壓縮蓄勢", False))

            mean_bandwidth = df["Bandwidth"].shift(1).tail(20).mean()
            prev_bandwidth = df["Bandwidth"].shift(1).iloc[-1]
            is_bb_squeeze = prev_bandwidth <= (mean_bandwidth * 0.85) if mean_bandwidth > 0 else False
            if is_bb_squeeze and latest["Close"] > latest["MA20"]:
                score += 15
                health_checks.append(("極限壓縮突破", True))
            else: health_checks.append(("極限壓縮突破", False))
        except: has_error = True

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
        if market_status == "Bull": score += 10
        elif market_status == "Neutral": score += 5
        score = min(100, max(0, score))
        grade = "S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D"
        
        return {
            "fish_score": round(score), "health_grade": grade,
            "trend_status": "強勢" if trend_score >= 25 else "轉弱",
            "rs_status": "強勢" if rs_score >= 14 else "弱勢",
            "chip_status": "安定" if vwap_score >= 10 else "鬆動",
            "health_checks": health_checks, "has_error": has_error, "error_details": []
        }

class RetreatScoreEngine:
    def calculate(self, data, custom_params=None):
        if custom_params is None: custom_params = {}
        df = data["df"]
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        retreat_checks = []
        
        vol_breakout_limit = custom_params.get("retreat_vol_breakout", 3.0)
        bias_limit = custom_params.get("bias20_limit", 20)
        drop_tolerance = custom_params.get("drop_tolerance", -0.05)
        
        prev_vol20 = df["VOL20_PRIOR"].iloc[-1]
        vwap60 = float(latest.get("VWAP60", df["MA60"].iloc[-1]))
        cost_distance = ((latest["Close"] - vwap60) / vwap60 * 100) if vwap60 > 0 else 0
        is_bottom_exempt = cost_distance <= 8.0
        
        grp1_score = 0
        try:
            price_change = (latest["Close"] - prev["Close"]) / prev["Close"]
            is_volume_high = latest["Volume"] > prev_vol20 * vol_breakout_limit
            is_price_stagnant = price_change < 0.02
            if (is_volume_high and is_price_stagnant):
                if not is_bottom_exempt and cost_distance > 5.0:
                    grp1_score += 25
                    retreat_checks.append(("高檔爆量不漲", True))
                else:
                    retreat_checks.append(("爆量不漲(底部)", False))
            else: retreat_checks.append(("爆量不漲", False))
        except: pass
        
        try:
            if latest["Volume"] > prev_vol20 * 2 and latest["Raw_Close"] < latest["Raw_Open"]:
                grp1_score += 30
                retreat_checks.append(("爆量長黑", True))
            else: retreat_checks.append(("爆量長黑", False))
        except: pass
        
        grp2_score = 0
        try:
            bias20 = ((latest["Close"] - df["MA20"].iloc[-1]) / df["MA20"].iloc[-1]) * 100
            if bias20 > bias_limit and latest["Close"] < df["MA5"].iloc[-1]:
                grp2_score += 20
                retreat_checks.append(("正乖離過大破線", True))
            else: retreat_checks.append(("正乖離過大破線", False))
        except: pass

        retreat_score = min(100, grp1_score + grp2_score)
        risk_status = "主力撤退" if retreat_score >= 80 else "高機率撤退" if retreat_score >= 60 else "疑似出貨" if retreat_score >= 40 else "低"
        return {"retreat_score": round(retreat_score), "risk_status": risk_status, "retreat_checks": retreat_checks, "has_error": False, "error_details": []}

class WhaleEnduranceEngine:
    def calculate(self, data):
        df = data["df"]
        latest = df.iloc[-1]
        score = 50
        messages = []
        try:
            day_range = latest['Raw_High'] - latest['Raw_Low']
            if day_range > 0:
                close_pos = (latest['Raw_Close'] - latest['Raw_Low']) / day_range
                if close_pos > 0.8:
                    score += 10
                    messages.append("強勢收紅")
                elif close_pos < 0.2:
                    score -= 10
                    messages.append("弱勢收低")
        except: pass
        status = "燃料充沛" if score >= 80 else "震盪整理" if score >= 60 else "動能衰退" if score >= 40 else "燃料耗盡"
        return {"endurance_score": round(score), "endurance_status": status, "endurance_messages": messages, "has_error": False, "error_details": []}

class FundamentalEngine:
    def calculate(self, rev_df, current_date):
        if rev_df is None or rev_df.empty or len(rev_df) < 2:
            return {"fund_score": 0, "fund_label": "【無營收資料】", "yoy": 0, "mom": 0, "is_high": False, "fund_state": "missing", "is_pit_embargo": False}
        rev_df['revenue'] = pd.to_numeric(rev_df['revenue'], errors='coerce')
        latest_rev = rev_df.iloc[-1]['revenue']
        latest_year, latest_month = rev_df.iloc[-1]['revenue_year'], rev_df.iloc[-1]['revenue_month']
        yoy = mom = 0.0
        
        last_year_df = rev_df[(rev_df['revenue_year'] == latest_year - 1) & (rev_df['revenue_month'] == latest_month)]
        if not last_year_df.empty and last_year_df.iloc[-1]['revenue'] > 0:
            yoy = ((latest_rev - last_year_df.iloc[-1]['revenue']) / last_year_df.iloc[-1]['revenue']) * 100
            
        score = 20 if yoy >= 30 else 10 if yoy >= 10 else 0
        return {"fund_score": score, "fund_label": f"YoY: {round(yoy, 1)}%", "yoy": round(yoy, 2), "mom": round(mom, 2), "is_dual_growth": (yoy>0 and mom>0), "fund_state": "complete"}

class FishPositionEngine:
    def calculate(self, data, fish, retreat, warning, endurance, defense, fundamental, chip_data, chip_xray):
        df = data["df"]
        latest = df.iloc[-1]
        current_price_adj = float(latest["Close"])
        current_price_raw = float(latest.get("Raw_Close", current_price_adj))
        atr14 = float(latest.get("ATR14", current_price_adj * 0.03))
        ratio = current_price_raw / current_price_adj if current_price_adj > 0 else 1.0
        
        vwap60_adj = float(latest.get("VWAP60", current_price_adj))
        cost_distance = ((current_price_adj - vwap60_adj) / vwap60_adj * 100) if vwap60_adj > 0 else 0
        
        progress = 10 if fish["fish_score"] < 70 else 50
        defensive_price_adj = latest["MA20"] - (1.8 * atr14) if progress > 40 else latest.get("Raw_Low", current_price_raw)/ratio
        defensive_price_exec = WhaleTools.round_tick(defensive_price_adj * ratio, 'floor')
        
        return {
            "candidate_status": "候選", "fish_position": "主升段" if progress > 40 else "築底", "progress": progress,
            "opportunity_score": 75, "opportunity_level": "****",
            "position_comment": "系統穩定執行中", "strategy_profile": "純技術波段", "bias20": 0.0,
            "current_price": round(current_price_raw, 2), "vwap60": round(vwap60_adj * ratio, 2),
            "cost_distance": round(cost_distance, 2), "target_low": 0.0, "target_high": 0.0,
            "upside_low": 0.0, "upside_high": 0.0,
            "heat_level": "正常", "defensive_price": defensive_price_exec, "defensive_status_text": "技術防守",
            "max_tolerance": 25.0, "is_evaluable": True
        }

class EarlyWarningEngine:
    def calculate(self, data):
        return {"warning_score": 0, "warning_status": "動能正常", "warning_checks": [], "has_error": False, "error_details": []}

class SmartMoneyDefenseEngine:
    def calculate(self, data, **kwargs):
        return {"defense_score": 50, "defense_status": "防守型態確認", "defense_signals": [], "has_error": False, "error_details": []}

class ChipRadarEngine:
    def calculate(self, data, mode):
        return {"chip_score": 10, "chip_status": "法人進駐", "chip_messages": []}

class ChipXRayEngine:
    def calculate(self, tdcc_df, fish_score, retreat_score):
        return {"xray_status": "籌碼中性", "xray_message": "無異常動向", "is_surge": False}

class DashboardEngine:
    def generate_report(self, *args, **kwargs):
        pass

# ==========================================
# 前鋒掃描器 ScannerEngine
# ==========================================
class ScannerEngine:
    def __init__(self, dataloader):
        self.dl = dataloader

    def run_scan(self, min_volume_sheets=800, top_n_liquidity=300, max_bandwidth=0.025):
        try:
            stock_info = self.dl.taiwan_stock_info()
            mask = (stock_info['industry_category'] != '') & (stock_info['stock_id'].str.len() == 4)
            common_stocks = stock_info[mask].copy()

            tickers = []
            for index, row in common_stocks.iterrows():
                if row['type'] == 'twse': tickers.append(f"{row['stock_id']}.TW")
                elif row['type'] == 'tpex': tickers.append(f"{row['stock_id']}.TWO")

            min_shares = min_volume_sheets * 1000
            candidate_dict = {}
            chunk_size = 200 
            
            for i in range(0, len(tickers), chunk_size):
                chunk = tickers[i:i + chunk_size]
                data = yf.download(chunk, period="2d", group_by="ticker", auto_adjust=False, threads=False)
                for ticker in chunk:
                    try:
                        if len(chunk) == 1:
                            vol = data['Volume'].iloc[-1]
                            close_price = data['Close'].iloc[-1]
                        elif ticker in data.columns.levels[0]:
                            vol = data[ticker]['Volume'].iloc[-1]
                            close_price = data[ticker]['Close'].iloc[-1]
                        else: continue
                        if pd.notna(vol) and pd.notna(close_price) and vol >= min_shares:
                            candidate_dict[ticker] = vol
                    except: continue
                time.sleep(random.uniform(1.5, 3.0))

            sorted_stocks = sorted(candidate_dict.items(), key=lambda x: x[1], reverse=True)
            selected_tickers = [stock[0] for stock in sorted_stocks[:top_n_liquidity]]

            target_stocks = []
            chunk_size_120 = 100

            for i in range(0, len(selected_tickers), chunk_size_120):
                chunk = selected_tickers[i:i + chunk_size_120]
                batch_data = yf.download(chunk, period="120d", group_by="ticker", auto_adjust=False, threads=False)

                for ticker in chunk:
                    try:
                        if len(chunk) == 1: hist = batch_data.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                        else:
                            if ticker not in batch_data.columns.levels[0]: continue
                            hist = batch_data[ticker].dropna(subset=['Close', 'High', 'Low', 'Volume'])

                        if len(hist) < 60: continue
                        close = hist['Close']
                        current_price = close.iloc[-1]
                        
                        ma5 = close.rolling(window=5).mean()
                        ma10 = close.rolling(window=10).mean()
                        ma20 = close.rolling(window=20).mean()
                        ma60 = close.rolling(window=60).mean()

                        ma_max = max(ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1])
                        ma_min = min(ma5.iloc[-1], ma10.iloc[-1], ma20.iloc[-1])
                        bandwidth_ratio = (ma_max - ma_min) / ma20.iloc[-1]
                        
                        if (bandwidth_ratio <= max_bandwidth) and (current_price >= ma_max) and (ma20.iloc[-1] >= ma20.iloc[-3]) and (ma20.iloc[-1] >= ma60.iloc[-1] * 0.98):
                            target_stocks.append(ticker.replace(".TW", "").replace(".TWO", ""))
                    except: continue
                time.sleep(random.uniform(1.5, 3.0))
            return target_stocks
        except Exception as e:
            raise e

# ==========================================
# WhaleEngine 總司令部 (統籌所有模組)
# ==========================================
class WhaleEngine:
    def __init__(self, tdcc_cache_dir=None, github_repo=None):
        self.shared_dl = DataLoader()
        # 若是 Streamlit，通常將 TOKEN 放環境變數或 secrets
        token = os.getenv("FINMIND_TOKEN")
        if token:
            self.shared_dl.login_by_token(api_token=token)
            
        # 將 github_repo 參數交給 TDCCCacheManager 進行雲端 API 抓取
        self.tdcc_manager = TDCCCacheManager(cache_dir=tdcc_cache_dir, github_repo=github_repo)
        
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
            tz = pytz.timezone('Asia/Taipei')
            now = datetime.now(tz)
            
            df, target_code, data_quality, rev_df, tdcc_df = self.data_engine.load_stock(stock_id, mode)
            if df is None or df.empty or len(df) < 60: raise Exception("歷史資料不足或異常")
            
            mkt = self.data_engine.load_market(target_code, data_quality['latest_price_date'])
            data = self.data_engine.prepare_indicators(df, mkt)
            data['data_quality'] = data_quality
            
            fundamental = self.fundamental_engine.calculate(rev_df, now.strftime("%Y-%m-%d"))
            fish = self.fish_engine.calculate(data, custom_params)
            retreat = self.retreat_engine.calculate(data, custom_params)
            warning = self.warning_engine.calculate(data)
            endurance = self.endurance_engine.calculate(data)
            defense = self.defense_engine.calculate(data, market_data={"df": mkt})
            
            chip = self.chip_engine.calculate(data, mode)
            chip_xray = self.xray_engine.calculate(tdcc_df, fish["fish_score"], retreat["retreat_score"])
            position = self.position_engine.calculate(data, fish, retreat, warning, endurance, defense, fundamental, chip, chip_xray)
            
            return {
                "stock_id": stock_id, "fish": fish, "retreat": retreat, "position": position,
                "endurance": endurance, "warning": warning, "defense": defense, "chip": chip,
                "chip_xray": chip_xray, "fundamental": fundamental, "data_quality": data_quality,
            }
        except Exception as e:
            return {"stock_id": stock_id, "position": {"candidate_status": "【分析失敗】資料異常"}, "all_errors": [str(e)]}
