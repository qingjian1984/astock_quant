"""数据库模块"""
import pandas as pd
from sqlalchemy import create_engine, text
from loguru import logger
import config


def get_engine():
    """获取数据库引擎"""
    db_config = config.DB_CONFIG[config.DB_ACTIVE]
    engine = create_engine(db_config["url"], echo=False)
    # 建表
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_bars (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                pct_change REAL,
                PRIMARY KEY (symbol, date)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                direction TEXT,
                price REAL,
                volume INTEGER,
                commission REAL,
                tax REAL,
                date TEXT,
                strategy TEXT
            )
        """))
        conn.commit()
    logger.info(f"数据库已连接: {config.DB_ACTIVE}")
    return engine


def save_daily(engine, symbol: str, df):
    """保存日线数据到数据库"""
    df_copy = df.copy().reset_index()
    df_copy["symbol"] = symbol
    df_copy.to_sql("daily_bars", engine, if_exists="append", index=False, method="multi")
    logger.info(f"保存 {symbol} {len(df)} 条日线数据")


def load_daily(engine, symbol: str, start_date: str = None, end_date: str = None):
    """从数据库加载日线数据"""
    query = f"SELECT * FROM daily_bars WHERE symbol = '{symbol}'"
    if start_date:
        query += f" AND date >= '{start_date}'"
    if end_date:
        query += f" AND date <= '{end_date}'"
    query += " ORDER BY date"
    df = pd.read_sql(query, engine)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    return df
