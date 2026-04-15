"""数据源抽象基类"""
from abc import ABC, abstractmethod
import pandas as pd


class DataSource(ABC):
    """数据源基类，所有数据源需继承并实现以下方法"""

    def __init__(self, name: str, priority: int = 0, config: dict = None):
        self.name = name
        self.priority = priority  # 数字越大优先级越高
        self.config = config or {}
        self._connected = False

    @abstractmethod
    def connect(self) -> bool:
        """连接数据源，返回是否成功"""
        pass

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取日线数据
        返回标准格式: index=date, columns=[open, high, low, close, volume, amount, pct_change]
        """
        pass

    @abstractmethod
    def fetch_stock_list(self) -> pd.DataFrame:
        """获取股票列表"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass

    @staticmethod
    def standardize(df: pd.DataFrame, col_map: dict = None) -> pd.DataFrame:
        """统一标准化数据格式"""
        default_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "amount", "涨跌幅": "pct_change",
            "date": "date", "open": "open", "close": "close",
            "high": "high", "low": "low", "volume": "volume",
            "amount": "amount", "pct_change": "pct_change",
        }
        if col_map:
            default_map.update(col_map)

        df = df.rename(columns={k: v for k, v in default_map.items() if k in df.columns})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_change", "turn"]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def __repr__(self):
        status = "可用" if self.is_available() else "不可用"
        return f"DataSource({self.name}, priority={self.priority}, status={status})"
