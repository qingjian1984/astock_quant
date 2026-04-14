"""策略基类"""
from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """策略基类，所有策略需继承此类"""

    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}
        self.positions = {}  # {symbol: volume}
        self.cash = 1000000.0  # 初始资金100万

    @abstractmethod
    def on_bar(self, symbol: str, bar: pd.Series, context: dict) -> dict:
        """
        每根K线调用，返回交易信号
        Returns: {"action": "buy"/"sell"/"hold", "volume": int}
        """
        pass

    def buy(self, symbol: str, volume: int, price: float) -> dict:
        """生成买入信号"""
        return {"action": "buy", "symbol": symbol, "volume": volume, "price": price}

    def sell(self, symbol: str, volume: int, price: float) -> dict:
        """生成卖出信号"""
        return {"action": "sell", "symbol": symbol, "volume": volume, "price": price}

    def hold(self) -> dict:
        return {"action": "hold"}
