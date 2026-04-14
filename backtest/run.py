"""回测入口 - 整合可视化、监控、多标的"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from loguru import logger
from data.manager import DataSourceManager
from data.sources.akshare_src import AKShareSource
from data.sources.baostock_src import BaoStockSource
from data.sources.tushare_src import TushareSource
from data.sources.yahoo_src import YahooFinanceSource
from backtest.engine import BacktestEngine
from utils.viz import plot_equity_curve, plot_trades, plot_monthly_returns
from utils.monitor import AlertManager, PerformanceMonitor
from utils.analyst import StrategyAnalyst
import config

# 策略导入
from strategy.ma_cross import MACrossStrategy
from strategy.rsi import RSIStrategy
from strategy.macd import MACDStrategy
from strategy.multi_factor import MultiFactorStrategy

# 初始化数据源管理器
_mgr = None

def get_data_manager() -> DataSourceManager:
    global _mgr
    if _mgr is None:
        _mgr = DataSourceManager()
        for ds_cfg in config.DATA_SOURCES:
            if not ds_cfg["enabled"]:
                continue
            name = ds_cfg["name"]
            if name == "AKShare":
                _mgr.register(AKShareSource(retry=config.AKSHARE_RETRY))
            elif name == "BaoStock":
                _mgr.register(BaoStockSource())
            elif name == "Tushare" and config.TUSHARE_TOKEN:
                _mgr.register(TushareSource(token=config.TUSHARE_TOKEN))
            elif name == "YahooFinance":
                _mgr.register(YahooFinanceSource())
        _mgr.connect_all()
    return _mgr

STRATEGIES = {
    "ma_cross": lambda: MACrossStrategy(fast=5, slow=20),
    "rsi": lambda: RSIStrategy(period=14),
    "macd": lambda: MACDStrategy(fast=12, slow=26, signal=9),
    "multi_factor": lambda: MultiFactorStrategy(top_n=5, rebalance_days=20),
}


def run_backtest(
    symbols: list | str = "000001",
    start: str = "20230101",
    end: str = "20241231",
    strategy_name: str = "ma_cross",
    initial_capital: float = 1_000_000,
    slippage: float = 0.001,
    plot: bool = True,
    source: str = None,
):
    """
    运行回测
    symbols: 单个代码字符串或代码列表
    strategy_name: 策略名称 (ma_cross / rsi / macd / multi_factor)
    """
    if isinstance(symbols, str):
        symbols = [symbols]

    logger.info(f"=== A股量化回测系统 ===")
    logger.info(f"策略: {strategy_name}")
    logger.info(f"标的: {symbols}")
    logger.info(f"区间: {start} ~ {end}")
    logger.info(f"初始资金: {initial_capital:,.0f}")
    logger.info(f"滑点: {slippage:.3%}")

    # 初始化策略
    if strategy_name not in STRATEGIES:
        logger.error(f"未知策略: {strategy_name}, 可选: {list(STRATEGIES.keys())}")
        return

    strategy = STRATEGIES[strategy_name]()

    # 初始化监控
    alert = AlertManager()
    monitor = PerformanceMonitor(alert)

    # 初始化数据源
    dm = get_data_manager()
    available = dm.available_sources()
    logger.info(f"可用数据源: {', '.join(s.name for s in available)}")

    # 拉取数据
    data = {}
    for sym in symbols:
        logger.info(f"拉取数据: {sym}")
        if source:
            # 指定数据源
            df = dm.fetch_by_source(source, sym, start, end)
        else:
            # 自动降级
            df = dm.fetch_daily(sym, start, end)
        if df.empty:
            logger.warning(f"{sym} 无数据，跳过")
            continue
        data[sym] = df
        logger.info(f"  {sym}: {len(df)} 条")

    if not data:
        logger.error("无可用数据，退出")
        return

    # 运行回测
    engine = BacktestEngine(strategy, initial_capital, slippage=slippage)
    stats = engine.run(data)

    # 输出结果
    logger.info("\n" + "=" * 40)
    logger.info("回测结果")
    logger.info("=" * 40)
    for k, v in stats.items():
        logger.info(f"  {k}: {v}")

    # 策略分析与建议
    equity = engine.get_equity_curve()
    trades = engine.get_trades()
    analyst = StrategyAnalyst()
    report = analyst.analyze(equity, trades, stats, symbol=symbols[0])
    analyst.print_report(report)

    # 监控检查
    if engine.equity_curve:
        final = engine.equity_curve[-1]
        monitor.daily_pnl(final["equity"])

    # 保存交易记录
    results_dir = Path(__file__).resolve().parent.parent / "results"
    results_dir.mkdir(exist_ok=True)

    if not trades.empty:
        trades.to_csv(results_dir / "trades.csv", index=False)
        logger.info(f"交易记录: {results_dir / 'trades.csv'}")

    equity.to_csv(results_dir / "equity.csv", index=False)
    logger.info(f"净值曲线: {results_dir / 'equity.csv'}")

    # 可视化
    if plot and len(equity) > 1:
        try:
            p1 = plot_equity_curve(equity)
            logger.info(f"净值图: {p1}")

            if not trades.empty:
                p2 = plot_trades(equity, trades)
                logger.info(f"交易图: {p2}")

            p3 = plot_monthly_returns(equity)
            logger.info(f"月度收益: {p3}")
        except Exception as e:
            logger.warning(f"可视化失败: {e}")

    # 每日报告
    alert.daily_report(stats)

    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A股量化回测系统")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # 回测命令
    bt_parser = subparsers.add_parser("backtest", help="运行回测")
    bt_parser.add_argument("--symbol", default="000001", help="股票代码 (多个用逗号分隔)")
    bt_parser.add_argument("--start", default="20240101", help="开始日期")
    bt_parser.add_argument("--end", default="20241231", help="结束日期")
    bt_parser.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "rsi", "macd", "multi_factor"])
    bt_parser.add_argument("--capital", type=float, default=1_000_000, help="初始资金")
    bt_parser.add_argument("--slippage", type=float, default=0.001, help="滑点")
    bt_parser.add_argument("--source", default=None, help="指定数据源 (AKShare/BaoStock/Tushare)")
    bt_parser.add_argument("--no-plot", action="store_true", help="不生成图表")

    # 数据源对比命令
    cmp_parser = subparsers.add_parser("compare", help="对比数据源数据质量")
    cmp_parser.add_argument("--symbol", default="000001", help="股票代码")
    cmp_parser.add_argument("--start", default="20240101", help="开始日期")
    cmp_parser.add_argument("--end", default="20241231", help="结束日期")

    # 列出数据源
    subparsers.add_parser("list-sources", help="列出已注册的数据源")

    args = parser.parse_args()

    if args.command == "compare":
        dm = get_data_manager()
        logger.info(f"对比数据源: {args.symbol} {args.start} ~ {args.end}")
        result = dm.compare_sources(args.symbol, args.start, args.end)
        if not result.empty:
            print(result.to_string(index=False))
        else:
            logger.warning("无可用数据")

    elif args.command == "list-sources":
        dm = get_data_manager()
        print(f"\n{'数据源':<20} {'优先级':<8} {'状态':<10}")
        print("-" * 40)
        for s in dm.list_sources():
            status = "可用" if s.is_available() else "不可用"
            print(f"{s.name:<20} {s.priority:<8} {status:<10}")
        print()
        stats = dm.get_stats()
        if not stats.empty:
            print(stats.to_string(index=False))

    elif args.command == "backtest" or args.command is None:
        symbols = [s.strip() for s in args.symbol.split(",")]
        kwargs = {
            "symbols": symbols,
            "start": args.start,
            "end": args.end,
            "strategy_name": args.strategy,
            "initial_capital": args.capital,
            "slippage": args.slippage,
            "plot": not args.no_plot,
        }
        if args.source:
            kwargs["source"] = args.source
        run_backtest(**kwargs)
