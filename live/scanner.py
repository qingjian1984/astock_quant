"""选股扫描器"""
import pandas as pd
from loguru import logger
from data.manager import DataSourceManager
from backtest.engine import BacktestEngine
from strategy.ma_cross import MACrossStrategy
from strategy.macd import MACDStrategy
from strategy.rsi import RSIStrategy
from strategy.multi_factor import MultiFactorStrategy


class StockScanner:
    """
    波段股选股扫描器
    遍历股票列表，用策略筛选出符合条件的股票
    """

    STRATEGIES = {
        "ma_cross": lambda: MACrossStrategy(fast=5, slow=20),
        "macd": lambda: MACDStrategy(fast=12, slow=26, signal=9),
        "rsi": lambda: RSIStrategy(period=14),
        "multi_factor": lambda: MultiFactorStrategy(top_n=3),
    }

    def __init__(self, dm: DataSourceManager):
        self.dm = dm
        self.candidates = []

    def scan(self, strategy_name: str, pool: list = None, lookback_days: int = 60) -> list:
        """
        扫描符合条件的股票
        pool: 股票池，默认从数据源获取
        Returns: [{"symbol": str, "score": float, "reason": str}]
        """
        if pool is None:
            logger.info("获取股票池...")
            stock_list = self.dm.fetch_stock_list()
            if stock_list.empty:
                return []
            # 默认取前100只测试
            pool = stock_list["symbol"].head(100).tolist()

        logger.info(f"开始扫描 {len(pool)} 只股票，策略: {strategy_name}")
        strategy = self.STRATEGIES.get(strategy_name)
        if not strategy:
            logger.error(f"未知策略: {strategy_name}")
            return []

        candidates = []
        for symbol in pool:
            try:
                df = self.dm.fetch_daily(symbol, "20240101", "20241231")
                if df.empty or len(df) < lookback_days:
                    continue

                # 快速回测判断是否有买入信号
                engine = BacktestEngine(strategy(), initial_capital=100000)
                stats = engine.run(df, symbols=[symbol])

                # 评分逻辑：有买入信号且预期收益为正
                trades = engine.get_trades()
                if trades.empty:
                    continue

                # 检查最后一笔交易是否是买入（当前持有）
                last_trade = trades.iloc[-1]
                if last_trade["action"] == "buy":
                    candidates.append({
                        "symbol": symbol,
                        "score": float(stats.get("夏普比率", 0)),
                        "reason": f"{strategy_name}发出买入信号",
                        "stats": stats,
                    })
            except Exception as e:
                logger.debug(f"扫描 {symbol} 失败: {e}")

        # 按评分排序
        candidates.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"扫描完成，发现 {len(candidates)} 只候选股票")
        return candidates
