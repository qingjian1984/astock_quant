"""Yahoo Finance 数据源（港股/美股）"""
import pandas as pd
from loguru import logger
from data.base import DataSource


class YahooFinanceSource(DataSource):
    """Yahoo Finance 数据源 - 港股/美股/全球市场"""

    def __init__(self):
        super().__init__(name="YahooFinance", priority=3)
        self._connected = False

    def connect(self) -> bool:
        try:
            import yfinance as yf
            self._connected = True
            logger.info("[YahooFinance] 可用")
            return True
        except ImportError:
            logger.warning("[YahooFinance] 未安装 yfinance，跳过")
            return False

    def _symbol_format(self, symbol: str) -> str:
        """转换为 Yahoo 格式"""
        symbol = str(symbol).upper()
        # A股
        if symbol.startswith("6") or len(symbol) == 6:
            if symbol.startswith("6"):
                return f"{symbol}.SS"
            else:
                return f"{symbol}.SZ"
        return symbol

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        if not self._connected:
            return pd.DataFrame()
        try:
            import yfinance as yf
            ticker = self._symbol_format(symbol)
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if df is not None and len(df) > 0:
                # yfinance returns multi-index columns
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0].lower() for col in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                df = df.rename(columns={"adj close": "close"})
                return self.standardize(df)
        except Exception as e:
            logger.warning(f"[YahooFinance] 日线失败 {symbol}: {e}")
        return pd.DataFrame()

    def fetch_stock_list(self) -> pd.DataFrame:
        """Yahoo Finance 不提供完整股票列表"""
        logger.warning("[YahooFinance] 不支持获取股票列表")
        return pd.DataFrame()

    def fetch_hk(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取港股数据"""
        return self.fetch_daily(symbol, start_date, end_date)

    def fetch_us(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取美股数据"""
        return self.fetch_daily(symbol, start_date, end_date)

    def is_available(self) -> bool:
        try:
            import yfinance as yf
            return True
        except ImportError:
            return False
