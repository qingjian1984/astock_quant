"""交易限制器"""
from datetime import datetime, timedelta
from loguru import logger
import config


class TradeLimiter:
    """
    交易限制管理器
    控制：每日次数、单笔金额、单笔股数、交易间隔、每日总额
    """

    def __init__(self, custom_limits: dict = None):
        self.limits = config.DAILY_LIMITS.copy()
        if custom_limits:
            self.limits.update(custom_limits)

        # 当日统计
        self.today = datetime.now().date()
        self.trade_count = 0
        self.daily_buy_amount = 0
        self.daily_sell_amount = 0
        self.last_trade_time = None

    def reset_daily(self):
        """重置当日统计"""
        today = datetime.now().date()
        if today != self.today:
            logger.info(f"新交易日: {today}，重置限制统计")
            self.today = today
            self.trade_count = 0
            self.daily_buy_amount = 0
            self.daily_sell_amount = 0
            self.last_trade_time = None

    def check_trade(self, symbol: str, action: str, price: float, volume: int) -> tuple:
        """
        检查交易是否被允许
        Returns: (allowed: bool, reason: str)
        """
        self.reset_daily()

        # 1. 每日交易次数
        if self.trade_count >= self.limits["max_trades_per_day"]:
            return False, f"已达每日最大交易次数 {self.limits['max_trades_per_day']}"

        # 2. 交易间隔
        if self.last_trade_time:
            elapsed = (datetime.now() - self.last_trade_time).total_seconds()
            if elapsed < self.limits["min_trade_interval"]:
                remaining = self.limits["min_trade_interval"] - elapsed
                return False, f"交易间隔不足，还需等待 {remaining:.0f} 秒"

        # 3. 单笔金额
        amount = price * volume
        if amount > self.limits["max_amount_per_trade"]:
            return False, f"单笔金额 {amount:,.0f} 超过上限 {self.limits['max_amount_per_trade']:,.0f}"

        # 4. 单笔股数
        if volume > self.limits["max_volume_per_trade"]:
            return False, f"单笔股数 {volume} 超过上限 {self.limits['max_volume_per_trade']}"

        # 5. 每日交易总额
        total_daily = self.daily_buy_amount + self.daily_sell_amount + amount
        if total_daily > self.limits["max_daily_amount"]:
            return False, f"每日交易总额将达 {total_daily:,.0f}，超过上限 {self.limits['max_daily_amount']:,.0f}"

        # 6. 每日买入金额
        if action == "buy":
            if self.daily_buy_amount + amount > self.limits["max_daily_buy_amount"]:
                return False, f"每日买入金额将达 {self.daily_buy_amount + amount:,.0f}，超过上限 {self.limits['max_daily_buy_amount']:,.0f}"

        # 7. 每日卖出金额
        if action == "sell":
            if self.daily_sell_amount + amount > self.limits["max_daily_sell_amount"]:
                return False, f"每日卖出金额将达 {self.daily_sell_amount + amount:,.0f}，超过上限 {self.limits['max_daily_sell_amount']:,.0f}"

        return True, "通过限制检查"

    def record_trade(self, action: str, amount: float):
        """记录一次交易"""
        self.trade_count += 1
        self.last_trade_time = datetime.now()
        if action == "buy":
            self.daily_buy_amount += amount
        elif action == "sell":
            self.daily_sell_amount += amount

    def get_status(self) -> dict:
        """获取当前限制状态"""
        return {
            "今日交易次数": f"{self.trade_count}/{self.limits['max_trades_per_day']}",
            "今日买入金额": f"{self.daily_buy_amount:,.0f}/{self.limits['max_daily_buy_amount']:,.0f}",
            "今日卖出金额": f"{self.daily_sell_amount:,.0f}/{self.limits['max_daily_sell_amount']:,.0f}",
            "单笔最大金额": f"{self.limits['max_amount_per_trade']:,.0f}",
            "单笔最大股数": f"{self.limits['max_volume_per_trade']}",
            "最小交易间隔": f"{self.limits['min_trade_interval']}秒",
            "距上次交易": f"{(datetime.now() - self.last_trade_time).total_seconds():.0f}秒" if self.last_trade_time else "无",
        }
