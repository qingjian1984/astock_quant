"""事件驱动引擎 - A股量化交易系统"""
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from loguru import logger


class EventType(Enum):
    """事件类型定义"""
    # 行情事件
    TICK = "tick"                    # 实时tick数据
    BAR_1M = "bar_1m"               # 1分钟K线
    BAR_5M = "bar_5m"               # 5分钟K线
    BAR_15M = "bar_15m"             # 15分钟K线
    BAR_DAILY = "bar_daily"         # 日K线

    # 交易事件
    SIGNAL = "signal"               # 策略信号
    ORDER = "order"                 # 订单生成
    ORDER_CANCEL = "order_cancel"   # 订单撤销
    TRADE = "trade"                 # 成交回报
    POSITION = "position"           # 持仓变化

    # 系统事件
    TIMER = "timer"                 # 定时器
    LOG = "log"                     # 日志
    ERROR = "error"                 # 错误
    STATUS = "status"               # 系统状态变化

    # 风控事件
    RISK_CHECK = "risk_check"       # 风控检查
    RISK_ALERT = "risk_alert"       # 风控告警


@dataclass
class Event:
    """事件对象"""
    type: EventType
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""


class EventEngine:
    """
    事件驱动引擎
    参考 vnpy 的设计，所有组件通过事件总线通信

    用法:
        engine = EventEngine()
        engine.register(EventType.TICK, on_tick_handler)
        engine.put(Event(EventType.TICK, tick_data))
        engine.start()
    """

    def __init__(self, interval: float = 1.0):
        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._queue: List[Event] = []
        self._handlers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._general_handlers: List[Callable] = []  # 全局处理器
        self._timer_interval = interval
        self._timer_thread: Optional[threading.Thread] = None
        self._event_count = 0

    def start(self):
        """启动事件引擎"""
        if self._active:
            return

        self._active = True
        self._thread = threading.Thread(target=self._run, name="EventEngine", daemon=True)
        self._thread.start()

        self._timer_thread = threading.Thread(target=self._run_timer, name="EventTimer", daemon=True)
        self._timer_thread.start()

        logger.info("事件引擎已启动")

    def stop(self):
        """停止事件引擎"""
        if not self._active:
            return

        self._active = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._timer_thread:
            self._timer_thread.join(timeout=5)
        logger.info(f"事件引擎已停止，共处理 {self._event_count} 个事件")

    def put(self, event: Event):
        """推送事件到队列"""
        with self._lock:
            self._queue.append(event)

    def register(self, event_type: EventType, handler: Callable):
        """注册事件处理器"""
        with self._lock:
            self._handlers[event_type].append(handler)
        logger.debug(f"注册处理器: {event_type.value}")

    def unregister(self, event_type: EventType, handler: Callable):
        """注销事件处理器"""
        with self._lock:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

    def register_general(self, handler: Callable):
        """注册全局处理器 - 接收所有事件"""
        with self._lock:
            self._general_handlers.append(handler)

    def _run(self):
        """事件处理循环"""
        while self._active:
            events = []
            with self._lock:
                if self._queue:
                    events = self._queue[:]
                    self._queue.clear()

            for event in events:
                self._process(event)

            if not events:
                time.sleep(0.01)  # 空转时休眠，降低CPU

    def _run_timer(self):
        """定时器循环"""
        while self._active:
            time.sleep(self._timer_interval)
            if self._active:
                self.put(Event(
                    type=EventType.TIMER,
                    data={"timestamp": datetime.now().isoformat()},
                    source="timer"
                ))

    def _process(self, event: Event):
        """处理单个事件"""
        self._event_count += 1

        # 调用类型特定处理器
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"事件处理器异常 [{event.type.value}]: {e}")

        # 调用全局处理器
        for handler in self._general_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"全局事件处理器异常: {e}")

    @property
    def active(self) -> bool:
        return self._active

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def queue_size(self) -> int:
        return len(self._queue)
