"""风控模块"""
from loguru import logger
import config


class RiskManager:
    """A股风控管理器"""

    def __init__(self):
        self.cfg = config.RISK_CONFIG
        self.total_capital = 1000000.0
        self.peak_value = self.total_capital
        self.max_drawdown = 0.0
        self.paused = False

    def check_buy(self, symbol: str, volume: int, price: float,
                  position: int, cash: float, total_value: float) -> tuple:
        """
        检查买入是否合规
        Returns: (allowed: bool, adjusted_volume: int, reason: str)
        """
        # 黑名单
        if symbol in self.cfg["blacklist"]:
            return False, 0, f"股票 {symbol} 在黑名单中"

        # 单票仓位限制
        order_value = volume * price
        position_value = position * price
        if position_value + order_value > total_value * self.cfg["max_position_pct"]:
            max_vol = int(total_value * self.cfg["max_position_pct"] / price / 100) * 100
            adjusted = max_vol - position
            if adjusted <= 0:
                return False, 0, f"{symbol} 仓位已达上限"
            return True, adjusted, f"仓位调整至 {adjusted} 股"

        # 总仓位限制
        if total_value / self.total_capital > self.cfg["max_total_position"]:
            return False, 0, "总仓位已达上限"

        # 最大回撤暂停
        if total_value > self.peak_value:
            self.peak_value = total_value
        dd = (total_value - self.peak_value) / self.peak_value
        self.max_drawdown = dd
        if dd < self.cfg["max_drawdown_pct"]:
            self.paused = True
            return False, 0, f"触发最大回撤 {dd:.2%}，暂停交易"

        return True, volume, "通过风控检查"

    def check_sell(self, symbol: str, volume: int, price: float,
                   cost_price: float) -> tuple:
        """
        检查止损止盈
        Returns: (should_sell: bool, reason: str)
        """
        if cost_price <= 0:
            return False, ""

        pnl_pct = (price - cost_price) / cost_price

        if pnl_pct <= self.cfg["stop_loss_pct"]:
            return True, f"止损: {symbol} 亏损 {pnl_pct:.2%}"

        if pnl_pct >= self.cfg["take_profit_pct"]:
            return True, f"止盈: {symbol} 盈利 {pnl_pct:.2%}"

        return False, ""

    def check_drawdown(self, current_value: float, peak_value: float) -> float:
        """
        检查回撤
        Returns: 回撤比例（负值表示下跌）
        """
        if peak_value <= 0:
            return 0.0
        dd = (current_value - peak_value) / peak_value
        self.max_drawdown = min(self.max_drawdown, dd)
        if dd < self.cfg["max_drawdown_pct"]:
            self.paused = True
        return dd

    def calculate_fees(self, price: float, volume: int, is_sell: bool) -> dict:
        """计算A股交易费用"""
        tc = config.TRADE_CONFIG
        amount = price * volume

        commission = max(amount * tc["commission_rate"], tc["commission_min"])
        stamp_tax = amount * tc["stamp_tax"] if is_sell else 0.0
        transfer = amount * tc["transfer_fee"]
        total = commission + stamp_tax + transfer

        return {
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "transfer_fee": round(transfer, 2),
            "total": round(total, 2),
        }
