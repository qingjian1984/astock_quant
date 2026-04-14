"""数据采集模块 - 基于 AKShare"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
import config


def fetch_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取日线数据（前复权）"""
    logger.info(f"获取日线数据: {symbol} {start_date} ~ {end_date}")
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"  # 前复权
        )
        return _standardize(df)
    except Exception as e:
        logger.error(f"获取日线失败 {symbol}: {e}")
        return pd.DataFrame()


def fetch_minute(symbol: str, period: str = "5") -> pd.DataFrame:
    """获取分钟线数据"""
    logger.info(f"获取分钟线: {symbol} {period}分钟")
    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol,
            period=period,
            adjust="qfq"
        )
        return _standardize(df)
    except Exception as e:
        logger.error(f"获取分钟线失败 {symbol}: {e}")
        return pd.DataFrame()


def fetch_stock_list() -> pd.DataFrame:
    """获取全部A股列表"""
    logger.info("获取A股列表...")
    try:
        df = ak.stock_zh_a_spot_em()
        cols = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "总市值"]
        return df[cols].copy()
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return pd.DataFrame()


def _standardize(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名和格式"""
    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "涨跌幅": "pct_change",
        "时间": "datetime"
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
    return df
