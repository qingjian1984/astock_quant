"""策略基类 - 多标的版本"""
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """
    策略基类
    context 结构:
        data: {symbol: 到当前的历史DataFrame}
        current_bar: {symbol: 当前K线}
        positions: {symbol: volume}
        cash: float
        total_value: float
        date: 当前日期
    """

    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}

    @abstractmethod
    def on_bar(self, context: dict) -> list:
        """
        返回信号列表
        每个信号: {"action": "buy"/"sell", "symbol": str, "volume": int, "reason": str}
        """
        pass

    @staticmethod
    def buy(symbol: str, volume: int, reason: str = "") -> dict:
        return {"action": "buy", "symbol": symbol, "volume": volume, "reason": reason}

    @staticmethod
    def sell(symbol: str, volume: int, reason: str = "") -> dict:
        return {"action": "sell", "symbol": symbol, "volume": volume, "reason": reason}
