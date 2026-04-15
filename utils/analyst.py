"""策略分析与建议模块"""
import pandas as pd
import numpy as np
from loguru import logger
from typing import Optional


class StrategyAnalyst:
    """
    策略分析器：基于回测结果自动诊断问题并给出优化建议
    """

    def __init__(self):
        self.suggestions = []

    def analyze(self, equity_df: pd.DataFrame, trades_df: pd.DataFrame,
                stats: dict, symbol: str = "unknown") -> dict:
        """
        全面分析回测结果
        Returns: {
            "summary": 总体评价,
            "diagnosis": 问题诊断,
            "suggestions": 优化建议列表,
            "score": 策略评分(0-100)
        }
        """
        self.suggestions = []

        # 数据准备
        equity = equity_df.copy()
        equity["date"] = pd.to_datetime(equity["date"])
        equity.set_index("date", inplace=True)

        trades = trades_df.copy()
        if not trades.empty:
            trades["date"] = pd.to_datetime(trades["date"])

        # 1. 基础指标分析
        score = 50  # 基础分
        self._analyze_returns(equity, stats)
        self._analyze_drawdown(equity)
        self._analyze_trades(trades, equity)
        self._analyze_timing(trades)
        self._analyze_risk(equity, stats)

        # 2. 计算综合评分
        score = self._calc_score(stats, equity, trades)

        # 3. 生成总结
        summary = self._generate_summary(stats, score)

        return {
            "symbol": symbol,
            "score": score,
            "summary": summary,
            "diagnosis": self._get_diagnosis(),
            "suggestions": self.suggestions,
            "stats": stats
        }

    def _analyze_returns(self, equity: pd.DataFrame, stats: dict):
        """收益分析"""
        total_return = float(stats.get("总收益率", "0%").replace("%", "")) / 100
        ann_return = float(stats.get("年化收益", "0%").replace("%", "")) / 100

        if total_return < 0:
            self.suggestions.append(
                {"type": "warning", "title": "收益为负",
                 "content": f"总收益率 {total_return:.1%}，策略在当前市场环境下亏损。建议：1) 检查买入信号是否过于频繁 2) 增加过滤条件（如成交量、趋势） 3) 考虑空仓期"}
            )
        elif total_return < 0.05:
            self.suggestions.append(
                {"type": "info", "title": "收益偏低",
                 "content": f"总收益率 {total_return:.1%}，勉强跑赢无风险利率。建议优化持仓时间或调整均线参数"}
            )
        else:
            self.suggestions.append(
                {"type": "success", "title": "收益良好",
                 "content": f"总收益率 {total_return:.1%}，策略表现不错"}
            )

    def _analyze_drawdown(self, equity: pd.DataFrame):
        """回撤分析"""
        peak = equity["equity"].cummax()
        drawdown = (equity["equity"] - peak) / peak
        max_dd = drawdown.min()

        if max_dd < -0.20:
            self.suggestions.append(
                {"type": "critical", "title": "最大回撤过大",
                 "content": f"最大回撤 {max_dd:.1%}，超过20%警戒线。建议：1) 降低单票仓位 2) 增加止损条件 3) 加入市场择时（如大盘跌破20日线空仓）"}
            )
        elif max_dd < -0.10:
            self.suggestions.append(
                {"type": "warning", "title": "回撤偏高",
                 "content": f"最大回撤 {max_dd:.1%}，建议优化出场逻辑或加入移动止损"}
            )

    def _analyze_trades(self, trades: pd.DataFrame, equity: pd.DataFrame):
        """交易行为分析"""
        if trades.empty or len(trades) < 4:
            self.suggestions.append(
                {"type": "warning", "title": "交易次数过少",
                 "content": f"仅 {len(trades)} 次交易，统计意义不足。建议拉长回测周期（至少2年）或调整信号参数"}
            )
            return

        buys = trades[trades["action"] == "buy"]
        sells = trades[trades["action"] == "sell"]

        # 胜率分析
        if len(buys) == len(sells):
            wins = sum(1 for b, s in zip(buys["price"], sells["price"]) if s > b)
            win_rate = wins / len(buys)

            if win_rate < 0.40:
                self.suggestions.append(
                    {"type": "critical", "title": "胜率过低",
                     "content": f"胜率仅 {win_rate:.0%}，低于40%。建议：1) 优化买入信号（增加确认条件） 2) 严格止损 3) 考虑趋势过滤"}
                )
            elif win_rate < 0.50:
                self.suggestions.append(
                    {"type": "warning", "title": "胜率偏低",
                     "content": f"胜率 {win_rate:.0%}，建议增加信号过滤条件（如MACD、RSI共振）"}
                )

            # 盈亏比分析
            profits = []
            for (_, b), (_, s) in zip(buys.iterrows(), sells.iterrows()):
                pnl = (s["price"] - b["price"]) / b["price"]
                profits.append(pnl)
            avg_win = np.mean([p for p in profits if p > 0]) if any(p > 0 for p in profits) else 0
            avg_loss = np.mean([p for p in profits if p < 0]) if any(p < 0 for p in profits) else -0.01
            profit_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            if profit_ratio < 1.5:
                self.suggestions.append(
                    {"type": "warning", "title": "盈亏比不佳",
                     "content": f"盈亏比 {profit_ratio:.1f}，建议：1) 让利润奔跑（延迟卖出） 2) 快速止损（严格止损） 3) 目标盈亏比 > 2.0"}
                )

        # 交易频率
        if not trades.empty:
            date_range = (trades["date"].max() - trades["date"].min()).days
            if date_range > 0:
                trades_per_month = len(buys) / (date_range / 30)
                if trades_per_month > 10:
                    self.suggestions.append(
                        {"type": "warning", "title": "交易过于频繁",
                         "content": f"月均交易 {trades_per_month:.1f} 次，手续费侵蚀利润。建议：1) 拉长信号周期 2) 增加持仓时间要求 3) 过滤震荡市"}
                    )
                elif trades_per_month < 0.5:
                    self.suggestions.append(
                        {"type": "info", "title": "交易频率偏低",
                         "content": f"月均交易 {trades_per_month:.1f} 次，资金利用率不足。可适当放宽信号条件"}
                    )

    def _analyze_timing(self, trades: pd.DataFrame):
        """持仓时间分析"""
        if len(trades) < 4:
            return

        buys = trades[trades["action"] == "buy"].reset_index(drop=True)
        sells = trades[trades["action"] == "sell"].reset_index(drop=True)

        if len(buys) == len(sells):
            hold_times = []
            for (_, b), (_, s) in zip(buys.iterrows(), sells.iterrows()):
                days = (s["date"] - b["date"]).days
                hold_times.append(days)

            avg_hold = np.mean(hold_times)
            if avg_hold < 5:
                self.suggestions.append(
                    {"type": "info", "title": "持仓时间过短",
                     "content": f"平均持仓 {avg_hold:.0f} 天，T+1限制下手续费占比高。建议：1) 改用日线以上周期 2) 增加最小持仓天数过滤"}
                )
            elif avg_hold > 60:
                self.suggestions.append(
                    {"type": "info", "title": "持仓时间过长",
                     "content": f"平均持仓 {avg_hold:.0f} 天，建议：1) 检查卖出信号是否滞后 2) 增加趋势反转过滤"}
                )

    def _analyze_risk(self, equity: pd.DataFrame, stats: dict):
        """风险指标分析"""
        sharpe = float(stats.get("夏普比率", "0"))
        if sharpe < 0:
            self.suggestions.append(
                {"type": "critical", "title": "夏普比率为负",
                 "content": f"夏普比率 {sharpe:.2f}，风险调整后收益为负。策略不如持有现金，需全面优化信号逻辑"}
            )
        elif sharpe < 0.5:
            self.suggestions.append(
                {"type": "warning", "title": "夏普比率偏低",
                 "content": f"夏普比率 {sharpe:.2f}，建议优化收益波动比。可考虑：1) 降低仓位 2) 增加对冲 3) 优化进出场时机"}
            )
        elif sharpe > 1.5:
            self.suggestions.append(
                {"type": "success", "title": "夏普比率优秀",
                 "content": f"夏普比率 {sharpe:.2f}，风险调整后收益良好。建议：1) 检查是否过拟合 2) 做样本外验证"}
            )

    def _calc_score(self, stats: dict, equity: pd.DataFrame, trades: pd.DataFrame) -> int:
        """计算策略综合评分 (0-100)"""
        score = 50

        # 收益分 (±20)
        total_ret = float(stats.get("总收益率", "0%").replace("%", "")) / 100
        score += min(max(total_ret * 100, -20), 20)

        # 回撤分 (±15)
        max_dd = float(stats.get("最大回撤", "0%").replace("%", "")) / 100
        score += min(max(max_dd * 50, -15), 5)  # 回撤越小越好

        # 夏普分 (±15)
        sharpe = float(stats.get("夏普比率", "0"))
        score += min(max(sharpe * 10, -15), 15)

        # 交易质量分 (±10)
        if not trades.empty:
            buys = trades[trades["action"] == "buy"]
            sells = trades[trades["action"] == "sell"]
            if len(buys) == len(sells) and len(buys) > 0:
                wins = sum(1 for b, s in zip(buys["price"], sells["price"]) if s > b)
                win_rate = wins / len(buys)
                score += (win_rate - 0.5) * 20

        return max(0, min(100, int(score)))

    def _generate_summary(self, stats: dict, score: int) -> str:
        if score >= 75:
            return "策略表现优秀，建议进行样本外验证和实盘模拟"
        elif score >= 60:
            return "策略可用但需优化，建议调整参数或增加过滤条件"
        elif score >= 45:
            return "策略表现一般，需重点优化信号逻辑和风控"
        else:
            return "策略表现不佳，建议重新设计或更换策略框架"

    def _get_diagnosis(self) -> list:
        return [s for s in self.suggestions if s["type"] in ("warning", "critical")]

    def print_report(self, report: dict):
        """打印分析报告"""
        logger.info("\n" + "=" * 50)
        logger.info(f"策略分析报告 - {report['symbol']}")
        logger.info("=" * 50)
        logger.info(f"综合评分: {report['score']}/100")
        logger.info(f"总体评价: {report['summary']}")
        logger.info("")

        # 诊断问题
        if report["diagnosis"]:
            logger.warning("--- 问题诊断 ---")
            for d in report["diagnosis"]:
                logger.warning(f"[{d['title']}] {d['content']}")
            logger.info("")

        # 优化建议
        logger.info("--- 优化建议 ---")
        for s in report["suggestions"]:
            icon = {"success": "[+]", "warning": "[!]", "critical": "[X]", "info": "[i]"}.get(s["type"], "[ ]")
            logger.info(f"{icon} {s['title']}: {s['content']}")

        logger.info("=" * 50)
