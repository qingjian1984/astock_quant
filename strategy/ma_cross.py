"""双均线交叉策略 - A股版"""
import pandas as pd
from strategy.base import BaseStrategy


class MACrossStrategy(BaseStrategy):
    """
    双均线策略：短期均线上穿长期均线买入，下穿卖出
    默认参数: fast=5, slow=20
    """

    def __init__(self, fast: int = 5, slow: int = 20, name: str = "MA_Cross"):
        super().__init__(name)
        self.fast = fast
        self.slow = slow
        self.history = {}  # {symbol: DataFrame}

    def on_bar(self, symbol: str, bar: pd.Series, context: dict) -> dict:
        """
        bar: 当前K线数据
        context: {"data": 完整历史DataFrame, "positions": 持仓, "cash": 现金}
        """
        data = context.get("data", pd.DataFrame())
        if data.empty or len(data) < self.slow:
            return self.hold()

        # 计算均线
        close = data["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()

        # 当前和上一时刻的信号
        curr_fast = fast_ma.iloc[-1]
        curr_slow = slow_ma.iloc[-1]
        prev_fast = fast_ma.iloc[-2]
        prev_slow = slow_ma.iloc[-2]

        price = bar.get("close", bar.get("close"))
        position = context.get("positions", {}).get(symbol, 0)

        # 金叉买入
        if prev_fast <= prev_slow and curr_fast > curr_slow and position == 0:
            # 计算可买数量（A股100股整数倍）
            volume = int((context.get("cash", 0) * 0.95) / price / 100) * 100
            if volume >= 100:
                return self.buy(symbol, volume, price)

        # 死叉卖出
        if prev_fast >= prev_slow and curr_fast < curr_slow and position > 0:
            return self.sell(symbol, position, price)

        return self.hold()
