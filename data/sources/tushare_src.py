"""Tushare Pro 数据源"""
import pandas as pd
from loguru import logger
from data.base import DataSource


class TushareSource(DataSource):
    """Tushare Pro 数据源 - 需 token，数据质量好"""

    def __init__(self, token: str = None):
        super().__init__(name="Tushare", priority=8)
        self.token = token
        self.pro = None
        self._connected = False

    def connect(self) -> bool:
        if not self.token:
            logger.warning("[Tushare] 未配置 token，跳过")
            return False
        try:
            import tushare as ts
            ts.set_token(self.token)
            self.pro = ts.pro_api(self.token)
            self._connected = True
            logger.info("[Tushare] 连接成功")
            return True
        except Exception as e:
            logger.error(f"[Tushare] 连接失败: {e}")
            return False

    def _symbol_format(self, symbol: str) -> str:
        """转换为 Tushare 格式: 000001.SZ / 600000.SH"""
        symbol = str(symbol).zfill(6)
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        else:
            return f"{symbol}.SZ"

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        if not self._connected:
            return pd.DataFrame()
        try:
            ts_code = self._symbol_format(symbol)
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )
            if df is not None and not df.empty:
                # 获取复权因子计算前复权
                adj = self.pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if adj is not None and not adj.empty:
                    df = df.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
                    # 用最后一个复权因子标准化
                    last_factor = adj["adj_factor"].iloc[-1]
                    df["adj_close"] = df["close"] * df["adj_factor"] / last_factor
                    df["adj_open"] = df["open"] * df["adj_factor"] / last_factor
                    df["adj_high"] = df["high"] * df["adj_factor"] / last_factor
                    df["adj_low"] = df["low"] * df["adj_factor"] / last_factor
                    df = df.rename(columns={
                        "adj_open": "open", "adj_high": "high",
                        "adj_low": "low", "adj_close": "close"
                    })

                df = df.rename(columns={"trade_date": "date"})
                result = self.standardize(df)
                logger.info(f"[Tushare] 日线成功: {symbol} {len(result)} 条")
                return result
        except Exception as e:
            logger.warning(f"[Tushare] 日线失败 {symbol}: {e}")
        return pd.DataFrame()

    def fetch_stock_list(self) -> pd.DataFrame:
        if not self._connected:
            return pd.DataFrame()
        try:
            df = self.pro.stock_basic(exchange="", list_status="L",
                                      fields="ts_code,symbol,name,area,industry,list_date")
            if df is not None and not df.empty:
                df = df.rename(columns={"ts_code": "ts_code", "symbol": "symbol", "name": "name"})
                logger.info(f"[Tushare] 股票列表: {len(df)} 只")
                return df
        except Exception as e:
            logger.error(f"[Tushare] 股票列表失败: {e}")
        return pd.DataFrame()

    def fetch_daily_basic(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取每日指标（PE/PB/市值等）"""
        if not self._connected:
            return pd.DataFrame()
        try:
            ts_code = self._symbol_format(symbol)
            df = self.pro.daily_basic(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pb,total_mv,circ_mv"
            )
            if df is not None and not df.empty:
                df = df.rename(columns={"trade_date": "date"})
                return self.standardize(df)
        except Exception as e:
            logger.warning(f"[Tushare] 每日指标失败: {e}")
        return pd.DataFrame()

    def is_available(self) -> bool:
        return self._connected and self.pro is not None
