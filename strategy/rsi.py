"""RSI 均值回归策略"""
import pandas as pd
from strategy.base import BaseStrategy


class RSIStrategy(BaseStrategy):
    """
    RSI 策略：RSI < 30 超卖买入，RSI > 70 超买卖出
    """

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        super().__init__("RSI", {"period": period, "oversold": oversold, "overbought": overbought})
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def on_bar(self, context: dict) -> list:
        signals = []
        for symbol, data in context["data"].items():
            if len(data) < self.period + 1:
                continue

            close = data["close"]
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(self.period).mean()
            loss = (-delta.clip(upper=0)).rolling(self.period).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))

            curr_rsi = rsi.iloc[-1]
            prev_rsi = rsi.iloc[-2]
            price = context["current_bar"][symbol]["close"]
            position = context["positions"].get(symbol, 0)

            # 超卖反弹买入
            if prev_rsi <= self.oversold and curr_rsi > self.oversold and position == 0:
                alloc = context["total_value"] * 0.25
                volume = int(alloc / price / 100) * 100
                if volume >= 100:
                    signals.append(self.buy(symbol, volume, f"RSI超卖反弹({curr_rsi:.1f})"))

            # 超买卖出
            elif prev_rsi >= self.overbought and curr_rsi < self.overbought and position > 0:
                signals.append(self.sell(symbol, position, f"RSI超买回落({curr_rsi:.1f})"))

            # 止损：RSI继续跌破20
            elif position > 0 and curr_rsi < 20:
                signals.append(self.sell(symbol, position, f"RSI跌破20止损({curr_rsi:.1f})"))

        return signals
