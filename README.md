# A股量化交易系统

> 完整的A股量化交易回测系统，包含数据采集、策略引擎、回测、风控、可视化和监控告警

## 项目结构

```
astock_quant/
├── config.py              # 全局配置（交易费率、风控参数）
├── requirements.txt       # Python 依赖
├── data/
│   ├── fetcher.py         # 数据采集（AKShare 优先，BaoStock 降级）
│   └── store.py           # 数据库存储（SQLite/PostgreSQL）
├── strategy/
│   ├── base.py            # 策略基类（多标的支持）
│   ├── ma_cross.py        # 双均线策略
│   ├── rsi.py             # RSI 均值回归
│   ├── macd.py            # MACD 趋势跟踪
│   └── multi_factor.py    # 多因子选股
├── backtest/
│   ├── engine.py          # 回测引擎（T+1/涨跌停/滑点/风控/多标的）
│   └── run.py             # 回测入口
├── risk/
│   └── manager.py         # 风控模块（止损止盈、仓位控制）
├── live/
│   └── trader.py          # 实盘交易接口（预留）
└── utils/
    ├── calendar.py        # 交易日历
    ├── viz.py             # 可视化（净值曲线/买卖点/月度热力图）
    └── monitor.py         # 监控告警（钉钉推送/回撤监控/每日报告）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行回测

```bash
# 单标的回测
python backtest/run.py --symbol 000001 --start 20240101 --end 20241231

# 多标的回测
python backtest/run.py --symbol "000001,600519,000858" --start 20240101 --end 20241231

# 切换策略
python backtest/run.py --symbol 000001 --strategy rsi
python backtest/run.py --symbol 000001 --strategy macd
python backtest/run.py --symbol "000001,600519" --strategy multi_factor

# 调整参数
python backtest/run.py --symbol 000001 --capital 500000 --slippage 0.002
```

### 3. 输出结果

回测完成后会在 `results/` 目录生成：
- `equity_curve.png` - 净值曲线 + 最大回撤图
- `trades.png` - 交易信号标记图
- `monthly_returns.png` - 月度收益热力图
- `equity.csv` - 净值数据
- `trades.csv` - 交易明细

## 策略说明

| 策略 | 文件 | 信号逻辑 | 适用场景 |
|------|------|----------|----------|
| 双均线 | ma_cross.py | MA5上穿MA20买入，下穿卖出 | 趋势行情 |
| RSI | rsi.py | RSI<30超卖买入，>70超买卖出 | 震荡行情 |
| MACD | macd.py | DIF上穿DEA买入，下穿卖出 | 趋势行情 |
| 多因子 | multi_factor.py | 动量+波动率+成交量综合评分 | 组合选股 |

## A股特殊处理（已实现）

| 规则 | 处理方式 |
|------|----------|
| T+1 | 买入当天禁止卖出，记录buy_date |
| 涨跌停 | 涨停(>=+9.9%)不能买，跌停(<=-9.9%)不能卖 |
| 滑点 | 买入价上偏、卖出价下偏，默认千1 |
| 手续费 | 佣金万2.5(最低5元)+印花税千1(卖出)+过户费万0.1 |
| 最小单位 | 100股整数倍 |
| 风控 | 单票20%上限、总仓位80%、止损8%、止盈20%、回撤15%暂停 |

## 数据源

- **主数据源**: AKShare（免费，A股数据全）
- **降级数据源**: BaoStock（AKShare不可用时自动切换）
- **预留**: Tushare Pro（需配置token）

## 扩展方向

- [ ] vnpy 实盘对接
- [ ] 参数优化（网格搜索、Walk-Forward）
- [ ] 更多策略（布林带、海龟、配对交易）
- [ ] 因子库（估值因子、质量因子、情绪因子）
- [ ] 实时行情监控
- [ ] PostgreSQL 时序数据库
