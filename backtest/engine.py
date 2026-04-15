"""回测引擎 - A股完整版（修复T+1、涨跌停、滑点、风控接入、多标的支持）"""
import pandas as pd
from loguru import logger
from datetime import datetime
from risk.manager import RiskManager
import config


class BacktestEngine:
    """
    回测引擎 - A股完整版
    修复项：
    1. T+1 限制（买入次日才可卖出）
    2. 涨跌停判断（±10% 主板）
    3. 滑点模拟
    4. 风控模块接入
    5. 多标的组合回测
    """

    def __init__(self, strategy, initial_capital: float = 1_000_000, slippage: float = None):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk = RiskManager()
        self.risk.total_capital = initial_capital
        self.slippage = slippage or config.TRADE_CONFIG.get("slippage", 0.001)  # 默认千1滑点

        # 状态
        self.cash = initial_capital
        self.positions = {}   # {symbol: {"volume": int, "cost": float, "buy_date": str}}
        self.buy_dates = {}   # {symbol: set(dates)} 记录每天买入的持仓（T+1用）
        self.trades = []
        self.equity_curve = []

    def run(self, data: dict | pd.DataFrame, symbols: list = None):
        """
        运行回测
        data: 单标的 DataFrame 或 {symbol: DataFrame}
        symbols: 多标的列表（当 data 是 dict 时使用）
        """
        # 统一为多标的格式
        if isinstance(data, pd.DataFrame):
            # 单标的模式
            if symbols is None:
                symbols = ["stock"]
            data_dict = {symbols[0]: data}
        else:
            data_dict = data
            if symbols is None:
                symbols = list(data_dict.keys())

        logger.info(f"开始回测: {symbols}, 数据量: {', '.join(f'{s}: {len(d)}' for s, d in data_dict.items())}")

        self.cash = self.initial_capital
        self.positions = {}
        self.buy_dates = {}
        self.trades = []
        self.equity_curve = []

        # 合并所有日期的并集
        all_dates = set()
        for df in data_dict.values():
            all_dates.update(df.index.tolist())
        all_dates = sorted(all_dates)

        for current_date in all_dates:
            context = {
                "data": {},         # {symbol: 到当前的历史}
                "current_bar": {},  # {symbol: 当前K线}
                "positions": {s: p["volume"] for s, p in self.positions.items()},
                "cash": self.cash,
                "total_value": 0,   # 后面算
                "date": current_date,
            }

            # 构建上下文
            for sym, df in data_dict.items():
                if current_date in df.index:
                    bar = df.loc[current_date]
                    context["current_bar"][sym] = bar
                    context["data"][sym] = df.loc[:current_date]

            # 计算当前总资产
            context["total_value"] = self._get_total_value(context["current_bar"])
            self.risk.peak_value = max(self.risk.peak_value, context["total_value"])

            # 策略产生信号
            signals = self.strategy.on_bar(context)
            if not isinstance(signals, list):
                signals = [signals] if signals else []

            # 按顺序执行：先卖后买（释放资金）
            sells = [s for s in signals if s.get("action") == "sell"]
            buys = [s for s in signals if s.get("action") == "buy"]

            for signal in sells:
                self._execute_sell(signal, data_dict, current_date)

            for signal in buys:
                self._execute_buy(signal, data_dict, current_date)

            # 记录净值
            total = self._get_total_value(context["current_bar"])
            self.equity_curve.append({
                "date": current_date,
                "equity": total,
                "cash": self.cash,
                "position_value": total - self.cash,
            })

        return self._calc_stats()

    def _is_limit_up(self, bar: pd.Series) -> bool:
        """判断是否涨停（主板±10%）"""
        if "pct_change" in bar and pd.notna(bar["pct_change"]):
            return bar["pct_change"] >= 9.9
        return False

    def _is_limit_down(self, bar: pd.Series) -> bool:
        """判断是否跌停"""
        if "pct_change" in bar and pd.notna(bar["pct_change"]):
            return bar["pct_change"] <= -9.9
        return False

    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        """应用滑点：买入价上偏，卖出价下偏"""
        slippage = price * self.slippage
        if is_buy:
            return price + slippage
        else:
            return price - slippage

    def _can_sell(self, symbol: str, date) -> bool:
        """T+1 检查：买入当天不能卖"""
        if symbol not in self.positions:
            return False
        buy_date = self.positions[symbol].get("buy_date", date)
        # 买入日期不等于当前日期才能卖
        return str(buy_date)[:10] != str(date)[:10]

    def _execute_buy(self, signal, data_dict, date):
        """执行买入"""
        symbol = signal.get("symbol", "stock")
        bar = data_dict.get(symbol)
        if bar is None or date not in bar.index:
            return

        price = bar.loc[date]["close"]

        # 涨停不能买入
        if self._is_limit_up(bar.loc[date]):
            logger.debug(f"涨停不能买入 {symbol} @ {date}")
            return

        # 滑点
        exec_price = self._apply_slippage(price, is_buy=True)

        volume = signal.get("volume", 0)

        # 风控检查
        pos_vol = self.positions.get(symbol, {}).get("volume", 0)
        total_value = self._get_total_value({})
        allowed, adj_vol, reason = self.risk.check_buy(
            symbol, volume, exec_price, pos_vol, self.cash, total_value
        )
        if not allowed:
            logger.debug(f"风控拦截买入 {symbol}: {reason}")
            return

        volume = adj_vol
        fees = self.risk.calculate_fees(exec_price, volume, is_sell=False)
        cost = exec_price * volume + fees["total"]

        if cost <= self.cash and volume >= 100:
            self.cash -= cost

            # T+1 记录
            if symbol not in self.positions:
                self.positions[symbol] = {
                    "volume": volume,
                    "cost": exec_price,
                    "buy_date": date,
                }
            else:
                # 加仓：更新均价
                old = self.positions[symbol]
                total_cost = old["cost"] * old["volume"] + exec_price * volume
                old["volume"] += volume
                old["cost"] = total_cost / old["volume"]
                old["buy_date"] = date  # 新买的要T+1

            self.trades.append({
                "date": date, "symbol": symbol, "action": "buy",
                "price": round(exec_price, 2), "volume": volume,
                "fees": fees["total"], "reason": signal.get("reason", ""),
            })
            logger.debug(f"买入 {symbol} {volume}股 @ {exec_price:.2f} (滑点{self.slippage:.3%})")

    def _execute_sell(self, signal, data_dict, date):
        """执行卖出"""
        symbol = signal.get("symbol", "stock")

        # T+1 检查
        if not self._can_sell(symbol, date):
            logger.debug(f"T+1 限制不能卖 {symbol} @ {date}")
            return

        bar = data_dict.get(symbol)
        if bar is None or date not in bar.index:
            return

        price = bar.loc[date]["close"]

        # 跌停不能卖出
        if self._is_limit_down(bar.loc[date]):
            logger.debug(f"跌停不能卖出 {symbol} @ {date}")
            return

        # 滑点
        exec_price = self._apply_slippage(price, is_buy=False)

        pos = self.positions.get(symbol)
        if not pos or pos["volume"] <= 0:
            return

        volume = min(signal.get("volume", pos["volume"]), pos["volume"])

        fees = self.risk.calculate_fees(exec_price, volume, is_sell=True)
        revenue = exec_price * volume - fees["total"]
        self.cash += revenue

        pos["volume"] -= volume
        if pos["volume"] <= 0:
            del self.positions[symbol]

        self.trades.append({
            "date": date, "symbol": symbol, "action": "sell",
            "price": round(exec_price, 2), "volume": volume,
            "fees": fees["total"], "reason": signal.get("reason", ""),
        })
        logger.debug(f"卖出 {symbol} {volume}股 @ {exec_price:.2f} (滑点{self.slippage:.3%})")

    def _get_total_value(self, current_bars: dict) -> float:
        """计算总资产"""
        value = self.cash
        for sym, pos in self.positions.items():
            if sym in current_bars:
                price = current_bars[sym]["close"]
            else:
                price = pos["cost"]  # 无行情时用成本价
            value += pos["volume"] * price
        return value

    def _calc_stats(self) -> dict:
        """计算回测统计"""
        equity = pd.DataFrame(self.equity_curve)
        if equity.empty:
            return {}

        equity["date"] = pd.to_datetime(equity["date"])
        equity.set_index("date", inplace=True)
        equity["return"] = equity["equity"].pct_change().fillna(0)

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

        # 交易统计
        buy_trades = [t for t in self.trades if t["action"] == "buy"]
        sell_trades = [t for t in self.trades if t["action"] == "sell"]
        total_fees = sum(t["fees"] for t in self.trades)

        # 胜率
        wins = 0
        if len(buy_trades) == len(sell_trades):
            for b, s in zip(buy_trades, sell_trades):
                if s["price"] > b["price"]:
                    wins += 1
        win_rate = wins / max(len(buy_trades), 1)

        stats = {
            "初始资金": f"{self.initial_capital:,.0f}",
            "最终净值": f"{equity['equity'].iloc[-1]:,.0f}",
            "总收益率": f"{total_return:.2%}",
            "年化收益": f"{ann_return:.2%}",
            "最大回撤": f"{max_dd:.2%}",
            "夏普比率": f"{ann_sharp:.2f}",
            "胜率": f"{win_rate:.1%}",
            "交易次数": len(self.trades),
            "买入次数": len(buy_trades),
            "卖出次数": len(sell_trades),
            "总手续费": f"{total_fees:,.0f}",
            "滑点设置": f"{self.slippage:.3%}",
        }
        return stats

    def get_equity_curve(self) -> pd.DataFrame:
        return pd.DataFrame(self.equity_curve)

    def get_trades(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades)
