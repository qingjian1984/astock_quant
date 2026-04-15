"""自动交易引擎（完整版）"""
import time
import pandas as pd
from datetime import datetime
from loguru import logger
from live.realtime import RealtimeFeed
from live.learner import StrategyLearner
from live.limiter import TradeLimiter
from live.broker import BrokerInterface
from risk.manager import RiskManager
import config


class AutoTrader:
    """
    自动交易引擎（完整版）
    支持模拟盘/实盘 + 交易限制 + 自主学习
    """

    def __init__(self, strategy, symbols: list, strategy_name: str = "auto",
                 param_space: dict = None, trading_mode: str = "paper",
                 custom_limits: dict = None):
        self.strategy = strategy
        self.symbols = symbols
        self.strategy_name = strategy_name
        self.trading_mode = trading_mode  # "paper" or "live"

        # 组件
        self.feed = RealtimeFeed(symbols, interval=60)
        self.risk = RiskManager()
        self.learner = StrategyLearner(strategy_name, param_space or {})
        self.limiter = TradeLimiter(custom_limits)

        # 交易执行器
        if trading_mode == "live":
            self.executor = BrokerInterface()
            logger.warning("实盘模式：需要配置券商API")
        else:
            from live.trader import TradeSimulator
            self.executor = TradeSimulator()
            logger.info("模拟盘模式：使用 TradeSimulator")

        # 状态
        self.running = False
        self.cycle_count = 0
        self.last_rebalance = None
        self.rebalance_minutes = 120
        self.check_interval = 60

    @staticmethod
    def _get_dm():
        """获取数据源管理器"""
        from data.manager import DataSourceManager
        from data.sources.akshare_src import AKShareSource
        from data.sources.baostock_src import BaoStockSource
        dm = DataSourceManager()
        dm.register(AKShareSource(retry=3))
        dm.register(BaoStockSource())
        dm.connect_all()
        return dm

    def start(self):
        """启动自动交易"""
        logger.info("=" * 50)
        logger.info("自动交易引擎启动")
        logger.info(f"模式: {'实盘' if self.trading_mode == 'live' else '模拟盘'}")
        logger.info(f"标的: {self.symbols}")
        logger.info(f"策略: {self.strategy_name}")
        logger.info(f"限制: {self.limiter.get_status()}")
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

    def _cycle(self):
        """一个交易周期"""
        now = datetime.now()
        self.cycle_count += 1

        # 检查交易时间
        if not RealtimeFeed._is_trading_time(now):
            if self.cycle_count % 60 == 0:
                logger.info(f"非交易时间，等待中... ({now.strftime('%H:%M:%S')})")
            return

        # 获取行情
        self.feed._refresh()
        latest = self.feed.get_all_latest()
        if not latest:
            return

        # 构建上下文
        context = self._build_context()

        # 生成信号
        signals = self.strategy.on_bar(context)

        # 执行信号（带限制检查）
        for signal in signals:
            self._execute_with_limits(signal, latest)

        # 风控
        self._risk_check()

        # 定期学习
        if self._should_rebalance(now):
            self._rebalance()

        # 打印状态
        if self.cycle_count % 10 == 0:
            self._print_status()

    def _build_context(self) -> dict:
        """构建策略上下文"""
        context = {
            "data": {},
            "current_bar": {},
            "positions": {},
            "cash": 0,
            "date": datetime.now(),
        }

        prices = {}
        for symbol in self.symbols:
            history = self.feed.get_history(symbol)
            if not history.empty:
                context["data"][symbol] = history
                context["current_bar"][symbol] = history.iloc[-1]
                prices[symbol] = history.iloc[-1]["close"]

        # 获取持仓
        if hasattr(self.executor, "positions"):
            context["positions"] = {s: p["volume"] for s, p in self.executor.positions.items()}
            context["cash"] = getattr(self.executor, "cash", 0)
        elif hasattr(self.executor, "query_position"):
            for symbol in self.symbols:
                vol = self.executor.query_position(symbol)
                if vol > 0:
                    context["positions"][symbol] = vol
            context["cash"] = self.executor.query_cash()

        total = context["cash"]
        for sym, vol in context["positions"].items():
            total += vol * prices.get(sym, 0)
        context["total_value"] = total
        return context

    def _execute_with_limits(self, signal, latest: dict):
        """带限制检查的执行"""
        symbol = signal.get("symbol")
        action = signal.get("action")
        price = latest.get(symbol, {}).get("price", 0)
        volume = signal.get("volume", 0)

        if price <= 0 or volume <= 0:
            return

        # 1. 限制检查
        allowed, reason = self.limiter.check_trade(symbol, action, price, volume)
        if not allowed:
            logger.debug(f"交易被限制: {symbol} {action} {volume}股 @ {price:.2f} - {reason}")
            return

        # 2. 学习建议覆盖
        suggestion = self.learner.suggest_action(symbol, latest, {"history": self.feed.get_history(symbol)})
        if suggestion["action"] != action and suggestion["confidence"] > 0.7:
            logger.info(f"学习建议覆盖: {symbol} 策略={action} 学习={suggestion['action']} ({suggestion['reason']})")
            action = suggestion["action"]

        # 3. 下单
        if action == "buy":
            result = self.executor.submit_order(symbol, "buy", price, volume)
        elif action == "sell":
            result = self.executor.submit_order(symbol, "sell", price, volume)
        else:
            return

        if result.get("status") == "filled":
            logger.info(f"{'买入' if action == 'buy' else '卖出'} {symbol} {volume}股 @ {price:.2f}")
            self.limiter.record_trade(action, price * volume)
            self.learner.record_trade(symbol, action, price, volume,
                                      datetime.now().isoformat(), signal.get("params", {}),
                                      signal.get("reason", ""))

            # 记录卖出结果
            if action == "sell":
                buy_trades = [t for t in self.learner.trade_history
                              if t["symbol"] == symbol and t["action"] == "buy" and "result" not in t]
                if buy_trades:
                    self.learner.record_trade_result(
                        self.learner.trade_history.index(buy_trades[-1]),
                        price, datetime.now().isoformat(), result.get("fee", 0)
                    )
        else:
            logger.warning(f"下单被拒: {result.get('reason', 'unknown')}")

    def _risk_check(self):
        """风控检查"""
        prices = {s: self.feed.get_latest(s).get("price", 0) for s in self.symbols}
        total_value = self._calc_total_value(prices)

        # 回撤检查
        dd = self.risk.check_drawdown(total_value, self.risk.peak_value)
        if dd < config.RISK_CONFIG["max_drawdown_pct"]:
            logger.critical(f"触发最大回撤 {dd:.2%}，暂停交易")
            self.running = False

        # 持仓止损
        positions = self.executor.positions if hasattr(self.executor, "positions") else {}
        for symbol, pos in positions.items():
            price = prices.get(symbol, pos.get("cost", 0))
            if pos.get("cost", 0) > 0:
                pnl_pct = (price - pos["cost"]) / pos["cost"]
                if pnl_pct <= config.RISK_CONFIG["stop_loss_pct"]:
                    logger.warning(f"止损触发: {symbol} 亏损 {pnl_pct:.2%}")
                    self.executor.submit_order(symbol, "sell", price, pos["volume"])

    def _calc_total_value(self, prices: dict) -> float:
        """计算总资产"""
        if hasattr(self.executor, "get_portfolio_value"):
            return self.executor.get_portfolio_value(prices)
        elif hasattr(self.executor, "cash"):
            value = self.executor.cash
            for sym, pos in getattr(self.executor, "positions", {}).items():
                value += pos["volume"] * prices.get(sym, pos["cost"])
            return value
        return 0

    def _should_rebalance(self, now: datetime) -> bool:
        """是否需要重新学习"""
        if self.last_rebalance is None:
            return True
        return (now - self.last_rebalance).total_seconds() / 60 >= self.rebalance_minutes

    def _rebalance(self):
        """重新学习优化"""
        logger.info("开始自主学习优化...")
        self.last_rebalance = datetime.now()
        recent = self.learner.trade_history[-20:]
        self.learner.adaptive_update(recent)
        if len(self.learner.trade_history) >= 10:
            logger.info(f"学习统计: {self.learner.get_learning_stats()}")

    def _print_status(self):
        """打印当前状态"""
        prices = {s: self.feed.get_latest(s).get("price", 0) for s in self.symbols}
        total = self._calc_total_value(prices)
        learning = self.learner.get_learning_stats()
        limits = self.limiter.get_status()

        logger.info("\n" + "-" * 40)
        logger.info(f"模式: {'实盘' if self.trading_mode == 'live' else '模拟盘'}")
        logger.info(f"总资产: {total:,.0f}")
        logger.info(f"持仓: {len(self.executor.positions if hasattr(self.executor, 'positions') else {})} 只")
        for sym, pos in (self.executor.positions if hasattr(self.executor, 'positions') else {}).items():
            price = prices.get(sym, pos["cost"])
            pnl = (price - pos["cost"]) / pos["cost"] if pos["cost"] > 0 else 0
            logger.info(f"  {sym}: {pos['volume']}股 @ {pos['cost']:.2f} 现价{price:.2f} ({pnl:+.2%})")
        logger.info(f"学习: {learning.get('total_trades', 0)}笔, 胜率 {learning.get('win_rate', 0):.0%}")
        for k, v in limits.items():
            logger.info(f"  {k}: {v}")
        logger.info("-" * 40)
