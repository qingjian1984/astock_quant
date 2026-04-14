"""券商交易接口"""
from loguru import logger
import config


class BrokerInterface:
    """
    券商交易接口
    实盘时替换为真实券商API
    """

    def __init__(self, broker_config: dict = None):
        self.config = broker_config or config.BROKER_CONFIG
        self.connected = False
        self.cash = 1_000_000
        self.positions = {}
        self.orders = []

    def connect(self) -> bool:
        """连接券商"""
        logger.info(f"连接券商: {self.config.get('gateway', 'unknown')}")
        # 实盘对接示例:
        # from vnpy.trader.engine import MainEngine
        # from vnpy_ctp import CtpGateway
        # self.engine = MainEngine(EventEngine())
        # self.engine.add_gateway(CtpGateway)
        # self.engine.connect(self.config["vnpy"])
        # self.connected = True

        logger.warning("当前为模拟模式，未连接真实券商")
        self.connected = False
        return False

    def order(self, symbol: str, direction: str, price: float, volume: int) -> dict:
        """下单"""
        if not self.connected:
            return {"status": "rejected", "reason": "券商未连接"}

        # 实盘下单示例:
        # from vnpy.trader.constant import Direction, Offset
        # req = OrderRequest(
        #     symbol=symbol,
        #     exchange=Exchange.SSE,
        #     direction=Direction.LONG if direction == "buy" else Direction.SHORT,
        #     offset=Offset.OPEN,
        #     type=OrderType.LIMIT,
        #     price=price,
        #     volume=volume,
        # )
        # vt_orderid = self.engine.send_order(req, self.config["gateway"])

        return {"status": "filled", "orderid": "real_order_id"}

    def query_position(self, symbol: str) -> int:
        """查询持仓"""
        return self.positions.get(symbol, {}).get("volume", 0)

    def query_cash(self) -> float:
        """查询可用资金"""
        return self.cash

    def query_orders(self) -> list:
        """查询委托"""
        return self.orders
