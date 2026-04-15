"""网格交易策略 - 用于长线股做T降低成本"""
import pandas as pd
from strategy.base import BaseStrategy


class GridStrategy(BaseStrategy):
    """
    网格策略：在底仓基础上高抛低吸
    适用于长线持股期间做T
    """

    def __init__(self, base_symbol: str, grid_size: float = 0.02, grid_count: int = 5):
        """
        base_symbol: 对应长线股的代码
        grid_size: 网格大小 (2%)
        grid_count: 网格层数
        """
        super().__init__("Grid_T", {"base": base_symbol, "size": grid_size, "count": grid_count})
        self.base_symbol = base_symbol
        self.grid_size = grid_size
        self.grid_count = grid_count
        self.last_price = 0

    def on_bar(self, context: dict) -> list:
        signals = []

        # 只在长线股有持仓时才做T
        pos = context["positions"].get(self.base_symbol, 0)
        if pos == 0:
            return signals

        for symbol, bar in context["current_bar"].items():
            price = bar["close"]

            if self.last_price == 0:
                self.last_price = price
                continue

            pct_change = (price - self.last_price) / self.last_price

            # 跌到网格线 -> 买入做T
            if pct_change <= -self.grid_size:
                t_volume = int(pos * 0.1 / 100) * 100  # 每次做T 10%底仓
                if t_volume > 0:
                    signals.append(self.buy(self.base_symbol, t_volume, f"网格买入 (-{pct_change:.1%})"))
                self.last_price = price

            # 涨到网格线 -> 卖出做T
            elif pct_change >= self.grid_size:
                t_volume = int(pos * 0.1 / 100) * 100
                if t_volume > 0 and t_volume <= pos:
                    signals.append(self.sell(self.base_symbol, t_volume, f"网格卖出 (+{pct_change:.1%})"))
                self.last_price = price

        return signals
