"""回测入口"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from loguru import logger
from data.fetcher import fetch_daily
from backtest.engine import BacktestEngine
from strategy.ma_cross import MACrossStrategy


def run_backtest(symbol: str = "000001", start: str = "20230101", end: str = "20241231"):
    """
    运行回测
    symbol: 股票代码（纯数字，如 000001 = 平安银行）
    """
    logger.info(f"=== A股量化回测系统 ===")
    logger.info(f"股票: {symbol}, 区间: {start} ~ {end}")

    # 1. 获取数据
    df = fetch_daily(symbol, start, end)
    if df.empty:
        logger.error("未获取到数据，退出")
        return

    logger.info(f"获取到 {len(df)} 条数据")
    logger.info(f"数据范围: {df.index[0]} ~ {df.index[-1]}")

    # 2. 初始化策略
    strategy = MACrossStrategy(fast=5, slow=20)

    # 3. 运行回测
    engine = BacktestEngine(strategy, initial_capital=1_000_000)
    stats = engine.run(df, symbol)

    # 4. 输出结果
    logger.info("\n===== 回测结果 =====")
    for k, v in stats.items():
        logger.info(f"  {k}: {v}")

    # 5. 保存交易记录
    trades = engine.get_trades()
    if not trades.empty:
        trades.to_csv(f"trades_{symbol}.csv", index=False)
        logger.info(f"交易记录已保存到 trades_{symbol}.csv")

    # 6. 保存净值曲线
    equity = engine.get_equity_curve()
    equity.to_csv(f"equity_{symbol}.csv", index=False)

    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A股量化回测")
    parser.add_argument("--symbol", default="000001", help="股票代码")
    parser.add_argument("--start", default="20230101", help="开始日期")
    parser.add_argument("--end", default="20241231", help="结束日期")
    args = parser.parse_args()

    run_backtest(args.symbol, args.start, args.end)
