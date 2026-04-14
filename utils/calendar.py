"""交易日历工具 - A股"""
import pandas as pd


class TradeCalendar:
    """A股交易日历"""

    def __init__(self):
        self._cache = None

    def get_trading_days(self, start: str, end: str) -> pd.DatetimeIndex:
        """获取交易日（近似，过滤周末）"""
        dates = pd.bdate_range(start, end)
        return dates

    def is_trading_day(self, date) -> bool:
        """判断是否为交易日"""
        dt = pd.Timestamp(date)
        return dt.weekday() < 5  # 周一到周五

    def get_next_trading_day(self, date) -> pd.Timestamp:
        """获取下一个交易日"""
        dt = pd.Timestamp(date)
        while True:
            dt += pd.Timedelta(days=1)
            if self.is_trading_day(dt):
                return dt


def get_trading_hours():
    """A股交易时段"""
    return {
        "pre_open": "09:15-09:25",   # 集合竞价
        "morning": "09:30-11:30",    # 上午交易
        "afternoon": "13:00-15:00",  # 下午交易
        "closing_auction": "14:57-15:00",  # 尾盘集合竞价
    }
