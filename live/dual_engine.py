"""双轨交易引擎 - 完整版"""
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
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
    双轨交易引擎 - 完整版
    1. 长线股：优化策略 + 长期持有 + 网格做T
    2. 波段股：扫描选股 + 策略交易 + 止损止盈
    """

    def __init__(self, trading_mode: str = "paper", initial_capital: float = 1_000_000):
        self.mode = trading_mode
        self.initial_capital = initial_capital
        self.dm = AutoTrader._get_dm()
        self.risk = RiskManager()
        self.risk.total_capital = initial_capital
        self.risk.peak_value = initial_capital
        self.limiter = TradeLimiter()
        self.optimizer = StrategyOptimizer()

        # 交易执行器
        if trading_mode == "live":
            from live.broker import VnpyBroker
            self.executor = VnpyBroker()
            self.executor.connect()
            if not self.executor.connected:
                logger.error("实盘模式券商连接失败，回退到模拟盘")
                from live.trader import TradeSimulator
                self.executor = TradeSimulator(initial_capital=initial_capital)
                self.mode = "paper"
        else:
            from live.trader import TradeSimulator
            self.executor = TradeSimulator(initial_capital=initial_capital)

        # 长线股状态
        self.long_term_positions: Dict = {}
        self.long_term_data: Dict[str, pd.DataFrame] = {}
        self.long_term_learners: Dict[str, StrategyLearner] = {}

        # 波段股状态
        self.swing_positions: Dict = {}
        self.swing_entry_prices: Dict[str, float] = {}
        self.scanner = StockScanner(self.dm)
        self.last_scan_time = 0
        self.swing_stop_loss_pct = config.RISK_CONFIG.get("stop_loss_pct", -0.08)
        self.swing_take_profit_pct = config.RISK_CONFIG.get("take_profit_pct", 0.20)

        # 运行状态
        self.running = False
        self.cycle_count = 0
        self.last_rebalance = None
        self.rebalance_minutes = 120
        self.daily_stats = {
            "trades": 0,
            "amount": 0,
            "last_date": datetime.now().strftime("%Y-%m-%d"),
        }

    def start(self):
        """启动双轨引擎"""
        logger.info("=" * 60)
        logger.info("双轨交易引擎启动")
        logger.info(f"模式: {'实盘' if self.mode == 'live' else '模拟盘'}")
        logger.info(f"初始资金: {self.initial_capital:,.0f}")
        logger.info(f"长线股: {[s['symbol'] for s in LONG_TERM_STOCKS]}")
        logger.info(f"波段策略: {SWING_CONFIG.get('strategies', [])}")
        logger.info(f"止损: {self.swing_stop_loss_pct:.0%}, 止盈: {self.swing_take_profit_pct:.0%}")
        logger.info("=" * 60)

        # 初始化长线股
        self._init_long_term()

        # 主循环
        self.running = True
        while self.running:
            try:
                self._cycle()
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("引擎停止")
                self.stop()
                break
            except Exception as e:
                logger.error(f"引擎异常: {e}", exc_info=True)
                time.sleep(60)

    def stop(self):
        """停止引擎"""
        self.running = False
        self.executor.disconnect()
        logger.info("双轨交易引擎已停止")

    def _init_long_term(self):
        """初始化长线股：回测找策略"""
        logger.info("初始化长线股策略...")
        for stock in LONG_TERM_STOCKS:
            symbol = stock["symbol"]
            try:
                # 获取历史数据
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=365*2)).strftime("%Y%m%d")
                df = self.dm.fetch_daily(symbol, start_date, end_date)
                if df.empty:
                    logger.warning(f"{symbol} 无历史数据，跳过")
                    continue
                self.long_term_data[symbol] = df

                # 寻找最优策略
                result = self.optimizer.optimize(symbol, df, capital=stock.get("min_capital", 100000))
                logger.info(f"  {symbol} 最优策略: {result['strategy']} {result['params']} "
                           f"(得分: {result.get('score', 0):.2f})")

                # 创建策略实例
                from core.optimizer import STRATEGY_LIBRARY
                s_info = STRATEGY_LIBRARY[result["strategy"]]
                strat = s_info["class"](**result["params"])

                # 创建网格做T策略
                from strategies.cost_reducer import GridStrategy
                grid_strat = GridStrategy(symbol)

                # 创建学习器
                param_space = s_info.get("params", {})
                learner = StrategyLearner(
                    strategy_name=f"longterm_{symbol}",
                    param_space={k: {"min": min(v), "max": max(v), "step": 1}
                                for k, v in param_space.items() if isinstance(v, list)},
                )

                self.long_term_positions[symbol] = {
                    "strat": strat,
                    "grid_strat": grid_strat,
                    "result": result,
                    "capital": stock.get("min_capital", 100000),
                    "last_price": 0,
                }
                self.long_term_learners[symbol] = learner
                logger.info(f"  {symbol} 初始化完成")

            except Exception as e:
                logger.error(f"  {symbol} 初始化失败: {e}", exc_info=True)

    def _cycle(self):
        """主循环"""
        now = datetime.now()
        self.cycle_count += 1

        # 检查交易时间
        if not RealtimeFeed._is_trading_time(now):
            if self.cycle_count % 60 == 0:
                logger.info(f"非交易时间，等待中... ({now.strftime('%H:%M:%S')})")
            return

        # 检查日期变更
        today = now.strftime("%Y-%m-%d")
        if today != self.daily_stats["last_date"]:
            self.daily_stats["trades"] = 0
            self.daily_stats["amount"] = 0
            self.daily_stats["last_date"] = today
            self._reset_daily_positions()

        # 1. 处理长线股
        self._process_long_term()

        # 2. 处理波段股
        self._process_swing()

        # 3. 风控检查
        self._risk_check()

        # 4. 定期重新平衡
        if self._should_rebalance(now):
            self._rebalance()

        # 5. 打印状态
        if self.cycle_count % 10 == 0:
            self._print_status()

    def _process_long_term(self):
        """长线股处理：趋势跟踪 + 网格做T"""
        for symbol, info in self.long_term_positions.items():
            try:
                # 获取最新数据
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
                df = self.dm.fetch_daily(symbol, start_date, end_date)
                if df.empty:
                    continue

                context = self._build_context(symbol, df)

                # 1. 主趋势策略信号
                signals = info["strat"].on_bar(context)
                if not isinstance(signals, list):
                    signals = [signals] if signals else []

                for sig in signals:
                    self._execute_signal(sig, df, "longterm")

                # 2. 网格做T策略信号（有持仓就运行）
                pos = self.executor.query_position(symbol)
                if pos > 0:
                    grid_signals = info["grid_strat"].on_bar(context)
                    if not isinstance(grid_signals, list):
                        grid_signals = [grid_signals] if grid_signals else []
                    for sig in grid_signals:
                        self._execute_signal(sig, df, "grid")

                # 3. 记录学习
                if symbol in self.long_term_learners:
                    current_price = df.iloc[-1]["close"]
                    info["last_price"] = current_price

            except Exception as e:
                logger.error(f"长线股处理失败 {symbol}: {e}", exc_info=True)

    def _process_swing(self):
        """波段股处理：扫描 + 交易 + 止损止盈"""
        now = time.time()
        scan_interval = SWING_CONFIG.get("scan_interval", 3600)

        # 扫描选股
        if now - self.last_scan_time >= scan_interval:
            self.last_scan_time = now
            self._scan_swing_opportunities()

        # 检查波段股卖出条件（止损止盈）
        self._check_swing_exits()

    def _scan_swing_opportunities(self):
        """扫描波段机会"""
        logger.info("开始波段股扫描...")

        max_positions = SWING_CONFIG.get("max_positions", 5)
        current_swing_count = len(self.swing_positions)

        if current_swing_count >= max_positions:
            logger.info(f"波段持仓已达上限 ({current_swing_count}/{max_positions})，跳过扫描")
            return

        available_slots = max_positions - current_swing_count

        for strat_name in SWING_CONFIG.get("strategies", ["ma_cross", "macd"]):
            try:
                candidates = self.scanner.scan(strat_name)
                for c in candidates[:available_slots]:
                    symbol = c["symbol"]
                    if symbol in self.swing_positions:
                        continue

                    # 获取当前价格
                    df = self.dm.fetch_daily(
                        symbol,
                        datetime.now().strftime("%Y%m%d"),
                        datetime.now().strftime("%Y%m%d")
                    )
                    if df.empty:
                        continue

                    current_price = df.iloc[-1]["close"]
                    # 计算买入数量（每只股票分配固定资金）
                    capital_per_stock = self.initial_capital / max_positions
                    volume = int(capital_per_stock / current_price / 100) * 100

                    if volume <= 0:
                        continue

                    # 执行买入
                    result = self.executor.submit_order(
                        symbol, "buy", current_price, volume,
                        strategy=f"swing_{strat_name}"
                    )

                    if result.get("status") == "filled":
                        logger.info(f"波段买入: {symbol} {volume}股 @ {current_price:.2f} "
                                   f"({c['reason']})")
                        self.swing_positions[symbol] = {
                            "strat": strat_name,
                            "entry_date": datetime.now().isoformat(),
                            "entry_price": result.get("filled_price", current_price),
                            "stats": c.get("stats", {}),
                            "volume": result.get("filled_volume", volume),
                        }
                        self.swing_entry_prices[symbol] = result.get("filled_price", current_price)
                        self.limiter.record_trade("buy", current_price * volume)
                        self.daily_stats["trades"] += 1
                        self.daily_stats["amount"] += current_price * volume

                        available_slots -= 1
                        if available_slots <= 0:
                            break

            except Exception as e:
                logger.error(f"扫描策略 {strat_name} 失败: {e}", exc_info=True)

    def _check_swing_exits(self):
        """检查波段股卖出条件（止损止盈）"""
        symbols_to_remove = []

        for symbol, info in list(self.swing_positions.items()):
            try:
                pos = self.executor.query_position(symbol)
                if pos == 0:
                    symbols_to_remove.append(symbol)
                    continue

                # 获取当前价格
                df = self.dm.fetch_daily(
                    symbol,
                    datetime.now().strftime("%Y%m%d"),
                    datetime.now().strftime("%Y%m%d")
                )
                if df.empty:
                    continue

                current_price = df.iloc[-1]["close"]
                entry_price = info.get("entry_price", self.swing_entry_prices.get(symbol, 0))

                if entry_price <= 0:
                    continue

                # 计算盈亏
                pnl_pct = (current_price - entry_price) / entry_price

                # 止损检查
                if pnl_pct <= self.swing_stop_loss_pct:
                    logger.warning(f"波段止损: {symbol} 亏损 {pnl_pct:.2%} "
                                 f"(入场: {entry_price:.2f}, 现价: {current_price:.2f})")
                    self._execute_swing_exit(symbol, current_price, pos, "止损")
                    symbols_to_remove.append(symbol)
                    continue

                # 止盈检查
                if pnl_pct >= self.swing_take_profit_pct:
                    logger.info(f"波段止盈: {symbol} 盈利 {pnl_pct:.2%} "
                               f"(入场: {entry_price:.2f}, 现价: {current_price:.2f})")
                    self._execute_swing_exit(symbol, current_price, pos, "止盈")
                    symbols_to_remove.append(symbol)
                    continue

            except Exception as e:
                logger.error(f"检查波段股 {symbol} 卖出条件失败: {e}", exc_info=True)

        # 清理已卖出的记录
        for symbol in symbols_to_remove:
            self.swing_positions.pop(symbol, None)
            self.swing_entry_prices.pop(symbol, None)

    def _execute_swing_exit(self, symbol: str, price: float, volume: int, reason: str):
        """执行波段卖出"""
        result = self.executor.submit_order(
            symbol, "sell", price, volume,
            strategy=f"swing_exit_{reason}"
        )

        if result.get("status") == "filled":
            filled_price = result.get("filled_price", price)
            entry_price = self.swing_entry_prices.get(symbol, 0)
            pnl = (filled_price - entry_price) * volume - result.get("fees", 0)
            logger.info(f"波段卖出: {symbol} {volume}股 @ {filled_price:.2f} "
                       f"({reason}, 盈亏: {pnl:+.2f})")
            self.limiter.record_trade("sell", filled_price * volume)
            self.daily_stats["trades"] += 1
            self.daily_stats["amount"] += filled_price * volume

    def _build_context(self, symbol: str, df: pd.DataFrame) -> dict:
        """构建策略上下文"""
        positions = {}
        for sym in list(self.long_term_positions.keys()) + list(self.swing_positions.keys()):
            vol = self.executor.query_position(sym)
            if vol > 0:
                positions[sym] = vol

        return {
            "data": {symbol: df},
            "current_bar": {symbol: df.iloc[-1]},
            "positions": positions,
            "cash": self.executor.query_cash(),
            "total_value": self.executor.get_portfolio_value(),
            "date": datetime.now(),
        }

    def _execute_signal(self, signal, df: pd.DataFrame, signal_type: str):
        """执行信号"""
        symbol = signal.get("symbol")
        action = signal.get("action")
        volume = signal.get("volume", 0)
        price = df.iloc[-1]["close"]

        if not symbol or not action or volume <= 0:
            return

        # 限制检查
        allowed, reason = self.limiter.check_trade(symbol, action, price, volume)
        if not allowed:
            logger.debug(f"{signal_type} {action} 被限制: {reason}")
            return

        # 下单
        result = self.executor.submit_order(
            symbol, action, price, volume,
            strategy=f"{signal_type}_{signal.get('reason', '')}"
        )

        if result.get("status") == "filled":
            filled_price = result.get("filled_price", price)
            filled_volume = result.get("filled_volume", volume)
            logger.info(f"{signal_type} {action}: {symbol} {filled_volume}股 @ {filled_price:.2f}")
            self.limiter.record_trade(action, filled_price * filled_volume)
            self.daily_stats["trades"] += 1
            self.daily_stats["amount"] += filled_price * filled_volume

            # 记录学习
            if symbol in self.long_term_learners:
                self.long_term_learners[symbol].record_trade(
                    symbol, action, filled_price, filled_volume,
                    datetime.now().isoformat(),
                    signal.get("params", {}),
                    f"{signal_type}: {signal.get('reason', '')}"
                )

    def _risk_check(self):
        """风控检查"""
        # 获取当前价格
        prices = {}
        for symbol in list(self.long_term_positions.keys()) + list(self.swing_positions.keys()):
            try:
                df = self.dm.fetch_daily(
                    symbol,
                    datetime.now().strftime("%Y%m%d"),
                    datetime.now().strftime("%Y%m%d")
                )
                if not df.empty:
                    prices[symbol] = df.iloc[-1]["close"]
            except Exception:
                pass

        if not prices:
            return

        total_value = self.executor.get_portfolio_value(prices)
        self.risk.peak_value = max(self.risk.peak_value, total_value)

        # 回撤检查
        drawdown = self.risk.check_drawdown(total_value, self.risk.peak_value)
        if drawdown < config.RISK_CONFIG["max_drawdown_pct"]:
            logger.critical(f"触发最大回撤 {drawdown:.2%}，暂停交易")
            self.running = False
            return

        # 持仓止损检查
        for symbol, pos in self.executor.query_all_positions().items():
            if pos.volume <= 0:
                continue
            price = prices.get(symbol, pos.cost_price)
            if pos.cost_price > 0:
                pnl_pct = (price - pos.cost_price) / pos.cost_price
                if pnl_pct <= config.RISK_CONFIG["stop_loss_pct"]:
                    logger.warning(f"止损触发: {symbol} 亏损 {pnl_pct:.2%}")
                    # 如果是波段股，执行卖出
                    if symbol in self.swing_positions:
                        self._execute_swing_exit(symbol, price, pos.available_volume, "风控止损")
                        self.swing_positions.pop(symbol, None)

    def _reset_daily_positions(self):
        """每日重置"""
        logger.info(f"每日重置: {self.daily_stats['last_date']}")
        logger.info(f"昨日交易: {self.daily_stats['trades']}笔, 金额: {self.daily_stats['amount']:,.0f}")
        # T+1 处理：昨日买入今日可用
        # TradeSimulator 内部已处理

    def _should_rebalance(self, now: datetime) -> bool:
        """是否需要重新学习"""
        if self.last_rebalance is None:
            return True
        return (now - self.last_rebalance).total_seconds() / 60 >= self.rebalance_minutes

    def _rebalance(self):
        """重新学习优化"""
        logger.info("开始自主学习优化...")
        self.last_rebalance = datetime.now()

        for symbol, learner in self.long_term_learners.items():
            try:
                recent_trades = learner.trade_history[-20:]
                if recent_trades:
                    learner.adaptive_update(recent_trades)
                    stats = learner.get_learning_stats()
                    logger.info(f"  {symbol} 学习统计: {stats['total_trades']}笔, "
                               f"胜率 {stats.get('win_rate', 0):.0%}")
            except Exception as e:
                logger.error(f"  {symbol} 学习优化失败: {e}", exc_info=True)

    def _print_status(self):
        """打印当前状态"""
        prices = {}
        for symbol in list(self.long_term_positions.keys()) + list(self.swing_positions.keys()):
            try:
                df = self.dm.fetch_daily(
                    symbol,
                    datetime.now().strftime("%Y%m%d"),
                    datetime.now().strftime("%Y%m%d")
                )
                if not df.empty:
                    prices[symbol] = df.iloc[-1]["close"]
            except Exception:
                pass

        total = self.executor.get_portfolio_value(prices)
        equity = self.executor.get_equity_curve(prices)

        logger.info("\n" + "-" * 50)
        logger.info(f"模式: {'实盘' if self.mode == 'live' else '模拟盘'}")
        logger.info(f"总资产: {total:,.0f} (现金: {equity['cash']:,.0f}, 持仓: {equity['position_value']:,.0f})")
        logger.info(f"总盈亏: {equity['pnl']:+,.0f} ({equity['pnl_pct']:+.2%})")
        logger.info(f"长线持仓: {len([s for s, p in self.executor.query_all_positions().items() if p.volume > 0 and s in self.long_term_positions])} 只")
        logger.info(f"波段持仓: {len(self.swing_positions)} 只")

        for symbol, pos in self.executor.query_all_positions().items():
            if pos.volume > 0:
                price = prices.get(symbol, pos.cost_price)
                pnl = (price - pos.cost_price) / pos.cost_price if pos.cost_price > 0 else 0
                track = "长线" if symbol in self.long_term_positions else "波段"
                logger.info(f"  [{track}] {symbol}: {pos.volume}股 @ {pos.cost_price:.3f} "
                           f"现价{price:.3f} ({pnl:+.2%})")

        logger.info("-" * 50)

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
