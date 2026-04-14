"""BaoStock 数据源"""
import pandas as pd
from loguru import logger
from data.base import DataSource

_bs_session = None


class BaoStockSource(DataSource):
    """BaoStock 数据源 - 免费、稳定、需登录"""

    def __init__(self):
        super().__init__(name="BaoStock", priority=5)

    def connect(self) -> bool:
        global _bs_session
        try:
            import baostock as bs
            if _bs_session is None:
                bs.login()
                _bs_session = bs
            self._connected = True
            logger.info("[BaoStock] 连接成功")
            return True
        except Exception as e:
            logger.error(f"[BaoStock] 连接失败: {e}")
            return False

    @staticmethod
    def _symbol_format(symbol: str) -> str:
        """转换为 BaoStock 格式: sh.600000 / sz.000001"""
        symbol = str(symbol).zfill(6)
        if symbol.startswith("6") or symbol.startswith("9"):
            return f"sh.{symbol}"
        else:
            return f"sz.{symbol}"

    @staticmethod
    def _date_format(date: str) -> str:
        """YYYYMMDD -> YYYY-MM-DD"""
        if "-" in date:
            return date
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            bs = _bs_session
            bs_symbol = self._symbol_format(symbol)
            rs = bs.query_history_k_data_plus(
                bs_symbol,
                "date,open,high,low,close,volume,amount,Turn,pctChg",
                start_date=self._date_format(start_date),
                end_date=self._date_format(end_date),
                frequency="d",
                adjustflag="2"  # 前复权
            )
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())

            if data_list:
                cols = ["date", "open", "high", "low", "close", "volume", "amount", "turn", "pct_change"]
                df = pd.DataFrame(data_list, columns=cols)
                # pctChg is percentage, keep as is
                df["pct_change"] = pd.to_numeric(df["pct_change"], errors="coerce")
                result = self.standardize(df)
                logger.info(f"[BaoStock] 日线成功: {symbol} {len(result)} 条")
                return result
        except Exception as e:
            logger.error(f"[BaoStock] 日线失败 {symbol}: {e}")
        return pd.DataFrame()

    def fetch_stock_list(self) -> pd.DataFrame:
        try:
            bs = _bs_session
            rs = bs.query_stock_industry()
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())
            if data_list:
                df = pd.DataFrame(data_list, columns=["code", "code_name", "industry", "industryClassification"])
                df = df.rename(columns={"code": "symbol", "code_name": "name"})
                logger.info(f"[BaoStock] 股票列表: {len(df)} 只")
                return df
        except Exception as e:
            logger.error(f"[BaoStock] 股票列表失败: {e}")
        return pd.DataFrame()

    def fetch_weekly(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取周线"""
        try:
            bs = _bs_session
            bs_symbol = self._symbol_format(symbol)
            rs = bs.query_history_k_data_plus(
                bs_symbol,
                "date,open,high,low,close,volume,amount",
                start_date=self._date_format(start_date),
                end_date=self._date_format(end_date),
                frequency="w",
                adjustflag="2"
            )
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())
            if data_list:
                cols = ["date", "open", "high", "low", "close", "volume", "amount"]
                df = pd.DataFrame(data_list, columns=cols)
                return self.standardize(df)
        except Exception as e:
            logger.warning(f"[BaoStock] 周线失败: {e}")
        return pd.DataFrame()

    def fetch_monthly(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取月线"""
        try:
            bs = _bs_session
            bs_symbol = self._symbol_format(symbol)
            rs = bs.query_history_k_data_plus(
                bs_symbol,
                "date,open,high,low,close,volume,amount",
                start_date=self._date_format(start_date),
                end_date=self._date_format(end_date),
                frequency="m",
                adjustflag="2"
            )
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())
            if data_list:
                cols = ["date", "open", "high", "low", "close", "volume", "amount"]
                df = pd.DataFrame(data_list, columns=cols)
                return self.standardize(df)
        except Exception as e:
            logger.warning(f"[BaoStock] 月线失败: {e}")
        return pd.DataFrame()

    def is_available(self) -> bool:
        return _bs_session is not None
