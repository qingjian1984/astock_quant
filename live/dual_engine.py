"""双轨交易引擎"""
import time
import pandas as pd
from datetime import datetime
from loguru import logger
from live.realtime import RealtimeFeed
from live.learner import StrategyLearner
from live.limiter import TradeLimiter
from live.scanner import StockScanner
from live.auto_trader import AutoTrader
from core.optimizer import StrategyOptimizer
from core.portfolio import LONG_TERM_STOCKS, SWING_CONFIG
from risk.manager import RiskManager
import config


class DualTrackEngine:
    """
    双轨交易引擎
    1. 长线股：优化策略 + 长期持有 + 网格做T
    2. 波段股：扫描选股 + 策略交易
    """

    def __init__(self, trading_mode: str = "paper"):
        self.mode = trading_mode
        self.dm = AutoTrader._get_dm()  # 复用 AutoTrader 的数据源管理
        self.risk = RiskManager()
        self.limiter = TradeLimiter()
        self.optimizer = StrategyOptimizer()

        # 长线股状态
        self.long_term_positions = {}  # {symbol: {"strat": obj, "grid_strat": obj, "best_score": float}}
        self.long_term_data = {}       # {symbol: DataFrame}

        # 波段股状态
        self.swing_positions = {}      # {symbol: {"strat": obj, "entry_date": str}}
        self.scanner = StockScanner(self.dm)
        self.last_scan_time = 0

        # 交易执行器
        if trading_mode == "live":
            from live.broker import BrokerInterface
            self.executor = BrokerInterface()
        else:
            from live.trader import TradeSimulator
            self.executor = TradeSimulator()

    def start(self):
        """启动双轨引擎"""
        logger.info("=" * 50)
        logger.info("双轨交易引擎启动")
        logger.info(f"模式: {self.mode}")
        logger.info(f"长线股: {[s['symbol'] for s in LONG_TERM_STOCKS]}")
        logger.info("=" * 50)

        # 1. 初始化长线股
        self._init_long_term()

        # 2. 主循环
        while True:
            try:
                self._cycle()
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("引擎停止")
                break
            except Exception as e:
                logger.error(f"引擎异常: {e}")
                time.sleep(60)

    def _init_long_term(self):
        """初始化长线股：回测找策略"""
        logger.info("初始化长线股策略...")
        for stock in LONG_TERM_STOCKS:
            symbol = stock["symbol"]
            df = self.dm.fetch_daily(symbol, "20200101", datetime.now().strftime("%Y%m%d"))
            if df.empty:
                continue
            self.long_term_data[symbol] = df

            # 寻找最优策略
            result = self.optimizer.optimize(symbol, df)
            logger.info(f"  {symbol} 最优策略: {result['strategy']} {result['params']}")

            # 创建策略实例
            from core.optimizer import STRATEGY_LIBRARY
            s_info = STRATEGY_LIBRARY[result["strategy"]]
            strat = s_info["class"](**result["params"])

            # 创建网格做T策略
            from strategies.cost_reducer import GridStrategy
            grid_strat = GridStrategy(symbol)

            self.long_term_positions[symbol] = {
                "strat": strat,
                "grid_strat": grid_strat,
                "result": result,
                "capital": stock.get("min_capital", 100000),
            }

    def _cycle(self):
        """主循环"""
        now = datetime.now()
        if not RealtimeFeed._is_trading_time(now):
            return

        # 1. 处理长线股
        self._process_long_term()

        # 2. 处理波段股
        self._process_swing()

    def _process_long_term(self):
        """长线股处理：趋势跟踪 + 网格做T"""
        for symbol, info in self.long_term_positions.items():
            # 获取最新数据
            df = self.dm.fetch_daily(symbol, "20240101", datetime.now().strftime("%Y%m%d"))
            if df.empty:
                continue

            context = self._build_context(symbol, df)

            # 1. 主趋势策略信号
            signals = info["strat"].on_bar(context)
            for sig in signals:
                self._execute_signal(sig, df)

            # 2. 网格做T策略信号（只要有持仓就运行）
            pos = self.executor.positions.get(symbol, {}).get("volume", 0)
            if pos > 0:
                grid_signals = info["grid_strat"].on_bar(context)
                for sig in grid_signals:
                    self._execute_signal(sig, df)

    def _process_swing(self):
        """波段股处理：扫描 + 交易"""
        now = time.time()
        if now - self.last_scan_time < SWING_CONFIG["scan_interval"]:
            return

        self.last_scan_time = now
        logger.info("开始波段股扫描...")

        for strat_name in SWING_CONFIG["strategies"]:
            candidates = self.scanner.scan(strat_name)
            for c in candidates[:SWING_CONFIG["max_positions"]]:
                if c["symbol"] not in self.swing_positions:
                    logger.info(f"发现波段机会: {c['symbol']} ({c['reason']})")
                    # 执行买入
                    # TODO: 调用 executor 下单
                    self.swing_positions[c["symbol"]] = {
                        "strat": strat_name,
                        "entry_date": datetime.now().isoformat(),
                        "stats": c["stats"],
                    }

        # 检查波段股卖出信号
        self._check_swing_exits()

    def _check_swing_exits(self):
        """检查波段股卖出条件"""
        for symbol, info in self.swing_positions.items():
            # 获取持仓
            pos = self.executor.positions.get(symbol, {}).get("volume", 0)
            if pos == 0:
                continue

            # 检查止损止盈
            # TODO: 实现具体逻辑

    def _build_context(self, symbol: str, df: pd.DataFrame) -> dict:
        """构建上下文"""
        return {
            "data": {symbol: df},
            "current_bar": {symbol: df.iloc[-1]},
            "positions": {s: p["volume"] for s, p in self.executor.positions.items()},
            "cash": self.executor.cash,
            "total_value": self.executor.get_portfolio_value(
                {s: self.dm.fetch_daily(s, "20241231", "20241231").iloc[-1]["close"]
                 for s in self.executor.positions}
            ),
            "date": datetime.now(),
        }

    def _execute_signal(self, signal, df: pd.DataFrame):
        """执行信号"""
        symbol = signal["symbol"]
        action = signal["action"]
        volume = signal["volume"]
        price = df.iloc[-1]["close"]

        if action == "buy":
            # 限制检查
            allowed, reason = self.limiter.check_trade(symbol, "buy", price, volume)
            if not allowed:
                logger.debug(f"长线买入被限: {reason}")
                return
            res = self.executor.submit_order(symbol, "buy", price, volume)
            if res["status"] == "filled":
                logger.info(f"长线买入: {symbol} {volume}股 @ {price:.2f}")
                self.limiter.record_trade("buy", price * volume)
        elif action == "sell":
            allowed, reason = self.limiter.check_trade(symbol, "sell", price, volume)
            if not allowed:
                logger.debug(f"长线卖出被限: {reason}")
                return
            res = self.executor.submit_order(symbol, "sell", price, volume)
            if res["status"] == "filled":
                logger.info(f"长线卖出: {symbol} {volume}股 @ {price:.2f}")
                self.limiter.record_trade("sell", price * volume)

    @staticmethod
    def _get_dm():
        from data.manager import DataSourceManager
        from data.sources.akshare_src import AKShareSource
        from data.sources.baostock_src import BaoStockSource
        dm = DataSourceManager()
        dm.register(AKShareSource(retry=3))
        dm.register(BaoStockSource())
        dm.connect_all()
        return dm
