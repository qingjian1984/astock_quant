# A股量化交易系统

## 项目结构

```
astock_quant/
├── config.py              # 全局配置（交易费率、风控参数）
├── requirements.txt       # Python 依赖
├── data/
│   ├── fetcher.py         # 数据采集（AKShare）
│   └── store.py           # 数据库存储（SQLite/PostgreSQL）
├── strategy/
│   ├── base.py            # 策略基类
│   └── ma_cross.py        # 双均线策略示例
├── backtest/
│   ├── engine.py          # 回测引擎（含A股费用计算）
│   └── run.py             # 回测入口
├── risk/
│   └── manager.py         # 风控模块（止损、仓位控制）
├── live/
│   └── trader.py          # 实盘交易接口（预留）
└── utils/
    └── calendar.py        # 交易日历
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行回测

```bash
# 平安银行 2023-2024 双均线回测
python backtest/run.py --symbol 000001 --start 20230101 --end 20241231

# 贵州茅台
python backtest/run.py --symbol 600519 --start 20230101 --end 20241231
```

### 3. 自定义策略

继承 `strategy/base.py` 中的 `BaseStrategy`，实现 `on_bar` 方法即可。

## A股特殊处理

- 前复权数据（除权除息处理）
- 印花税 千1（卖出时收取）
- 佣金 万2.5（最低5元）
- 100股整数倍（1手）
- T+1 限制
- 涨跌停限制

## 扩展方向

- [ ] 接入 Tushare Pro 数据源
- [ ] 多因子选股策略
- [ ] vnpy 实盘对接
- [ ] 钉钉/微信告警
- [ ] 可视化看板（Grafana/Plotly）
- [ ] PostgreSQL 时序数据库
