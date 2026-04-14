"""回测引擎"""
import pandas as pd
from loguru import logger
from datetime import datetime
from risk.manager import RiskManager


class BacktestEngine:
    """轻量回测引擎，支持A股规则"""

    def __init__(self, strategy, initial_capital: float = 1_000_000):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk = RiskManager()
        self.risk.total_capital = initial_capital

        # 状态
        self.cash = initial_capital
        self.positions = {}   # {symbol: {"volume": int, "cost": float}}
        self.trades = []
        self.equity_curve = []

    def run(self, data: pd.DataFrame, symbol: str = "test"):
        """
        运行回测
        data: DataFrame with columns [open, high, low, close, volume]
        """
        logger.info(f"开始回测: {symbol}, 数据 {len(data)} 条")
        self.strategy.positions = {}
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = []

        for i in range(len(data)):
            bar = data.iloc[i]
            context_data = data.iloc[:i+1]  # 到当前时刻的历史

            context = {
                "data": context_data,
                "positions": {s: p["volume"] for s, p in self.positions.items()},
                "cash": self.cash,
                "total_value": self._get_total_value(bar),
            }

            signal = self.strategy.on_bar(symbol, bar, context)
            self._execute(signal, bar)

            # 记录净值
            total = self._get_total_value(bar)
            self.equity_curve.append({
                "date": bar.name if hasattr(bar.name, "strftime") else str(bar.name),
                "equity": total,
                "cash": self.cash,
                "position_value": total - self.cash,
            })

        return self._calc_stats()

    def _execute(self, signal, bar):
        """执行交易信号"""
        if signal["action"] == "hold":
            return

        symbol = signal["symbol"]
        price = bar["close"]
        volume = signal["volume"]

        if signal["action"] == "buy":
            fees = self.risk.calculate_fees(price, volume, is_sell=False)
            cost = price * volume + fees["total"]
            if cost <= self.cash:
                self.cash -= cost
                self.positions[symbol] = {
                    "volume": volume,
                    "cost": price,
                }
                self.trades.append({
                    "date": bar.name, "symbol": symbol, "action": "buy",
                    "price": price, "volume": volume, "fees": fees["total"],
                })
                logger.debug(f"买入 {symbol} {volume}股 @ {price:.2f}")

        elif signal["action"] == "sell":
            pos = self.positions.get(symbol, {})
            sell_vol = min(volume, pos.get("volume", 0))
            if sell_vol > 0:
                fees = self.risk.calculate_fees(price, sell_vol, is_sell=True)
                revenue = price * sell_vol - fees["total"]
                self.cash += revenue
                self.positions[symbol]["volume"] -= sell_vol
                if self.positions[symbol]["volume"] <= 0:
                    del self.positions[symbol]
                self.trades.append({
                    "date": bar.name, "symbol": symbol, "action": "sell",
                    "price": price, "volume": sell_vol, "fees": fees["total"],
                })
                logger.debug(f"卖出 {symbol} {sell_vol}股 @ {price:.2f}")

    def _get_total_value(self, bar):
        """计算总资产"""
        value = self.cash
        for sym, pos in self.positions.items():
            value += pos["volume"] * bar["close"]
        return value

    def _calc_stats(self) -> dict:
        """计算回测统计"""
        equity = pd.DataFrame(self.equity_curve)
        if equity.empty:
            return {}

        equity["date"] = pd.to_datetime(equity["date"])
        equity.set_index("date", inplace=True)
        equity["return"] = equity["equity"].pct_change()

        total_return = (equity["equity"].iloc[-1] / self.initial_capital) - 1
        trading_days = len(equity)
        ann_return = (1 + total_return) ** (252 / max(trading_days, 1)) - 1

        # 最大回撤
        peak = equity["equity"].cummax()
        drawdown = (equity["equity"] - peak) / peak
        max_dd = drawdown.min()

        # 夏普比率
        ann_sharp = 0.0
        if equity["return"].std() > 0:
            ann_sharp = equity["return"].mean() / equity["return"].std() * (252 ** 0.5)

        # 交易次数
        buy_trades = [t for t in self.trades if t["action"] == "buy"]
        total_fees = sum(t["fees"] for t in self.trades)

        stats = {
            "初始资金": f"{self.initial_capital:,.0f}",
            "最终净值": f"{equity['equity'].iloc[-1]:,.0f}",
            "总收益率": f"{total_return:.2%}",
            "年化收益": f"{ann_return:.2%}",
            "最大回撤": f"{max_dd:.2%}",
            "夏普比率": f"{ann_sharp:.2f}",
            "交易次数": len(self.trades),
            "买入次数": len(buy_trades),
            "总手续费": f"{total_fees:,.0f}",
        }
        return stats

    def get_equity_curve(self) -> pd.DataFrame:
        return pd.DataFrame(self.equity_curve)

    def get_trades(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades)
