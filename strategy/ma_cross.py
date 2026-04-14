"""双均线交叉策略 - A股版（多标的支持）"""
import pandas as pd
from strategy.base import BaseStrategy


class MACrossStrategy(BaseStrategy):
    """
    双均线策略：短期均线上穿长期均线买入，下穿卖出
    """

    def __init__(self, fast: int = 5, slow: int = 20):
        super().__init__("MA_Cross", {"fast": fast, "slow": slow})
        self.fast = fast
        self.slow = slow

    def on_bar(self, context: dict) -> list:
        signals = []
        for symbol, data in context["data"].items():
            if len(data) < self.slow:
                continue

            close = data["close"]
            fast_ma = close.rolling(self.fast).mean()
            slow_ma = close.rolling(self.slow).mean()

            curr_fast = fast_ma.iloc[-1]
            curr_slow = slow_ma.iloc[-1]
            prev_fast = fast_ma.iloc[-2]
            prev_slow = slow_ma.iloc[-2]

            price = context["current_bar"][symbol]["close"]
            position = context["positions"].get(symbol, 0)

            # 金叉买入
            if prev_fast <= prev_slow and curr_fast > curr_slow and position == 0:
                alloc = context["total_value"] * 0.25  # 单票最多25%
                volume = int(alloc / price / 100) * 100
                if volume >= 100:
                    signals.append(self.buy(symbol, volume, f"MA{self.fast}上穿MA{self.slow}"))

            # 死叉卖出
            elif prev_fast >= prev_slow and curr_fast < curr_slow and position > 0:
                signals.append(self.sell(symbol, position, f"MA{self.fast}下穿MA{self.slow}"))

        return signals
