"""实时行情数据源 - 改进版（支持分钟级数据）"""
import time
import threading
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from loguru import logger
from data.manager import DataSourceManager
from data.sources.akshare_src import AKShareSource
from data.sources.baostock_src import BaoStockSource


class RealtimeFeed:
    """
    实时行情推送管理器 - 改进版
    功能：
    - 支持日线数据轮询（分钟级刷新）
    - 支持实时 tick 数据（通过 AKShare 东方财富接口）
    - 交易时间自动判断
    - 数据缓存和历史记录
    - 回调通知机制
    """

    def __init__(self, symbols: list, interval: int = 60):
        self.symbols = symbols
        self.interval = interval  # 刷新间隔（秒）
        self.dm = DataSourceManager()
        self.dm.register(AKShareSource(retry=2))
        self.dm.register(BaoStockSource())
        self.dm.connect_all()

        # 数据存储
        self._latest_data: Dict[str, dict] = {}  # {symbol: {price, volume, date, ...}}
        self._history: Dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}
        self._intraday_data: Dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}  # 分钟级数据
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 回调函数
        self._callbacks: List[Callable] = []

        # 交易时间控制
        self._last_refresh_date = ""
        self._daily_data_cache: Dict[str, pd.DataFrame] = {}

    def start(self, background: bool = False):
        """开始实时数据推送"""
        self._running = True
        logger.info(f"实时行情启动，监控 {len(self.symbols)} 只股票，刷新间隔 {self.interval}s")

        if background:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("实时行情在后台线程运行")
        else:
            self._run_loop()

    def stop(self):
        """停止实时数据推送"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("实时行情已停止")

    def _run_loop(self):
        """运行循环"""
        while self._running:
            try:
                self._refresh()
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"实时行情刷新异常: {e}")
                time.sleep(self.interval)

    def add_callback(self, callback: Callable):
        """添加数据更新回调"""
        self._callbacks.append(callback)

    def _refresh(self):
        """刷新一次行情"""
        now = datetime.now()

        # 检查交易时间
        if not self._is_trading_time(now):
            if self._last_refresh_date != now.strftime("%Y-%m-%d"):
                logger.debug(f"非交易时间，跳过刷新 ({now.strftime('%H:%M:%S')})")
            return

        # 日期变更时刷新缓存
        today = now.strftime("%Y-%m-%d")
        if today != self._last_refresh_date:
            self._last_refresh_date = today
            self._daily_data_cache.clear()

        for symbol in self.symbols:
            try:
                # 获取今日数据
                today_str = now.strftime("%Y%m%d")
                df = self._get_today_data(symbol, today_str)

                if df.empty:
                    continue

                bar = df.iloc[-1]
                self._latest_data[symbol] = {
                    "price": bar["close"],
                    "open": bar.get("open", bar["close"]),
                    "high": bar.get("high", bar["close"]),
                    "low": bar.get("low", bar["close"]),
                    "volume": bar.get("volume", 0),
                    "amount": bar.get("amount", 0),
                    "pct_change": bar.get("pct_change", 0),
                    "time": now,
                    "date": today_str,
                }

                # 更新历史数据
                if self._history[symbol].empty:
                    self._history[symbol] = df
                else:
                    # 合并新数据（去重）
                    existing_dates = set(self._history[symbol].index)
                    new_rows = df[~df.index.isin(existing_dates)]
                    if not new_rows.empty:
                        self._history[symbol] = pd.concat([self._history[symbol], new_rows])
                        self._history[symbol] = self._history[symbol].sort_index()

                # 触发回调
                for callback in self._callbacks:
                    try:
                        callback(symbol, self._latest_data[symbol])
                    except Exception as e:
                        logger.error(f"回调执行失败: {e}")

                logger.debug(
                    f"{symbol} 现价: {bar['close']:.2f} "
                    f"({bar.get('pct_change', 0):+.2f}%) "
                    f"成交量: {bar.get('volume', 0)}"
                )

            except Exception as e:
                logger.warning(f"获取 {symbol} 实时行情失败: {e}")

    def _get_today_data(self, symbol: str, today_str: str) -> pd.DataFrame:
        """获取今日数据（带缓存）"""
        if today_str in self._daily_data_cache:
            return self._daily_data_cache[today_str]

        try:
            # 使用 AKShare 获取实时数据
            df = self.dm.fetch_daily(symbol, today_str, today_str)
            if not df.empty:
                self._daily_data_cache[today_str] = df
            return df
        except Exception as e:
            logger.warning(f"获取 {symbol} 今日数据失败: {e}")
            return pd.DataFrame()

    def get_latest(self, symbol: str) -> dict:
        """获取最新行情"""
        return self._latest_data.get(symbol, {})

    def get_history(self, symbol: str) -> pd.DataFrame:
        """获取历史数据（含实时）"""
        return self._history.get(symbol, pd.DataFrame())

    def get_all_latest(self) -> dict:
        """获取所有标的最新行情"""
        return self._latest_data.copy()

    def get_intraday_data(self, symbol: str, period: str = "1") -> pd.DataFrame:
        """
        获取分钟级数据
        period: 1, 5, 15, 30, 60 分钟
        """
        try:
            import akshare as ak
            # AKShare 东方财富分钟数据接口
            df = ak.stock_zh_a_hist_min_em(
                symbol=symbol,
                period=period,
                adjust="qfq"
            )
            if not df.empty:
                df.index = pd.to_datetime(df["时间"])
                df = df.rename(columns={
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                    "成交额": "amount",
                })
                self._intraday_data[symbol] = df
            return df
        except Exception as e:
            logger.warning(f"获取 {symbol} 分钟数据失败: {e}")
            return self._intraday_data.get(symbol, pd.DataFrame())

    def is_trading_time(self) -> bool:
        """判断当前是否为交易时间"""
        return self._is_trading_time(datetime.now())

    @staticmethod
    def _is_trading_time(dt: datetime) -> bool:
        """判断是否为交易时间"""
        weekday = dt.weekday()
        if weekday >= 5:  # 周末
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

    @staticmethod
    def get_next_trading_time() -> datetime:
        """获取下一个交易时间"""
        now = datetime.now()

        # 如果是周末，跳到下周一
        if now.weekday() >= 5:
            days_ahead = 7 - now.weekday()
            next_day = now.replace(hour=9, minute=30, second=0, microsecond=0) + \
                      timedelta(days=days_ahead)
            return next_day

        t = now.time()
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("11:30", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("15:00", "%H:%M").time()

        if t < morning_start:
            # 今天开盘前
            return now.replace(hour=9, minute=30, second=0, microsecond=0)
        elif morning_end < t < afternoon_start:
            # 中午休市
            return now.replace(hour=13, minute=0, second=0, microsecond=0)
        elif t >= afternoon_end:
            # 今天收盘后，下一个交易日
            days_ahead = 1 if now.weekday() < 4 else 7 - now.weekday()
            next_day = now.replace(hour=9, minute=30, second=0, microsecond=0) + \
                      timedelta(days=days_ahead)
            return next_day

        return now  # 交易时间内
