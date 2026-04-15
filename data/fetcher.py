"""数据采集模块 - AKShare + BaoStock 双数据源"""
import akshare as ak
import pandas as pd
import time
from loguru import logger
import config

_baostock_session = None

def _get_baostock():
    """获取 BaoStock 连接（单例）"""
    global _baostock_session
    if _baostock_session is None:
        import baostock as bs
        bs.login()
        _baostock_session = bs
    return _baostock_session


def _symbol_to_baostock(symbol: str) -> str:
    """转换股票代码到 BaoStock 格式"""
    symbol = str(symbol).zfill(6)
    if symbol.startswith("6"):
        return f"sh.{symbol}"
    else:
        return f"sz.{symbol}"


def fetch_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取日线数据（前复权），AKShare 优先，BaoStock 降级"""
    # 尝试 AKShare
    for attempt in range(config.AKSHARE_RETRY):
        logger.info(f"[AKShare] 获取日线: {symbol} {start_date} ~ {end_date} (尝试 {attempt+1}/{config.AKSHARE_RETRY})")
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            result = _standardize_akshare(df)
            if not result.empty:
                logger.info(f"[AKShare] 成功: {len(result)} 条")
                return result
        except Exception as e:
            logger.warning(f"[AKShare] 失败 (尝试 {attempt+1}): {e}")
            if attempt < config.AKSHARE_RETRY - 1:
                time.sleep(2 * (attempt + 1))

    # 降级到 BaoStock
    logger.info(f"[BaoStock] 降级获取日线: {symbol}")
    try:
        bs = _get_baostock()
        bs_symbol = _symbol_to_baostock(symbol)
        rs = bs.query_history_k_data_plus(
            bs_symbol,
            "date,open,high,low,close,volume,amount,Turn,pctChg",
            start_date=start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:],
            end_date=end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:],
            frequency="d",
            adjustflag="2"  # 前复权
        )
        data_list = []
        while rs.error_code == "0" and rs.next():
            data_list.append(rs.get_row_data())
        if data_list:
            cols = ["date", "open", "high", "low", "close", "volume", "amount", "turn", "pct_change"]
            df = pd.DataFrame(data_list, columns=cols)
            result = _standardize_baostock(df)
            logger.info(f"[BaoStock] 成功: {len(result)} 条")
            return result
    except Exception as e:
        logger.error(f"[BaoStock] 失败: {e}")

    logger.error(f"所有数据源均失败: {symbol}")
    return pd.DataFrame()


def fetch_stock_list() -> pd.DataFrame:
    """获取全部A股列表"""
    try:
        df = ak.stock_zh_a_spot_em()
        cols = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "总市值"]
        return df[cols].copy()
    except Exception:
        # BaoStock 降级：获取行业分类
        try:
            bs = _get_baostock()
            rs = bs.query_stock_industry()
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())
            if data_list:
                df = pd.DataFrame(data_list, columns=["code", "code_name", "industry", "industryClassification"])
                return df[["code", "code_name"]]
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
    return pd.DataFrame()


def _standardize_akshare(df: pd.DataFrame) -> pd.DataFrame:
    """标准化 AKShare 数据"""
    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "涨跌幅": "pct_change"
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    for c in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _standardize_baostock(df: pd.DataFrame) -> pd.DataFrame:
    """标准化 BaoStock 数据"""
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    for c in ["open", "high", "low", "close", "volume", "amount", "turn", "pct_change"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
