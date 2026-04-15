"""券商交易接口 - 完整版（模拟盘+实盘预留）"""
import uuid
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import config


class Order:
    """订单对象"""
    STATUS_PENDING = "pending"
    STATUS_FILLED = "filled"
    STATUS_PARTIAL = "partial"
    STATUS_CANCELLED = "cancelled"
    STATUS_REJECTED = "rejected"

    DIRECTION_BUY = "buy"
    DIRECTION_SELL = "sell"

    def __init__(self, symbol: str, direction: str, price: float, volume: int,
                 order_type: str = "limit", strategy: str = ""):
        self.order_id = str(uuid.uuid4())[:8]
        self.symbol = symbol
        self.direction = direction
        self.price = price
        self.volume = volume
        self.filled_volume = 0
        self.filled_price = 0.0
        self.status = self.STATUS_PENDING
        self.order_type = order_type
        self.strategy = strategy
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.filled_at = None
        self.cancelled_at = None
        self.fees = 0.0
        self.message = ""

    def fill(self, fill_price: float, fill_volume: int, fees: float = 0):
        """成交"""
        self.filled_volume += fill_volume
        self.filled_price = (self.filled_price * (self.filled_volume - fill_volume) +
                           fill_price * fill_volume) / self.filled_volume if self.filled_volume > 0 else fill_price
        self.fees += fees
        self.status = self.STATUS_FILLED if self.filled_volume >= self.volume else self.STATUS_PARTIAL
        self.updated_at = datetime.now()
        if self.status == self.STATUS_FILLED:
            self.filled_at = datetime.now()

    def cancel(self):
        """撤单"""
        self.status = self.STATUS_CANCELLED
        self.cancelled_at = datetime.now()
        self.updated_at = datetime.now()

    def reject(self, reason: str):
        """拒单"""
        self.status = self.STATUS_REJECTED
        self.message = reason
        self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "price": self.price,
            "volume": self.volume,
            "filled_volume": self.filled_volume,
            "filled_price": self.filled_price,
            "status": self.status,
            "order_type": self.order_type,
            "strategy": self.strategy,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "fees": self.fees,
            "message": self.message,
        }


class Position:
    """持仓对象"""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.volume = 0
        self.available_volume = 0  # T+1 可用数量
        self.cost_price = 0.0
        self.total_cost = 0.0
        self.today_buy_volume = 0  # 今日买入（T+1 限制）
        self.last_update = datetime.now()

    def update(self, volume: int, price: float, is_buy: bool, is_today: bool = True):
        """更新持仓"""
        if is_buy:
            self.total_cost += volume * price
            self.volume += volume
            if is_today:
                self.today_buy_volume += volume
            # 重新计算成本价
            if self.volume > 0:
                self.cost_price = self.total_cost / self.volume
        else:
            sell_volume = min(volume, self.available_volume)
            if sell_volume <= 0:
                raise ValueError(f"{self.symbol} 无可卖持仓（T+1 限制）")
            self.volume -= sell_volume
            self.total_cost -= sell_volume * self.cost_price
            if self.volume == 0:
                self.cost_price = 0.0
                self.total_cost = 0.0
                self.today_buy_volume = 0
        self.last_update = datetime.now()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "volume": self.volume,
            "available_volume": self.available_volume,
            "cost_price": self.cost_price,
            "total_cost": self.total_cost,
            "today_buy_volume": self.today_buy_volume,
            "last_update": self.last_update.isoformat(),
        }


class BrokerInterface:
    """
    券商交易接口基类
    实盘时继承此类实现真实券商API
    """

    def __init__(self, broker_config: dict = None):
        self.config = broker_config or config.BROKER_CONFIG
        self.connected = False
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.cash = 1_000_000.0
        self._lock = threading.Lock()
        self._order_callbacks = []

    def connect(self) -> bool:
        """连接券商（子类实现）"""
        raise NotImplementedError

    def disconnect(self):
        """断开连接"""
        self.connected = False
        logger.info("已断开券商连接")

    def submit_order(self, symbol: str, direction: str, price: float,
                     volume: int, order_type: str = "limit", strategy: str = "") -> dict:
        """
        提交订单
        Returns: {"status": str, "order_id": str, "reason": str}
        """
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        with self._lock:
            order = self.orders.get(order_id)
            if not order:
                return False
            if order.status in [Order.STATUS_PENDING, Order.STATUS_PARTIAL]:
                order.cancel()
                logger.info(f"撤单成功: {order_id}")
                return True
            return False

    def query_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        return self.orders.get(order_id)

    def query_orders(self, symbol: str = None, status: str = None) -> List[Order]:
        """查询订单列表"""
        orders = list(self.orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        if status:
            orders = [o for o in orders if o.status == status]
        return orders

    def query_position(self, symbol: str) -> int:
        """查询持仓"""
        pos = self.positions.get(symbol)
        return pos.available_volume if pos else 0

    def query_all_positions(self) -> Dict[str, Position]:
        """查询所有持仓"""
        return self.positions.copy()

    def query_cash(self) -> float:
        """查询可用资金"""
        return self.cash

    def get_portfolio_value(self, prices: dict) -> float:
        """计算组合总价值"""
        value = self.cash
        for symbol, pos in self.positions.items():
            if pos.volume > 0:
                value += pos.volume * prices.get(symbol, pos.cost_price)
        return value

    def add_order_callback(self, callback):
        """添加订单状态变化回调"""
        self._order_callbacks.append(callback)

    def _notify_order_change(self, order: Order):
        """通知订单状态变化"""
        for callback in self._order_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.error(f"订单回调异常: {e}")


class VnpyBroker(BrokerInterface):
    """
    vnpy 实盘券商接口（预留）
    需要安装: pip install vnpy vnpy-ctp
    配置示例:
        BROKER_CONFIG = {
            "gateway": "CTP",
            "user_id": "你的账号",
            "password": "你的密码",
            "broker_id": "经纪商代码",
            "td_address": "前置地址",
        }
    """

    def __init__(self, broker_config: dict = None):
        super().__init__(broker_config)
        self.engine = None
        self.gateway = None
        self._vt_gateway = None
        logger.warning("vnpy 实盘接口需要安装 vnpy 并配置券商信息")

    def connect(self) -> bool:
        """连接券商"""
        try:
            # 实际对接示例（需要取消注释并配置）:
            # from vnpy.event import EventEngine
            # from vnpy.trader.engine import MainEngine
            # from vnpy_ctp import CtpGateway
            #
            # self.engine = MainEngine(EventEngine())
            # self.gateway = self.engine.add_gateway(CtpGateway)
            #
            # gateway_setting = {
            #     "用户名": self.config["vnpy"]["user_id"],
            #     "密码": self.config["vnpy"]["password"],
            #     "经纪商代码": self.config["vnpy"]["broker_id"],
            #     "交易服务器": self.config["vnpy"]["td_address"],
            # }
            # self.gateway.connect(gateway_setting)
            # self.connected = True
            #
            # logger.info("vnpy 券商连接成功")
            # return True

            logger.warning("vnpy 实盘接口未激活，请安装 vnpy 并配置券商信息")
            self.connected = False
            return False

        except ImportError:
            logger.error("vnpy 未安装，请运行: pip install vnpy vnpy-ctp")
            self.connected = False
            return False
        except Exception as e:
            logger.error(f"vnpy 连接失败: {e}")
            self.connected = False
            return False

    def submit_order(self, symbol: str, direction: str, price: float,
                     volume: int, order_type: str = "limit", strategy: str = "") -> dict:
        """提交订单（实盘）"""
        if not self.connected:
            return {"status": "rejected", "reason": "券商未连接"}

        # 实际下单示例:
        # from vnpy.trader.constant import Direction, Offset, OrderType
        # from vnpy.trader.object import OrderRequest
        # from vnpy.trader.constant import Exchange
        #
        # # 判断交易所
        # exchange = Exchange.SSE if symbol.startswith("6") else Exchange.SZSE
        #
        # req = OrderRequest(
        #     symbol=symbol,
        #     exchange=exchange,
        #     direction=Direction.LONG if direction == "buy" else Direction.SHORT,
        #     offset=Offset.OPEN,
        #     type=OrderType.LIMIT if order_type == "limit" else OrderType.MARKET,
        #     price=price,
        #     volume=volume,
        #     reference=strategy,
        # )
        #
        # vt_orderid = self.engine.send_order(req, self._vt_gateway)
        #
        # if vt_orderid:
        #     return {"status": "pending", "order_id": vt_orderid}
        # else:
        #     return {"status": "rejected", "reason": "下单失败"}

        return {"status": "rejected", "reason": "vnpy 实盘接口未激活"}

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单（实盘）"""
        if not self.connected:
            return False

        # 实际撤单示例:
        # from vnpy.trader.object import CancelRequest
        # from vnpy.trader.constant import Exchange
        #
        # # 需要根据订单信息查询交易所
        # req = CancelRequest(
        #     symbol=order.symbol,
        #     exchange=exchange,
        #     orderid=order_id,
        # )
        # self.engine.cancel_order(req)
        # return True

        return False

    def query_position(self, symbol: str) -> int:
        """查询持仓（实盘）"""
        # 实际查询示例:
        # positions = self.engine.main_engine.get_all_positions()
        # for pos in positions:
        #     if pos.symbol == symbol:
        #         return pos.volume
        return 0

    def query_cash(self) -> float:
        """查询可用资金（实盘）"""
        # accounts = self.engine.main_engine.get_all_accounts()
        # for acc in accounts:
        #     return acc.available
        return 0.0
