"""实时行情数据源"""
import time
import pandas as pd
from datetime import datetime
from loguru import logger
from data.manager import DataSourceManager
from data.sources.akshare_src import AKShareSource
from data.sources.baostock_src import BaoStockSource


class RealtimeFeed:
    """
    实时行情推送管理器
    通过轮询 AKShare 获取近实时数据（分钟级刷新）
    """

    def __init__(self, symbols: list, interval: int = 60):
        self.symbols = symbols
        self.interval = interval  # 刷新间隔（秒）
        self.dm = DataSourceManager()
        self.dm.register(AKShareSource(retry=2))
        self.dm.register(BaoStockSource())
        self.dm.connect_all()

        self._latest_data = {}  # {symbol: {price, volume, date, ...}}
        self._history = {s: pd.DataFrame() for s in symbols}
        self._running = False

    def start(self):
        """开始实时数据推送"""
        self._running = True
        logger.info(f"实时行情启动，监控 {len(self.symbols)} 只股票，刷新间隔 {self.interval}s")
        while self._running:
            self._refresh()
            time.sleep(self.interval)

    def stop(self):
        """停止实时数据推送"""
        self._running = False
        logger.info("实时行情已停止")

    def _refresh(self):
        """刷新一次行情"""
        now = datetime.now()
        if not self._is_trading_time(now):
            logger.debug(f"非交易时间，跳过刷新 ({now.strftime('%H:%M:%S')})")
            return

        for symbol in self.symbols:
            try:
                # 获取最近1分钟数据
                df = self.dm.fetch_daily(symbol, now.strftime("%Y%m%d"), now.strftime("%Y%m%d"))
                if not df.empty:
                    bar = df.iloc[-1]
                    self._latest_data[symbol] = {
                        "price": bar["close"],
                        "open": bar.get("open", bar["close"]),
                        "high": bar.get("high", bar["close"]),
                        "low": bar.get("low", bar["close"]),
                        "volume": bar.get("volume", 0),
                        "pct_change": bar.get("pct_change", 0),
                        "time": now,
                    }
                    # 追加历史
                    if self._history[symbol].empty:
                        self._history[symbol] = df
                    else:
                        self._history[symbol] = pd.concat([self._history[symbol], df[~df.index.isin(self._history[symbol].index)]])

                    logger.debug(f"{symbol} 现价: {bar['close']:.2f} ({bar.get('pct_change', 0):+.2f}%)")
            except Exception as e:
                logger.warning(f"获取 {symbol} 实时行情失败: {e}")

    def get_latest(self, symbol: str) -> dict:
        """获取最新行情"""
        return self._latest_data.get(symbol, {})

    def get_history(self, symbol: str) -> pd.DataFrame:
        """获取历史数据（含实时）"""
        return self._history.get(symbol, pd.DataFrame())

    def get_all_latest(self) -> dict:
        """获取所有标的最新行情"""
        return self._latest_data.copy()

    @staticmethod
    def _is_trading_time(dt: datetime) -> bool:
        """判断是否为交易时间"""
        weekday = dt.weekday()
        if weekday >= 5:
            return False
        t = dt.time()
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("11:30", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("15:00", "%H:%M").time()
        return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)

    @staticmethod
    def wait_for_open():
        """等待开盘"""
        now = datetime.now()
        if now.weekday() >= 5:
            logger.info("周末，等待下一个交易日...")
            return False
        t = now.time()
        if t < datetime.strptime("09:30", "%H:%M").time():
            logger.info(f"未开盘，等待开盘... (当前 {t.strftime('%H:%M')})")
            return False
        if t >= datetime.strptime("15:00", "%H:%M").time():
            logger.info(f"已收盘，等待下一个交易日... (当前 {t.strftime('%H:%M')})")
            return False
        return True
