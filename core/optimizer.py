"""策略优化器"""
import pandas as pd
from loguru import logger
from backtest.engine import BacktestEngine
from strategy.ma_cross import MACrossStrategy
from strategy.rsi import RSIStrategy
from strategy.macd import MACDStrategy


STRATEGY_LIBRARY = {
    "ma_cross": {"class": MACrossStrategy, "params": {"fast": [3, 5, 7, 10], "slow": [15, 20, 25, 30]}},
    "rsi": {"class": RSIStrategy, "params": {"period": [10, 14, 18, 21]}},
    "macd": {"class": MACDStrategy, "params": {"fast": [8, 10, 12], "slow": [21, 26], "signal": [5, 7, 9]}},
}


class StrategyOptimizer:
    """
    策略优化器
    为特定股票回测多个策略，找到盈利最强的那个
    """

    def __init__(self):
        self.results = []

    def optimize(self, symbol: str, data: pd.DataFrame, strategy_names: list = None, capital: float = 100000) -> dict:
        """
        为指定股票寻找最优策略
        Returns: {"strategy": str, "params": dict, "score": float, "stats": dict}
        """
        if strategy_names is None:
            strategy_names = list(STRATEGY_LIBRARY.keys())

        logger.info(f"开始优化 {symbol}，测试 {len(strategy_names)} 个策略...")
        best_result = {"strategy": None, "score": -999, "params": {}, "stats": {}}

        for s_name in strategy_names:
            s_info = STRATEGY_LIBRARY[s_name]
            s_class = s_info["class"]
            param_space = s_info["params"]

            # 网格搜索
            param_combos = self._generate_combos(param_space)
            logger.info(f"  [{s_name}] 测试 {len(param_combos)} 组参数")

            for params in param_combos:
                try:
                    strat = s_class(**params)
                    engine = BacktestEngine(strat, initial_capital=capital)
                    stats = engine.run(data, symbol=symbol)

                    # 计算评分：收益*0.6 + (1-回撤)*0.2 + 夏普*0.2
                    score = self._calc_score(stats)

                    if score > best_result["score"]:
                        best_result = {
                            "strategy": s_name,
                            "params": params,
                            "score": score,
                            "stats": stats
                        }
                except Exception as e:
                    logger.warning(f"  回测失败 {s_name} {params}: {e}")

        logger.info(f"最优策略: {best_result['strategy']} {best_result['params']} (得分: {best_result['score']:.2f})")
        return best_result

    def _calc_score(self, stats: dict) -> float:
        """计算策略评分"""
        ret = float(stats.get("总收益率", "0%").replace("%", "")) / 100
        dd = abs(float(stats.get("最大回撤", "0%").replace("%", "")) / 100)
        sharpe = float(stats.get("夏普比率", "0"))

        return ret * 60 + (1 - dd) * 20 + max(sharpe, 0) * 20

    def _generate_combos(self, param_space: dict) -> list:
        """生成参数组合"""
        if not param_space:
            return [{}]
        keys = list(param_space.keys())
        combos = [{}]
        for key in keys:
            new_combos = []
            for c in combos:
                for val in param_space[key]:
                    new_c = c.copy()
                    new_c[key] = val
                    new_combos.append(new_c)
            combos = new_combos
        return combos
