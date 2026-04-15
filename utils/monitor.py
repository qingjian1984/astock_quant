"""监控与告警模块"""
import requests
import json
from datetime import datetime
from loguru import logger
import config


class AlertManager:
    """告警管理器 - 支持钉钉/微信/日志"""

    def __init__(self, dingtalk_webhook: str = None):
        self.dingtalk = dingtalk_webhook or config.DINGTALK_WEBHOOK
        self.alert_history = []

    def send(self, title: str, content: str, level: str = "info"):
        """
        发送告警
        level: info / warning / critical
        """
        msg = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "title": title,
            "content": content,
        }
        self.alert_history.append(msg)

        # 写日志
        if level == "critical":
            logger.critical(f"[{title}] {content}")
        elif level == "warning":
            logger.warning(f"[{title}] {content}")
        else:
            logger.info(f"[{title}] {content}")

        # 钉钉推送
        if self.dingtalk:
            self._send_dingtalk(title, content, level)

    def _send_dingtalk(self, title: str, content: str, level: str):
        """钉钉机器人推送"""
        color = {"info": "#2196F3", "warning": "#FF9800", "critical": "#F44336"}.get(level, "#2196F3")
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"## <font color='{color}'>{title}</font>\n\n{content}\n\n---\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            },
        }
        try:
            resp = requests.post(self.dingtalk, json=payload, timeout=10, headers={"Content-Type": "application/json"})
            if resp.status_code == 200:
                logger.debug(f"钉钉推送成功: {title}")
            else:
                logger.error(f"钉钉推送失败: {resp.text}")
        except Exception as e:
            logger.error(f"钉钉推送异常: {e}")

    def daily_report(self, stats: dict, equity_df=None):
        """发送每日交易报告"""
        lines = ["#### 今日交易报告\n"]
        for k, v in stats.items():
            lines.append(f"- **{k}**: {v}")

        self.send("每日报告", "\n".join(lines), "info")


class PerformanceMonitor:
    """
    实时绩效监控
    跟踪：当日盈亏、持仓、回撤等
    """

    def __init__(self, alert_mgr: AlertManager = None):
        self.alert = alert_mgr or AlertManager()
        self.daily_start_value = None

    def check_drawdown(self, current_value: float, peak_value: float, threshold: float = -0.10):
        """检查回撤告警"""
        dd = (current_value - peak_value) / peak_value
        if dd < threshold:
            self.alert.send(
                "回撤告警",
                f"当前回撤: {dd:.2%}\n峰值: {peak_value:,.0f}\n当前: {current_value:,.0f}",
                "critical",
            )
        return dd

    def check_position(self, position_value: float, total_value: float, threshold: float = 0.30):
        """检查单票仓位告警"""
        pct = position_value / total_value if total_value > 0 else 0
        if pct > threshold:
            self.alert.send(
                "仓位告警",
                f"单票仓位: {pct:.1%} (阈值 {threshold:.0%})\n持仓: {position_value:,.0f}",
                "warning",
            )
        return pct

    def daily_pnl(self, current_value: float):
        """计算当日盈亏"""
        if self.daily_start_value is None:
            self.daily_start_value = current_value
            return 0, current_value

        pnl = current_value - self.daily_start_value
        pnl_pct = pnl / self.daily_start_value

        self.alert.send(
            "当日盈亏",
            f"盈亏: {pnl:+,.0f} ({pnl_pct:+.2%})\n当前净值: {current_value:,.0f}",
            "info" if abs(pnl_pct) < 0.02 else "warning",
        )
        return pnl, pnl_pct
