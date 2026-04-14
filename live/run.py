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
                       trading_mode: str = "paper", check_interval: int = 60,
                       custom_limits: dict = None):
    """
    启动交易
    trading_mode: "paper"=模拟盘, "live"=实盘
    """
    logger.info("=" * 50)
    logger.info("A股量化交易系统 - 交易模块")
    logger.info("=" * 50)

    if trading_mode == "live":
        logger.warning("实盘模式：请确认已配置券商API")
    else:
        logger.info("模拟盘模式：安全测试")

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
        trading_mode=trading_mode,
        custom_limits=custom_limits,
    )
    trader.check_interval = check_interval

    # 注入监管
    original_cycle = trader._cycle

    def monitored_cycle():
        original_cycle()
        state = trader.executor.get_state() if hasattr(trader.executor, "get_state") else {}
        supervisor.heartbeat(state)
        supervisor.check_system_health()

    trader._cycle = monitored_cycle

    # 启动
    try:
        trader.start()
    finally:
        learning_stats = trader.learner.get_learning_stats()
        report = supervisor.generate_daily_report(trader.executor.get_state() if hasattr(trader.executor, 'get_state') else {}, learning_stats)
        logger.info(report)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A股交易系统")
    parser.add_argument("--symbol", default="000001", help="股票代码 (多个用逗号分隔)")
    parser.add_argument("--strategy", default="ma_cross", choices=list(STRATEGIES.keys()))
    parser.add_argument("--mode", default="paper", choices=["paper", "live"], help="paper=模拟盘, live=实盘")
    parser.add_argument("--interval", type=int, default=60, help="检查间隔（秒）")

    # 交易限制
    parser.add_argument("--max-trades", type=int, help="每日最大交易次数")
    parser.add_argument("--max-amount", type=int, help="单笔最大金额")
    parser.add_argument("--max-volume", type=int, help="单笔最大股数")
    parser.add_argument("--min-interval", type=int, help="最小交易间隔（秒）")
    parser.add_argument("--max-daily-amount", type=int, help="每日最大交易总额")

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbol.split(",")]

    # 构建自定义限制
    custom_limits = {}
    if args.max_trades:
        custom_limits["max_trades_per_day"] = args.max_trades
    if args.max_amount:
        custom_limits["max_amount_per_trade"] = args.max_amount
    if args.max_volume:
        custom_limits["max_volume_per_trade"] = args.max_volume
    if args.min_interval:
        custom_limits["min_trade_interval"] = args.min_interval
    if args.max_daily_amount:
        custom_limits["max_daily_amount"] = args.max_daily_amount

    start_live_trading(
        symbols=symbols,
        strategy_name=args.strategy,
        trading_mode=args.mode,
        check_interval=args.interval,
        custom_limits=custom_limits if custom_limits else None,
    )
