"""自主学习能力模块"""
import pandas as pd
import numpy as np
from loguru import logger
from pathlib import Path
import json
import datetime


class StrategyLearner:
    """
    策略自主学习器
    通过历史交易表现自动优化参数
    """

    def __init__(self, strategy_name: str, param_space: dict, memory_path: str = None):
        self.strategy_name = strategy_name
        self.param_space = param_space  # {"param_name": {"min": x, "max": y, "step": z}}
        self.memory_path = memory_path or Path("data/learning_memory.json")
        self.memory_path = Path(self.memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)

        self.best_params = {}
        self.trade_history = []
        self.performance_log = []

        self._load_memory()

    def record_trade(self, symbol: str, action: str, price: float, volume: int,
                     date: str, params_used: dict = None, reason: str = ""):
        """记录一次交易"""
        self.trade_history.append({
            "symbol": symbol,
            "action": action,
            "price": price,
            "volume": volume,
            "date": date,
            "params": params_used or {},
            "reason": reason,
        })
        self._save_memory()

    def record_trade_result(self, trade_index: int, exit_price: float,
                            exit_date: str, fee: float = 0):
        """记录交易结果"""
        if trade_index < len(self.trade_history):
            trade = self.trade_history[trade_index]
            if trade["action"] == "buy":
                pnl = (exit_price - trade["price"]) * trade["volume"] - fee
                pnl_pct = (exit_price - trade["price"]) / trade["price"]
                hold_days = (pd.Timestamp(exit_date) - pd.Timestamp(trade["date"])).days

                trade.update({
                    "exit_price": exit_price,
                    "exit_date": exit_date,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "hold_days": hold_days,
                    "fee": fee,
                    "result": "win" if pnl > 0 else "loss",
                })
                self._save_memory()
                return pnl, pnl_pct
        return 0, 0

    def evaluate_params(self, params: dict, data: pd.DataFrame, capital: float = 100000) -> dict:
        """
        评估一组参数的表现（接入回测引擎）
        运行完整的回测来评估参数效果
        """
        try:
            # 动态导入策略类
            from strategy.base import BaseStrategy
            from backtest.engine import BacktestEngine

            # 根据策略名称找到对应的策略类
            strategy_class = self._get_strategy_class()
            if not strategy_class:
                return {
                    "params": params,
                    "score": -999,
                    "win_rate": 0,
                    "avg_pnl": 0,
                    "max_dd": 1,
                    "total_return": 0,
                    "sharpe": 0,
                    "error": "未知策略类",
                }

            # 创建策略实例
            strat = strategy_class(**params)

            # 运行回测
            engine = BacktestEngine(strat, initial_capital=capital)
            stats = engine.run(data, symbols=["stock"])

            if not stats:
                return {
                    "params": params,
                    "score": -999,
                    "win_rate": 0,
                    "avg_pnl": 0,
                    "max_dd": 1,
                    "total_return": 0,
                    "sharpe": 0,
                    "error": "回测无结果",
                }

            # 解析统计数据
            total_return = self._parse_pct(stats.get("总收益率", "0%"))
            max_dd = abs(self._parse_pct(stats.get("最大回撤", "0%")))
            sharpe = float(stats.get("夏普比率", "0"))
            win_rate = self._parse_pct(stats.get("胜率", "0%"))

            # 计算综合评分
            # 收益 40% + (1-回撤) 30% + 夏普 20% + 胜率 10%
            score = (
                total_return * 40 +
                (1 - max_dd) * 30 +
                max(sharpe, 0) * 20 +
                win_rate * 10
            )

            return {
                "params": params,
                "score": score,
                "win_rate": win_rate,
                "avg_pnl": total_return,
                "max_dd": max_dd,
                "total_return": total_return,
                "sharpe": sharpe,
                "stats": stats,
            }

        except Exception as e:
            logger.warning(f"参数评估失败: {e}")
            return {
                "params": params,
                "score": -999,
                "win_rate": 0,
                "avg_pnl": 0,
                "max_dd": 1,
                "total_return": 0,
                "sharpe": 0,
                "error": str(e),
            }

    def _get_strategy_class(self):
        """根据策略名称获取策略类"""
        from strategy.ma_cross import MACrossStrategy
        from strategy.rsi import RSIStrategy
        from strategy.macd import MACDStrategy
        from strategy.multi_factor import MultiFactorStrategy

        strategy_map = {
            "ma_cross": MACrossStrategy,
            "rsi": RSIStrategy,
            "macd": MACDStrategy,
            "multi_factor": MultiFactorStrategy,
        }

        # 尝试从策略名称中提取基础名称
        base_name = self.strategy_name.replace("longterm_", "").split("_")[0]
        return strategy_map.get(base_name)

    def _parse_pct(self, value: str) -> float:
        """解析百分比字符串"""
        if isinstance(value, (int, float)):
            return float(value) / 100
        if isinstance(value, str):
            return float(value.replace("%", "")) / 100
        return 0.0

    def optimize(self, data: pd.DataFrame, n_iterations: int = 20) -> dict:
        """
        参数优化
        使用网格搜索 + 遗传算法思想
        """
        logger.info(f"开始参数优化: {self.strategy_name}, {n_iterations} 次迭代")

        best_score = -float("inf")
        best_params = {}
        results = []

        # 生成参数组合
        param_grid = self._generate_grid()
        tested = min(n_iterations, len(param_grid))

        for i in range(tested):
            params = param_grid[i]
            result = self.evaluate_params(params, data)

            # 综合得分
            score = result.get("score", 0)
            if score > best_score:
                best_score = score
                best_params = params

            results.append({"params": params, "score": score})

        self.best_params = best_params
        logger.info(f"最优参数: {best_params} (得分: {best_score:.2f})")
        self._save_memory()

        return {
            "best_params": best_params,
            "best_score": best_score,
            "results": results,
        }

    def adaptive_update(self, recent_trades: list, decay: float = 0.1):
        """
        自适应更新参数
        根据近期交易表现动态调整
        """
        if len(recent_trades) < 5:
            logger.info("交易数据不足，跳过自适应更新")
            return

        wins = sum(1 for t in recent_trades if t.get("result") == "win")
        win_rate = wins / len(recent_trades)

        logger.info(f"近期胜率: {win_rate:.1%} ({wins}/{len(recent_trades)})")

        if win_rate < 0.4:
            logger.warning("胜率过低，建议放宽买入条件或严格止损")
            # 可以自动调整参数
        elif win_rate > 0.7:
            logger.info("胜率良好，可考虑加仓或放宽止盈")

    def suggest_action(self, symbol: str, current_data: dict, context: dict) -> dict:
        """
        基于学习给出操作建议
        Returns: {"action": "buy/sell/hold", "confidence": float, "reason": str}
        """
        # 综合分析：技术指标 + 历史表现 + 市场状态
        price = current_data.get("close", 0)
        history = context.get("history", pd.DataFrame())

        if history.empty or len(history) < 20:
            return {"action": "hold", "confidence": 0, "reason": "数据不足"}

        close = history["close"]
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]

        # 趋势判断
        trend = "up" if ma5 > ma20 else "down"

        # 历史表现
        recent = [t for t in self.trade_history if t.get("symbol") == symbol][-10:]
        recent_wins = sum(1 for t in recent if t.get("result") == "win")
        recent_wr = recent_wins / len(recent) if recent else 0.5

        # 决策
        if trend == "up" and recent_wr > 0.5:
            return {
                "action": "buy",
                "confidence": min(0.9, 0.5 + recent_wr * 0.4),
                "reason": f"趋势向上(MA5>MA20)，历史胜率{recent_wr:.0%}",
            }
        elif trend == "down" and recent_wr < 0.5:
            return {
                "action": "sell",
                "confidence": min(0.9, 0.5 + (1 - recent_wr) * 0.4),
                "reason": f"趋势向下(MA5<MA20)，历史胜率{recent_wr:.0%}",
            }

        return {"action": "hold", "confidence": 0.3, "reason": "信号不明确，观望"}

    def get_learning_stats(self) -> dict:
        """获取学习统计"""
        if not self.trade_history:
            return {"total_trades": 0}

        completed = [t for t in self.trade_history if "result" in t]
        wins = sum(1 for t in completed if t["result"] == "win")

        return {
            "total_trades": len(self.trade_history),
            "completed_trades": len(completed),
            "wins": wins,
            "losses": len(completed) - wins,
            "win_rate": wins / len(completed) if completed else 0,
            "best_params": self.best_params,
            "symbols": list(set(t["symbol"] for t in self.trade_history)),
        }

    def _generate_grid(self) -> list:
        """生成参数网格"""
        grid = [{}]
        for name, space in self.param_space.items():
            new_grid = []
            values = np.arange(space["min"], space["max"] + space["step"], space["step"])
            for g in grid:
                for v in values:
                    new_g = g.copy()
                    new_g[name] = int(v) if isinstance(space.get("min"), int) else round(v, 3)
                    new_grid.append(new_g)
            grid = new_grid
        return grid

    def _load_memory(self):
        """加载记忆"""
        if self.memory_path.exists():
            try:
                with open(self.memory_path, "r") as f:
                    data = json.load(f)
                self.trade_history = data.get("trades", [])
                self.best_params = data.get("best_params", {})
                logger.info(f"加载学习记忆: {len(self.trade_history)} 条交易记录")
            except Exception as e:
                logger.warning(f"加载学习记忆失败: {e}")

    def _save_memory(self):
        """保存记忆"""
        data = {
            "strategy": self.strategy_name,
            "trades": self.trade_history,
            "best_params": self.best_params,
            "last_update": datetime.datetime.now().isoformat(),
        }
        with open(self.memory_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
