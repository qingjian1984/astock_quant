"""实时监管与仪表盘"""
import pandas as pd
import json
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from utils.monitor import AlertManager


class TradingSupervisor:
    """
    交易系统监管器
    实时监控：资金、持仓、风险、策略表现、系统健康
    """

    def __init__(self, alert_mgr: AlertManager = None):
        self.alert = alert_mgr or AlertManager()
        self.state_log = []
        self.risk_events = []
        self.system_health = {
            "last_heartbeat": datetime.now(),
            "errors": 0,
            "warnings": 0,
            "uptime": datetime.now(),
        }
        self.watch_path = Path("data/state.json")
        self.watch_path.parent.mkdir(parents=True, exist_ok=True)

    def heartbeat(self, trader_state: dict):
        """记录一次心跳"""
        self.system_health["last_heartbeat"] = datetime.now()

        state = {
            "time": datetime.now().isoformat(),
            "cash": trader_state.get("cash", 0),
            "positions": trader_state.get("positions", {}),
            "total_orders": trader_state.get("total_orders", 0),
        }
        self.state_log.append(state)

        # 保留最近1000条
        if len(self.state_log) > 1000:
            self.state_log = self.state_log[-500:]

        # 保存状态
        self._save_state()

    def check_system_health(self):
        """检查系统健康状态"""
        now = datetime.now()
        last = self.system_health["last_heartbeat"]

        if (now - last).total_seconds() > 300:  # 5分钟无心跳
            self.alert.send(
                "系统异常",
                f"交易引擎超过5分钟无响应\n最后心跳: {last.strftime('%H:%M:%S')}",
                "critical",
            )
            self.system_health["errors"] += 1
            return False
        return True

    def check_pnl_alert(self, current_value: float, initial_value: float,
                        daily_open_value: float):
        """盈亏告警"""
        total_pnl = (current_value - initial_value) / initial_value
        daily_pnl = (current_value - daily_open_value) / daily_open_value

        if daily_pnl < -0.03:
            self.alert.send(
                "单日亏损告警",
                f"今日亏损 {daily_pnl:.2%}\n当前净值: {current_value:,.0f}\n开盘净值: {daily_open_value:,.0f}",
                "warning",
            )

        if total_pnl < -0.10:
            self.alert.send(
                "总亏损告警",
                f"累计亏损 {total_pnl:.2%}\n当前净值: {current_value:,.0f}\n初始资金: {initial_value:,.0f}",
                "critical",
            )

    def check_position_concentration(self, positions: dict, total_value: float,
                                     threshold: float = 0.40):
        """持仓集中度告警"""
        for symbol, pos in positions.items():
            value = pos.get("volume", 0) * pos.get("cost", 0)
            pct = value / total_value if total_value > 0 else 0
            if pct > threshold:
                self.alert.send(
                    "持仓集中告警",
                    f"{symbol} 占比 {pct:.1%} 超过阈值 {threshold:.0%}",
                    "warning",
                )

    def check_trade_frequency(self, orders: list, window_minutes: int = 30,
                              max_trades: int = 5):
        """交易频率告警"""
        now = datetime.now()
        recent = [o for o in orders
                  if (now - datetime.fromisoformat(o["time"])).total_seconds() < window_minutes * 60]

        if len(recent) > max_trades:
            self.alert.send(
                "交易频率异常",
                f"{window_minutes}分钟内交易 {len(recent)} 次，超过阈值 {max_trades}",
                "warning",
            )

    def generate_daily_report(self, trader_state: dict, learning_stats: dict) -> str:
        """生成每日监管报告"""
        report = f"""
## 每日监管报告 - {datetime.now().strftime('%Y-%m-%d')}

### 账户状态
- 现金: {trader_state.get('cash', 0):,.0f}
- 持仓: {len(trader_state.get('positions', {}))} 只
- 总订单: {trader_state.get('total_orders', 0)} 笔

### 学习统计
- 总交易: {learning_stats.get('total_trades', 0)} 笔
- 胜率: {learning_stats.get('win_rate', 0):.0%}
- 盈利: {learning_stats.get('wins', 0)} 笔
- 亏损: {learning_stats.get('losses', 0)} 笔

### 系统健康
- 运行时长: {datetime.now() - self.system_health['uptime']}
- 错误次数: {self.system_health['errors']}
- 最后心跳: {self.system_health['last_heartbeat'].strftime('%H:%M:%S')}
"""
        return report

    def _save_state(self):
        """保存状态到文件"""
        try:
            state = {
                "last_update": datetime.now().isoformat(),
                "system_health": {
                    "last_heartbeat": self.system_health["last_heartbeat"].isoformat(),
                    "errors": self.system_health["errors"],
                    "uptime": self.system_health["uptime"].isoformat(),
                },
                "latest_state": self.state_log[-1] if self.state_log else {},
            }
            with open(self.watch_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def load_state(self) -> dict:
        """加载最新状态"""
        if self.watch_path.exists():
            with open(self.watch_path, "r") as f:
                return json.load(f)
        return {}
