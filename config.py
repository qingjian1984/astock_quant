"""全局配置"""
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# ===== 数据库 =====
DB_CONFIG = {
    "sqlite": {
        "url": f"sqlite:///{PROJECT_ROOT}/data/astock.db"
    },
    # PostgreSQL 取消注释启用
    # "postgresql": {
    #     "url": "postgresql+psycopg2://user:pass@localhost:5432/astock"
    # }
}
DB_ACTIVE = "sqlite"  # 切换 "sqlite" 或 "postgresql"

# ===== 数据源 =====
AKSHARE_RETRY = 3
AKSHARE_TIMEOUT = 30
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# 数据源优先级（数字越大越优先）
DATA_SOURCES = [
    {"name": "AKShare", "priority": 10, "enabled": True},
    {"name": "Tushare", "priority": 8, "enabled": TUSHARE_TOKEN != ""},
    {"name": "BaoStock", "priority": 5, "enabled": True},
    {"name": "YahooFinance", "priority": 3, "enabled": False},  # 港股/美股
]

# ===== 交易模式 =====
# 模式: "paper"=模拟盘, "live"=实盘
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# 实盘券商配置（按需启用）
BROKER_CONFIG = {
    "vnpy": {
        "gateway": "CTP",           # CTP / XTP / 其他
        "user_id": os.getenv("BROKER_USER", ""),
        "password": os.getenv("BROKER_PASS", ""),
        "broker_id": os.getenv("BROKER_ID", ""),
        "td_address": os.getenv("BROKER_ADDR", ""),
    },
}

# ===== 交易参数 =====
TRADE_CONFIG = {
    "commission_rate": 0.00025,    # 佣金 万2.5
    "commission_min": 5.0,         # 最低佣金 5元
    "stamp_tax": 0.001,            # 印花税 千1 (卖出)
    "transfer_fee": 0.00001,       # 过户费 万0.1
    "slippage": 0.001,             # 滑点(百分比) 默认千1
    "min_volume": 100,             # 最小交易单位 1手
}

# ===== 每日交易限制 =====
DAILY_LIMITS = {
    "max_trades_per_day": 10,       # 每日最大交易次数
    "max_amount_per_trade": 100000, # 单笔最大金额
    "max_volume_per_trade": 10000,  # 单笔最大股数
    "min_trade_interval": 300,      # 最小交易间隔（秒）5分钟
    "max_daily_amount": 500000,     # 每日最大交易总额
    "max_daily_buy_amount": 300000, # 每日最大买入金额
    "max_daily_sell_amount": 300000,# 每日最大卖出金额
}

# ===== 风控参数 =====
RISK_CONFIG = {
    "max_position_pct": 0.20,      # 单票最大仓位 20%
    "max_total_position": 0.80,    # 总仓位上限 80%
    "stop_loss_pct": -0.08,        # 止损 -8%
    "take_profit_pct": 0.20,       # 止盈 +20%
    "max_drawdown_pct": -0.15,     # 最大回撤暂停 -15%
    "blacklist": [],               # 黑名单股票代码
}

# ===== 通知 =====
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")

# ===== 日志 =====
LOG_CONFIG = {
    "level": "INFO",
    "file": str(PROJECT_ROOT / "logs" / "astock.log"),
}

# ===== 长线股配置 =====
from core.portfolio import LONG_TERM_STOCKS, SWING_CONFIG
