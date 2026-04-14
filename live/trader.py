"""实盘交易模块（预留接口）"""
from loguru import logger


class LiveTrader:
    """
    实盘交易接口
    需要对接券商 API（如 vnpy/CTP/XTP）
    """

    def __init__(self, broker_config: dict = None):
        self.broker = None
        self.config = broker_config or {}
        logger.warning("实盘交易模块未配置，需要接入券商 API")

    def connect(self):
        """连接券商"""
        logger.info("连接券商...")
        # 示例: vnpy 接入
        # from vnpy.event import EventEngine
        # from vnpy.trader.engine import MainEngine
        # self.engine = MainEngine(EventEngine())
        # self.engine.connect(self.config)
        pass

    def order(self, symbol: str, direction: str, price: float, volume: int):
        """下单"""
        logger.info(f"下单: {symbol} {direction} {volume}股 @ {price:.2f}")
        # TODO: 实际下单逻辑
        pass

    def query_position(self, symbol: str) -> int:
        """查询持仓"""
        return 0

    def query_cash(self) -> float:
        """查询可用资金"""
        return 0.0
