"""多因子选股策略"""
import pandas as pd
from strategy.base import BaseStrategy


class MultiFactorStrategy(BaseStrategy):
    """
    多因子选股：动量 + 波动率 + 市值（用小市值替代）
    每月调仓，选排名前 N 的股票
    """

    def __init__(self, top_n: int = 5, rebalance_days: int = 20, momentum_window: int = 20):
        super().__init__("MultiFactor", {"top_n": top_n, "rebalance_days": rebalance_days, "momentum_window": momentum_window})
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.momentum_window = momentum_window
        self.days_since_rebalance = rebalance_days  # 首次强制调仓

    def on_bar(self, context: dict) -> list:
        signals = []
        self.days_since_rebalance += 1

        if self.days_since_rebalance < self.rebalance_days:
            return signals

        self.days_since_rebalance = 0
        scores = {}

        for symbol, data in context["data"].items():
            if len(data) < self.momentum_window + 10:
                continue

            close = data["close"]
            volume = data["volume"]

            # 因子1：动量（20日收益率）
            momentum = close.iloc[-1] / close.iloc[-self.momentum_window] - 1

            # 因子2：波动率倒数（低波动优先）
            returns = close.pct_change().dropna()
            volatility = returns.iloc[-self.momentum_window:].std()
            vol_score = 1 / volatility if volatility > 0 else 0

            # 因子3：成交量趋势（近期放量）
            vol_ma5 = volume.iloc[-5:].mean() if "volume" in data.columns else 0
            vol_ma20 = volume.iloc[-20:].mean() if "volume" in data.columns else 0
            vol_trend = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 0

            # 综合评分
            score = momentum * 2 + vol_score * 100 + vol_trend
            scores[symbol] = score

        if not scores:
            return signals

        # 排名
        sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_stocks = [s[0] for s in sorted_stocks[:self.top_n]]

        # 卖出不在 Top N 的
        for symbol in context["positions"]:
            if symbol not in top_stocks and context["positions"].get(symbol, 0) > 0:
                signals.append(self.sell(symbol, context["positions"][symbol], "因子排名下降"))

        # 买入 Top N 中没有持仓的
        alloc_per_stock = context["total_value"] / self.top_n
        for symbol in top_stocks:
            if context["positions"].get(symbol, 0) == 0 and symbol in context["current_bar"]:
                price = context["current_bar"][symbol]["close"]
                volume = int(alloc_per_stock / price / 100) * 100
                if volume >= 100:
                    signals.append(self.buy(symbol, volume, f"因子排名第{top_stocks.index(symbol)+1}"))

        return signals
