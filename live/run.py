"""实盘交易入口"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from strategy.ma_cross import MACrossStrategy
from strategy.rsi import RSIStrategy
from strategy.macd import MACDStrategy
from live.auto_trader import AutoTrader
from live.supervisor import TradingSupervisor
from utils.monitor import AlertManager
import config

STRATEGIES = {
    "ma_cross": lambda: MACrossStrategy(fast=5, slow=20),
    "rsi": lambda: RSIStrategy(period=14),
    "macd": lambda: MACDStrategy(fast=12, slow=26, signal=9),
}

PARAM_SPACES = {
    "ma_cross": {
        "fast": {"min": 3, "max": 10, "step": 1},
        "slow": {"min": 15, "max": 30, "step": 1},
    },
    "rsi": {
        "period": {"min": 10, "max": 20, "step": 1},
    },
    "macd": {
        "fast": {"min": 8, "max": 15, "step": 1},
        "slow": {"min": 20, "max": 30, "step": 1},
        "signal": {"min": 5, "max": 12, "step": 1},
    },
}


def start_live_trading(symbols: list, strategy_name: str = "ma_cross",
                       check_interval: int = 60, dry_run: bool = True):
    """
    启动实盘交易
    dry_run: True=模拟交易, False=实盘（需券商API）
    """
    logger.info("=" * 50)
    logger.info("A股量化交易系统 - 实盘交易模块")
    logger.info("=" * 50)

    if dry_run:
        logger.warning("当前为模拟交易模式（dry_run=True）")
        logger.warning("实盘交易需要对接券商API，请修改 TradeSimulator")

    # 初始化策略
    if strategy_name not in STRATEGIES:
        logger.error(f"未知策略: {strategy_name}")
        return

    strategy = STRATEGIES[strategy_name]()
    param_space = PARAM_SPACES.get(strategy_name, {})

    # 初始化监管
    alert = AlertManager()
    supervisor = TradingSupervisor(alert)

    # 初始化自动交易引擎
    trader = AutoTrader(
        strategy=strategy,
        symbols=symbols,
        strategy_name=strategy_name,
        param_space=param_space,
    )
    trader.check_interval = check_interval

    # 注入监管
    original_cycle = trader._cycle

    def monitored_cycle():
        original_cycle()
        supervisor.heartbeat(trader.trader.get_state())

        # 检查系统健康
        supervisor.check_system_health()

        # 检查盈亏
        prices = {s: trader.feed.get_latest(s).get("price", 0) for s in symbols}
        total_value = trader.trader.get_portfolio_value(prices)
        supervisor.check_pnl_alert(total_value, trader.trader.cash + sum(
            p["volume"] * p["cost"] for p in trader.trader.positions.values()
        ), trader.trader.cash)

    trader._cycle = monitored_cycle

    # 启动
    try:
        trader.start()
    finally:
        # 生成最终报告
        learning_stats = trader.learner.get_learning_stats()
        report = supervisor.generate_daily_report(trader.trader.get_state(), learning_stats)
        logger.info(report)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A股实盘交易")
    parser.add_argument("--symbol", default="000001", help="股票代码 (多个用逗号分隔)")
    parser.add_argument("--strategy", default="ma_cross", choices=list(STRATEGIES.keys()))
    parser.add_argument("--interval", type=int, default=60, help="检查间隔（秒）")
    parser.add_argument("--live", action="store_true", help="实盘模式（默认模拟）")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbol.split(",")]
    start_live_trading(
        symbols=symbols,
        strategy_name=args.strategy,
        check_interval=args.interval,
        dry_run=not args.live,
    )
