"""AKShare 数据源"""
import akshare as ak
import pandas as pd
import time
from loguru import logger
from data.base import DataSource


class AKShareSource(DataSource):
    """AKShare 数据源 - 免费、覆盖全"""

    def __init__(self, retry: int = 3, timeout: int = 30):
        super().__init__(name="AKShare", priority=10)
        self.retry = retry
        self.timeout = timeout

    def connect(self) -> bool:
        """AKShare 无需连接，直接返回可用"""
        self._connected = True
        return True

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        for attempt in range(self.retry):
            logger.info(f"[AKShare] 日线: {symbol} {start_date}~{end_date} ({attempt+1}/{self.retry})")
            try:
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"
                )
                result = self.standardize(df, {
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                    "成交额": "amount", "涨跌幅": "pct_change"
                })
                if not result.empty:
                    logger.info(f"[AKShare] 成功: {len(result)} 条")
                    return result
            except Exception as e:
                logger.warning(f"[AKShare] 失败: {e}")
                if attempt < self.retry - 1:
                    time.sleep(2 * (attempt + 1))
        return pd.DataFrame()

    def fetch_stock_list(self) -> pd.DataFrame:
        try:
            df = ak.stock_zh_a_spot_em()
            cols = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "总市值"]
            df = df[[c for c in cols if c in df.columns]].copy()
            df = df.rename(columns={"代码": "symbol", "名称": "name", "最新价": "price",
                                     "涨跌幅": "pct_change", "成交量": "volume",
                                     "成交额": "amount", "总市值": "total_mv"})
            logger.info(f"[AKShare] 股票列表: {len(df)} 只")
            return df
        except Exception as e:
            logger.error(f"[AKShare] 股票列表失败: {e}")
            return pd.DataFrame()

    def fetch_minute(self, symbol: str, period: str = "5") -> pd.DataFrame:
        """获取分钟线"""
        try:
            df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust="qfq")
            return self.standardize(df, {
                "时间": "date", "开盘价": "open", "收盘价": "close",
                "最高价": "high", "最低价": "low", "成交量": "volume",
                "成交额": "amount", "涨跌幅": "pct_change"
            })
        except Exception as e:
            logger.warning(f"[AKShare] 分钟线失败: {e}")
            return pd.DataFrame()

    def fetch_index_daily(self, symbol: str = "000001", start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取指数日线"""
        try:
            df = ak.stock_zh_index_daily_em(
                symbol=f"sh{symbol}" if symbol.startswith("0") else f"sz{symbol}"
            )
            return self.standardize(df)
        except Exception as e:
            logger.warning(f"[AKShare] 指数日线失败: {e}")
            return pd.DataFrame()

    def is_available(self) -> bool:
        try:
            df = ak.stock_zh_a_spot_em()
            return df is not None and len(df) > 0
        except Exception:
            return False
