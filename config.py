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
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")  # 可选
AKSHARE_RETRY = 3
AKSHARE_TIMEOUT = 30

# ===== 交易参数 =====
TRADE_CONFIG = {
    "commission_rate": 0.00025,    # 佣金 万2.5
    "commission_min": 5.0,         # 最低佣金 5元
    "stamp_tax": 0.001,            # 印花税 千1 (卖出)
    "transfer_fee": 0.00001,       # 过户费 万0.1
    "slippage": 0.0,               # 滑点(百分比)
    "min_volume": 100,             # 最小交易单位 1手
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
