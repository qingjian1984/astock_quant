"""
模拟盘测试脚本
用于验证双轨交易引擎的完整功能，包括：
- 券商接口（模拟）
- 订单生命周期
- T+1 交易规则
- 止损止盈
- 风控检查
- 学习器

使用方法:
    python live/test_paper_trading.py
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
import pandas as pd
import config


def setup_logger():
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    logger.add(
        project_root / "logs" / "paper_test.log",
        rotation="1 day",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8"
    )


def test_broker_interface():
    """测试券商接口"""
    logger.info("=" * 60)
    logger.info("测试 1: 券商接口 (TradeSimulator)")
    logger.info("=" * 60)

    from live.trader import TradeSimulator
    from live.broker import Order

    # 创建模拟器
    simulator = TradeSimulator(initial_capital=1_000_000)
    assert simulator.connected, "模拟器应已连接"
    assert simulator.cash == 1_000_000, "初始资金应为 1,000,000"
    logger.info(f"初始资金: {simulator.cash:,.0f}")

    # 测试买入
    logger.info("\n--- 测试买入 ---")
    result = simulator.submit_order("000001", "buy", 10.0, 1000)
    assert result["status"] == "filled", f"买入应成交，实际: {result['status']}"
    assert simulator.cash < 1_000_000, "资金应减少"
    logger.info(f"买入结果: {result}")
    logger.info(f"剩余资金: {simulator.cash:,.2f}")

    # 测试持仓
    pos = simulator.query_position("000001")
    assert pos > 0, "应有持仓"
    logger.info(f"持仓数量: {pos}")

    # 测试 T+1（简化模式下立即可用）
    logger.info("\n--- 测试卖出 ---")
    result = simulator.submit_order("000001", "sell", 10.5, 1000)
    assert result["status"] == "filled", f"卖出应成交，实际: {result['status']}"
    logger.info(f"卖出结果: {result}")
    logger.info(f"卖出后资金: {simulator.cash:,.2f}")

    # 测试无效订单
    logger.info("\n--- 测试无效订单 ---")
    result = simulator.submit_order("000001", "buy", 10.0, 50)  # 非 100 整数倍
    assert result["status"] == "rejected", "非 100 整数倍应被拒绝"
    logger.info(f"无效订单结果: {result}")

    result = simulator.submit_order("000001", "buy", -1, 100)  # 负价格
    assert result["status"] == "rejected", "负价格应被拒绝"
    logger.info(f"负价格订单结果: {result}")

    # 测试订单查询
    logger.info("\n--- 测试订单查询 ---")
    orders = simulator.query_orders()
    logger.info(f"总订单数: {len(orders)}")
    filled_orders = [o for o in orders if o.status == Order.STATUS_FILLED]
    logger.info(f"已成交订单: {len(filled_orders)}")

    logger.info("\n券商接口测试通过!")
    return True


def test_risk_manager():
    """测试风控模块"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 2: 风控模块 (RiskManager)")
    logger.info("=" * 60)

    from risk.manager import RiskManager

    risk = RiskManager()
    risk.total_capital = 1_000_000
    risk.peak_value = 1_000_000

    # 测试正常情况
    dd = risk.check_drawdown(950_000, 1_000_000)
    assert dd == -0.05, f"回撤应为 -5%，实际: {dd}"
    logger.info(f"回撤 5%: {dd:.2%}")

    # 测试触发最大回撤
    dd = risk.check_drawdown(800_000, 1_000_000)
    assert dd == -0.20, f"回撤应为 -20%，实际: {dd}"
    logger.info(f"回撤 20%: {dd:.2%}")

    # 测试新高
    risk.peak_value = max(risk.peak_value, 1_100_000)
    assert risk.peak_value == 1_100_000, "峰值应更新"
    logger.info(f"新高: {risk.peak_value:,.0f}")

    logger.info("\n风控模块测试通过!")
    return True


def test_learner():
    """测试学习器"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 3: 学习器 (StrategyLearner)")
    logger.info("=" * 60)

    from live.learner import StrategyLearner

    learner = StrategyLearner(
        strategy_name="ma_cross",
        param_space={"fast": {"min": 3, "max": 10, "step": 1},
                     "slow": {"min": 15, "max": 30, "step": 1}}
    )

    # 测试交易记录
    learner.record_trade("000001", "buy", 10.0, 1000, "2024-01-01",
                         {"fast": 5, "slow": 20}, "MA5 上穿 MA20")
    learner.record_trade("000001", "sell", 10.5, 1000, "2024-01-10",
                         {"fast": 5, "slow": 20}, "MA5 下穿 MA20")

    # 测试交易结果
    pnl, pnl_pct = learner.record_trade_result(0, 10.5, "2024-01-10", 50)
    assert pnl > 0, "盈利应为正"
    logger.info(f"交易盈亏: {pnl:+.2f} ({pnl_pct:+.2%})")

    # 测试学习统计
    stats = learner.get_learning_stats()
    assert stats["total_trades"] >= 2, "应至少有 2 笔交易"
    logger.info(f"学习统计: {stats}")

    # 测试建议
    suggestion = learner.suggest_action("000001", {"close": 10.5},
                                        {"history": pd.DataFrame({
                                            "close": [10.0] * 10 + [10.2, 10.3, 10.5]
                                        })})
    logger.info(f"操作建议: {suggestion}")

    logger.info("\n学习器测试通过!")
    return True


def test_limiter():
    """测试交易限制器"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 4: 交易限制器 (TradeLimiter)")
    logger.info("=" * 60)

    from live.limiter import TradeLimiter

    limiter = TradeLimiter()

    # 测试正常交易
    allowed, reason = limiter.check_trade("000001", "buy", 10.0, 1000)
    assert allowed, f"正常交易应被允许，实际: {reason}"
    logger.info(f"正常交易: {allowed}")

    # 记录交易
    limiter.record_trade("buy", 10_000)

    # 测试状态
    status = limiter.get_status()
    logger.info(f"限制器状态: {status}")

    logger.info("\n交易限制器测试通过!")
    return True


def test_scanner():
    """测试选股扫描器"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 5: 选股扫描器 (StockScanner)")
    logger.info("=" * 60)

    from live.scanner import StockScanner
    from data.manager import DataSourceManager
    from data.sources.akshare_src import AKShareSource
    from data.sources.baostock_src import BaoStockSource

    # 创建数据源管理器
    dm = DataSourceManager()
    dm.register(AKShareSource(retry=2))
    dm.register(BaoStockSource())
    dm.connect_all()

    scanner = StockScanner(dm)

    # 测试扫描（使用小股票池）
    test_pool = ["000001", "600519"]
    candidates = scanner.scan("ma_cross", pool=test_pool, lookback_days=30)

    logger.info(f"扫描结果: {len(candidates)} 只候选股票")
    for c in candidates:
        logger.info(f"  {c['symbol']}: {c['reason']} (评分: {c['score']:.2f})")

    logger.info("\n选股扫描器测试通过!")
    return True


def test_full_paper_trading():
    """完整模拟盘测试"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 6: 完整模拟盘流程 (DualTrackEngine)")
    logger.info("=" * 60)

    from live.dual_engine import DualTrackEngine

    # 创建引擎（模拟盘模式）
    engine = DualTrackEngine(trading_mode="paper", initial_capital=1_000_000)

    # 测试初始化
    assert engine.mode == "paper", "应为模拟盘模式"
    assert engine.executor.connected, "执行器应已连接"
    logger.info(f"引擎模式: {engine.mode}")
    logger.info(f"初始资金: {engine.initial_capital:,.0f}")

    # 测试长线股初始化（如果配置了）
    if config.LONG_TERM_STOCKS:
        logger.info(f"长线股配置: {[s['symbol'] for s in config.LONG_TERM_STOCKS]}")
        engine._init_long_term()
        logger.info(f"初始化完成: {len(engine.long_term_positions)} 只长线股")

    # 测试状态获取
    equity = engine.executor.get_equity_curve()
    logger.info(f"当前权益: {equity}")

    # 测试单个交易周期
    logger.info("\n--- 测试交易周期 ---")
    engine._cycle()
    logger.info("交易周期执行完成")

    # 打印最终状态
    logger.info("\n--- 最终状态 ---")
    logger.info(f"总资产: {engine.executor.get_portfolio_value():,.0f}")
    logger.info(f"现金: {engine.executor.query_cash():,.0f}")
    logger.info(f"持仓: {len(engine.executor.query_all_positions())} 只")

    for symbol, pos in engine.executor.query_all_positions().items():
        if pos.volume > 0:
            logger.info(f"  {symbol}: {pos.volume}股, 成本 {pos.cost_price:.3f}")

    logger.info("\n完整模拟盘测试通过!")
    return True


def main():
    """主测试函数"""
    setup_logger()

    logger.info("A股量化交易系统 - 模拟盘测试")
    logger.info(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"项目路径: {project_root}")

    tests = [
        ("券商接口", test_broker_interface),
        ("风控模块", test_risk_manager),
        ("学习器", test_learner),
        ("交易限制器", test_limiter),
        ("选股扫描器", test_scanner),
        ("完整模拟盘", test_full_paper_trading),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                logger.error(f"测试失败: {name}")
        except Exception as e:
            failed += 1
            logger.error(f"测试异常: {name} - {e}", exc_info=True)

    # 总结
    logger.info("\n" + "=" * 60)
    logger.info("测试总结")
    logger.info("=" * 60)
    logger.info(f"通过: {passed}/{len(tests)}")
    logger.info(f"失败: {failed}/{len(tests)}")

    if failed == 0:
        logger.info("\n所有测试通过! 系统可以进入模拟盘运行阶段。")
        logger.info("\n下一步:")
        logger.info("1. 运行模拟盘: python live/run.py --mode paper")
        logger.info("2. 观察至少 1-3 个月")
        logger.info("3. 验证策略稳定性后，再考虑小资金实盘")
    else:
        logger.warning(f"\n有 {failed} 个测试失败，请修复后再运行。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
