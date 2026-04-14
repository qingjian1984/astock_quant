"""MACD 趋势跟踪策略"""
import pandas as pd
from strategy.base import BaseStrategy


class MACDStrategy(BaseStrategy):
    """
    MACD 策略：DIF 上穿 DEA 买入，下穿卖出
    默认参数: fast=12, slow=26, signal=9
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__("MACD", {"fast": fast, "slow": slow, "signal": signal})
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    def on_bar(self, context: dict) -> list:
        signals = []
        for symbol, data in context["data"].items():
            if len(data) < self.slow + self.signal_period:
                continue

            close = data["close"]
            ema_fast = close.ewm(span=self.fast, adjust=False).mean()
            ema_slow = close.ewm(span=self.slow, adjust=False).mean()
            dif = ema_fast - ema_slow
            dea = dif.ewm(span=self.signal_period, adjust=False).mean()

            curr_dif = dif.iloc[-1]
            curr_dea = dea.iloc[-1]
            prev_dif = dif.iloc[-2]
            prev_dea = dea.iloc[-2]

            price = context["current_bar"][symbol]["close"]
            position = context["positions"].get(symbol, 0)

            # 金叉买入
            if prev_dif <= prev_dea and curr_dif > curr_dea and position == 0:
                alloc = context["total_value"] * 0.25
                volume = int(alloc / price / 100) * 100
                if volume >= 100:
                    signals.append(self.buy(symbol, volume, "MACD金叉"))

            # 死叉卖出
            elif prev_dif >= prev_dea and curr_dif < curr_dea and position > 0:
                signals.append(self.sell(symbol, position, "MACD死叉"))

        return signals
