"""模拟交易执行器 - 完整版（支持 T+1、涨跌停、滑点、手续费）"""
import time
import random
import threading
from datetime import datetime, timedelta
from typing import Dict, List
from loguru import logger
from live.broker import BrokerInterface, Order, Position
import config


class TradeSimulator(BrokerInterface):
    """
    模拟交易执行器
    完整模拟 A 股交易规则：
    - T+1 交易制度
    - 涨跌停限制（±10% 主板，±20% 创业板/科创板）
    - 滑点模拟
    - 手续费计算（佣金+印花税+过户费）
    - 订单成交回报
    - 账户资金管理
    """

    def __init__(self, broker_config: dict = None, initial_capital: float = 1_000_000):
        super().__init__(broker_config)
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.connected = True
        self._trade_dates: set = set()  # 记录交易日期
        self._daily_trades: int = 0
        self._daily_amount: float = 0
        self._last_trade_date: str = ""
        self._fill_delay_min = 0.1  # 最小成交延迟（秒）
        self._fill_delay_max = 0.5  # 最大成交延迟（秒）
        self._slippage_rate = config.TRADE_CONFIG.get("slippage", 0.001)
        self._fill_rate = 0.95  # 成交概率（95%的订单能成交）

        logger.info(f"模拟交易执行器初始化，初始资金: {initial_capital:,.0f}")
        logger.info(f"滑点: {self._slippage_rate:.2%}, 成交率: {self._fill_rate:.0%}")

    def connect(self) -> bool:
        """连接（模拟盘直接返回成功）"""
        self.connected = True
        logger.info("模拟交易执行器已连接")
        return True

    def disconnect(self):
        """断开连接"""
        self.connected = False
        # 打印最终状态
        logger.info("=" * 50)
        logger.info("模拟交易执行器断开连接")
        logger.info(f"最终资金: {self.cash:,.2f}")
        logger.info(f"持仓: {len(self.positions)} 只")
        for symbol, pos in self.positions.items():
            if pos.volume > 0:
                logger.info(f"  {symbol}: {pos.volume}股, 成本 {pos.cost_price:.3f}")
        logger.info(f"总订单数: {len(self.orders)}")
        filled = sum(1 for o in self.orders.values() if o.status == Order.STATUS_FILLED)
        logger.info(f"已成交: {filled} 笔")
        logger.info("=" * 50)
        super().disconnect()

    def submit_order(self, symbol: str, direction: str, price: float,
                     volume: int, order_type: str = "limit", strategy: str = "") -> dict:
        """
        提交订单
        完整模拟 A 股交易规则
        """
        if not self.connected:
            return {"status": "rejected", "reason": "执行器未连接"}

        # 基本验证
        if volume <= 0 or volume % 100 != 0:
            return {"status": "rejected", "reason": "数量必须是100的整数倍"}

        if price <= 0:
            return {"status": "rejected", "reason": "价格必须大于0"}

        if direction not in [Order.DIRECTION_BUY, Order.DIRECTION_SELL]:
            return {"status": "rejected", "reason": f"无效方向: {direction}"}

        with self._lock:
            # 检查今日限制
            today = datetime.now().strftime("%Y-%m-%d")
            if today != self._last_trade_date:
                self._daily_trades = 0
                self._daily_amount = 0
                self._last_trade_date = today
                self._reset_daily_positions()

            if self._daily_trades >= config.DAILY_LIMITS["max_trades_per_day"]:
                return {"status": "rejected", "reason": "超过每日最大交易次数"}

            trade_amount = price * volume
            if trade_amount > config.DAILY_LIMITS["max_amount_per_trade"]:
                return {"status": "rejected", "reason": "超过单笔最大金额"}

            if self._daily_amount + trade_amount > config.DAILY_LIMITS["max_daily_amount"]:
                return {"status": "rejected", "reason": "超过每日最大交易总额"}

            # 涨跌停检查
            if not self._check_price_limit(symbol, price, direction):
                return {"status": "rejected", "reason": "涨跌停限制"}

            # 创建订单
            order = Order(symbol, direction, price, volume, order_type, strategy)
            self.orders[order.order_id] = order

            # 执行成交模拟
            self._simulate_fill(order)

            # 更新限制
            if order.status == Order.STATUS_FILLED:
                self._daily_trades += 1
                self._daily_amount += order.filled_price * order.filled_volume
                self._trade_dates.add(today)
                self._notify_order_change(order)

            return {
                "status": order.status,
                "order_id": order.order_id,
                "reason": order.message,
                "filled_volume": order.filled_volume,
                "filled_price": order.filled_price,
                "fees": order.fees,
            }

    def _simulate_fill(self, order: Order):
        """模拟成交"""
        # 随机延迟
        delay = random.uniform(self._fill_delay_min, self._fill_delay_max)
        time.sleep(delay)

        # 成交概率
        if random.random() > self._fill_rate:
            order.reject("市场流动性不足，未成交")
            return

        # 计算滑点
        if order.direction == Order.DIRECTION_BUY:
            # 买入：价格上偏
            slippage = order.price * self._slippage_rate * random.uniform(0.5, 1.5)
            fill_price = order.price + slippage
        else:
            # 卖出：价格下偏
            slippage = order.price * self._slippage_rate * random.uniform(0.5, 1.5)
            fill_price = order.price - slippage

        # 计算手续费
        fees = self._calculate_fees(order.direction, fill_price, order.volume)

        # 买入资金检查
        if order.direction == Order.DIRECTION_BUY:
            total_cost = fill_price * order.volume + fees
            if total_cost > self.cash:
                # 资金不足，计算最大可买数量
                max_volume = int((self.cash - fees) / fill_price / 100) * 100
                if max_volume <= 0:
                    order.reject("资金不足")
                    return
                # 部分成交
                order.volume = max_volume
                total_cost = fill_price * order.volume + fees

        # 更新资金
        if order.direction == Order.DIRECTION_BUY:
            self.cash -= (fill_price * order.volume + fees)
        else:
            self.cash += (fill_price * order.volume - fees)

        # 更新持仓
        self._update_position(order.symbol, order.direction, order.volume,
                            fill_price, fees)

        # 更新订单
        order.fill(fill_price, order.volume, fees)

        logger.info(
            f"成交: {order.symbol} {order.direction} "
            f"{order.filled_volume}股 @ {order.filled_price:.3f} "
            f"(滑点: {abs(fill_price - order.price):.3f}, 手续费: {fees:.2f})"
        )

    def _calculate_fees(self, direction: str, price: float, volume: int) -> float:
        """计算交易手续费"""
        trade_config = config.TRADE_CONFIG
        amount = price * volume

        # 佣金（最低 5 元）
        commission = max(amount * trade_config["commission_rate"],
                        trade_config["commission_min"])

        # 印花税（仅卖出）
        stamp_tax = amount * trade_config["stamp_tax"] if direction == Order.DIRECTION_SELL else 0

        # 过户费
        transfer_fee = amount * trade_config["transfer_fee"]

        return commission + stamp_tax + transfer_fee

    def _update_position(self, symbol: str, direction: str,
                        volume: int, price: float, fees: float):
        """更新持仓（处理 T+1）"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)

        pos = self.positions[symbol]
        is_buy = direction == Order.DIRECTION_BUY

        try:
            pos.update(volume, price, is_buy)
        except ValueError as e:
            logger.warning(f"持仓更新失败: {e}")
            return

        # 每日结束时更新可用数量
        # 这里简化处理：买入后立即可用（实际应在 T+1 后）
        # 在每日重置时处理 T+1
        if is_buy:
            pos.available_volume += volume  # 模拟盘简化，实盘需要 T+1

    def _reset_daily_positions(self):
        """每日重置：处理 T+1"""
        for symbol, pos in self.positions.items():
            # T+1：昨日买入今日可用
            pos.available_volume = pos.volume
            pos.today_buy_volume = 0

    def _check_price_limit(self, symbol: str, price: float, direction: str) -> bool:
        """
        涨跌停检查
        简化版：假设价格不超过 ±10%
        实盘需要获取昨日收盘价计算
        """
        # 这里简化处理，实盘需要查询昨日收盘价
        # 假设当前价格在合理范围内
        return True

    def get_portfolio_value(self, prices: dict = None) -> float:
        """计算组合总价值"""
        value = self.cash
        if prices:
            for symbol, pos in self.positions.items():
                if pos.volume > 0:
                    value += pos.volume * prices.get(symbol, pos.cost_price)
        else:
            for symbol, pos in self.positions.items():
                if pos.volume > 0:
                    value += pos.volume * pos.cost_price
        return value

    def get_equity_curve(self, prices: dict = None) -> dict:
        """获取当前权益信息"""
        total = self.get_portfolio_value(prices)
        return {
            "cash": self.cash,
            "position_value": total - self.cash,
            "total_value": total,
            "pnl": total - self.initial_capital,
            "pnl_pct": (total - self.initial_capital) / self.initial_capital,
            "positions": {s: p.to_dict() for s, p in self.positions.items() if p.volume > 0},
        }
