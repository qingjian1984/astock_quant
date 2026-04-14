# ===== 长线股配置 =====
# 预先选好的股票，系统会自动回测找到最优策略进行长期跟踪和做T
LONG_TERM_STOCKS = [
    {"symbol": "000001", "name": "平安银行", "min_capital": 100000},
    {"symbol": "600519", "name": "贵州茅台", "min_capital": 200000},
]

# ===== 波段股配置 =====
SWING_CONFIG = {
    "scan_interval": 3600,          # 选股扫描间隔（秒）
    "max_positions": 5,             # 最大持仓只数
    "strategies": ["ma_cross", "macd"],  # 用于选股的策略列表
    "min_score": 60,                # 策略评分最低要求
}
