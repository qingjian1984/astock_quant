"""实时交易管理器"""
import time
import pandas as pd
from datetime import datetime
from loguru import logger
from live.realtime import RealtimeFeed
from live.learner import StrategyLearner
from risk.manager import RiskManager
import config


class TradeSimulator:
    """
    模拟券商下单
    实盘时替换为 vnpy/券商API
    """

    def __init__(self):
        self.cash = config.TRADE_CONFIG.get("initial_capital", 1_000_000)
        self.positions = {}  # {symbol: {"volume": int, "cost": float, "buy_date": str}}
        self.orders = []  # 订单记录
        self.trade_log = []

    def submit_order(self, symbol: str, action: str, price: float, volume: int) -> dict:
        """提交订单"""
        if action == "buy":
            return self._buy(symbol, price, volume)
        elif action == "sell":
            return self._sell(symbol, price, volume)
        return {"status": "rejected", "reason": "未知操作"}

    def _buy(self, symbol: str, price: float, volume: int) -> dict:
        """模拟买入"""
        cost = price * volume
        fee = cost * config.TRADE_CONFIG["commission_rate"]
        fee = max(fee, config.TRADE_CONFIG["commission_min"])
        total_cost = cost + fee

        if total_cost > self.cash:
            return {"status": "rejected", "reason": "资金不足"}
        if volume % 100 != 0:
            return {"status": "rejected", "reason": "必须是100股整数倍"}

        self.cash -= total_cost
        if symbol in self.positions:
            pos = self.positions[symbol]
            total_vol = pos["volume"] + volume
            pos["cost"] = (pos["cost"] * pos["volume"] + price * volume) / total_vol
            pos["volume"] = total_vol
        else:
            self.positions[symbol] = {
                "volume": volume,
                "cost": price,
                "buy_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        order = {
            "symbol": symbol, "action": "buy", "price": price, "volume": volume,
            "fee": fee, "time": datetime.now().isoformat(), "status": "filled",
        }
        self.orders.append(order)
        return order

    def _sell(self, symbol: str, price: float, volume: int) -> dict:
        """模拟卖出"""
        if symbol not in self.positions:
            return {"status": "rejected", "reason": "无持仓"}

        pos = self.positions[symbol]
        sell_vol = min(volume, pos["volume"])

        revenue = price * sell_vol
        commission = revenue * config.TRADE_CONFIG["commission_rate"]
        commission = max(commission, config.TRADE_CONFIG["commission_min"])
        stamp_tax = revenue * config.TRADE_CONFIG["stamp_tax"]
        transfer = revenue * config.TRADE_CONFIG["transfer_fee"]
        total_fee = commission + stamp_tax + transfer

        self.cash += revenue - total_fee
        pos["volume"] -= sell_vol
        if pos["volume"] <= 0:
            del self.positions[symbol]

        order = {
            "symbol": symbol, "action": "sell", "price": price, "volume": sell_vol,
            "fee": total_fee, "time": datetime.now().isoformat(), "status": "filled",
        }
        self.orders.append(order)
        return order

    def get_portfolio_value(self, prices: dict) -> float:
        """获取总资产"""
        value = self.cash
        for symbol, pos in self.positions.items():
            value += pos["volume"] * prices.get(symbol, pos["cost"])
        return value

    def get_state(self) -> dict:
        """获取当前状态"""
        return {
            "cash": self.cash,
            "positions": self.positions.copy(),
            "total_orders": len(self.orders),
        }


class AutoTrader:
    """
    自动交易引擎
    整合实时行情、策略信号、风控、学习和模拟下单
    """

    def __init__(self, strategy, symbols: list, strategy_name: str = "auto",
                 param_space: dict = None):
        self.strategy = strategy
        self.symbols = symbols
        self.strategy_name = strategy_name

        # 组件
        self.feed = RealtimeFeed(symbols, interval=60)
        self.trader = TradeSimulator()
        self.risk = RiskManager()
        self.learner = StrategyLearner(strategy_name, param_space or {})

        # 状态
        self.running = False
        self.cycle_count = 0
        self.last_rebalance = None

        # 配置
        self.rebalance_minutes = 120  # 每2小时重新学习
        self.check_interval = 60  # 每秒检查一次

    def start(self):
        """启动自动交易"""
        logger.info("=" * 50)
        logger.info("自动交易引擎启动")
        logger.info(f"标的: {self.symbols}")
        logger.info(f"策略: {self.strategy_name}")
        logger.info("=" * 50)

        self.running = True
        while self.running:
            try:
                self._cycle()
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                logger.info("收到停止信号")
                self.stop()
                break
            except Exception as e:
                logger.error(f"交易循环异常: {e}")
                time.sleep(30)

    def stop(self):
        """停止自动交易"""
        self.running = False
        self.feed.stop()
        logger.info("自动交易引擎已停止")
        logger.info(f"最终状态: {self.trader.get_state()}")

    def _cycle(self):
        """一个交易周期"""
        now = datetime.now()
        self.cycle_count += 1

        # 1. 检查交易时间
        if not RealtimeFeed._is_trading_time(now):
            if self.cycle_count % 60 == 0:  # 每小时打印一次
                logger.info(f"非交易时间，等待中... ({now.strftime('%H:%M:%S')})")
            return

        # 2. 获取实时行情
        self.feed._refresh()
        latest = self.feed.get_all_latest()

        if not latest:
            logger.debug("无实时数据，跳过")
            return

        # 3. 构建上下文
        context = self._build_context()

        # 4. 生成信号
        signals = self.strategy.on_bar(context)

        # 5. 执行交易
        for signal in signals:
            self._execute_signal(signal, latest)

        # 6. 风控检查
        self._risk_check()

        # 7. 定期学习
        if self._should_rebalance(now):
            self._rebalance()

        # 8. 打印状态
        if self.cycle_count % 10 == 0:
            self._print_status()

    def _build_context(self) -> dict:
        """构建策略上下文"""
        context = {
            "data": {},
            "current_bar": {},
            "positions": {s: p["volume"] for s, p in self.trader.positions.items()},
            "cash": self.trader.cash,
            "date": datetime.now(),
        }

        prices = {}
        for symbol in self.symbols:
            history = self.feed.get_history(symbol)
            if not history.empty:
                context["data"][symbol] = history
                context["current_bar"][symbol] = history.iloc[-1]
                prices[symbol] = history.iloc[-1]["close"]

        context["total_value"] = self.trader.get_portfolio_value(prices)
        return context

    def _execute_signal(self, signal, latest: dict):
        """执行交易信号"""
        symbol = signal.get("symbol")
        action = signal.get("action")
        price = latest.get(symbol, {}).get("price", 0)

        if price <= 0:
            return

        # 学习建议
        suggestion = self.learner.suggest_action(symbol, latest, {"history": self.feed.get_history(symbol)})

        # 结合策略信号和学习建议
        if suggestion["action"] != action and suggestion["confidence"] > 0.7:
            logger.info(f"学习建议覆盖: {symbol} 策略={action} 学习={suggestion['action']} ({suggestion['reason']})")
            action = suggestion["action"]

        if action == "buy":
            volume = signal.get("volume", 0)
            result = self.trader.submit_order(symbol, "buy", price, volume)
            if result["status"] == "filled":
                logger.info(f"买入 {symbol} {volume}股 @ {price:.2f}")
                self.learner.record_trade(symbol, "buy", price, volume,
                                          datetime.now().isoformat(), signal.get("params", {}),
                                          signal.get("reason", ""))
            else:
                logger.warning(f"买入被拒绝: {result['reason']}")

        elif action == "sell":
            volume = signal.get("volume", 0)
            result = self.trader.submit_order(symbol, "sell", price, volume)
            if result["status"] == "filled":
                logger.info(f"卖出 {symbol} {volume}股 @ {price:.2f}")
                # 记录交易结果
                buy_trades = [t for t in self.learner.trade_history
                              if t["symbol"] == symbol and t["action"] == "buy" and "result" not in t]
                if buy_trades:
                    self.learner.record_trade_result(
                        self.learner.trade_history.index(buy_trades[-1]),
                        price, datetime.now().isoformat(), result["fee"]
                    )
            else:
                logger.warning(f"卖出被拒绝: {result['reason']}")

    def _risk_check(self):
        """风控检查"""
        prices = {s: self.feed.get_latest(s).get("price", 0) for s in self.symbols}
        total_value = self.trader.get_portfolio_value(prices)

        # 回撤检查
        dd = self.risk.check_drawdown(total_value, self.risk.peak_value)
        if dd < config.RISK_CONFIG["max_drawdown_pct"]:
            logger.critical(f"触发最大回撤 {dd:.2%}，暂停交易")
            self.running = False

        # 持仓检查
        for symbol, pos in self.trader.positions.items():
            price = prices.get(symbol, pos["cost"])
            pos_value = pos["volume"] * price
            pct = self.risk.check_position(pos_value, total_value)

            # 止损检查
            pnl_pct = (price - pos["cost"]) / pos["cost"]
            if pnl_pct <= config.RISK_CONFIG["stop_loss_pct"]:
                logger.warning(f"止损触发: {symbol} 亏损 {pnl_pct:.2%}")
                # 自动卖出
                self.trader.submit_order(symbol, "sell", price, pos["volume"])

    def _should_rebalance(self, now: datetime) -> bool:
        """是否需要重新学习"""
        if self.last_rebalance is None:
            return True
        minutes = (now - self.last_rebalance).total_seconds() / 60
        return minutes >= self.rebalance_minutes

    def _rebalance(self):
        """重新学习优化"""
        logger.info("开始自主学习优化...")
        self.last_rebalance = datetime.now()

        # 收集近期交易
        recent = self.learner.trade_history[-20:]
        self.learner.adaptive_update(recent)

        # 如果有足够数据，可以尝试参数优化
        if len(self.learner.trade_history) >= 10:
            stats = self.learner.get_learning_stats()
            logger.info(f"学习统计: {stats}")

    def _print_status(self):
        """打印当前状态"""
        prices = {s: self.feed.get_latest(s).get("price", 0) for s in self.symbols}
        total = self.trader.get_portfolio_value(prices)
        learning = self.learner.get_learning_stats()

        logger.info("\n" + "-" * 40)
        logger.info(f"总资产: {total:,.0f}")
        logger.info(f"现金: {self.trader.cash:,.0f}")
        logger.info(f"持仓: {len(self.trader.positions)} 只")
        for sym, pos in self.trader.positions.items():
            price = prices.get(sym, pos["cost"])
            pnl = (price - pos["cost"]) / pos["cost"]
            logger.info(f"  {sym}: {pos['volume']}股 @ {pos['cost']:.2f} 现价{price:.2f} ({pnl:+.2%})")
        logger.info(f"学习记录: {learning.get('total_trades', 0)} 笔交易, "
                     f"胜率 {learning.get('win_rate', 0):.0%}")
        logger.info("-" * 40)
