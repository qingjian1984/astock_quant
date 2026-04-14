"""数据源管理器 - 统一管理多个数据源"""
import pandas as pd
from loguru import logger
from data.base import DataSource


class DataSourceManager:
    """
    数据源管理器
    按优先级自动选择数据源，失败时自动降级
    """

    def __init__(self):
        self.sources: list[DataSource] = []
        self._stats = {}  # 记录各数据源成功/失败次数

    def register(self, source: DataSource):
        """注册数据源"""
        self.sources.append(source)
        self.sources.sort(key=lambda s: s.priority, reverse=True)
        self._stats[source.name] = {"success": 0, "fail": 0}
        logger.info(f"注册数据源: {source}")

    def get_source(self, name: str) -> DataSource | None:
        """按名称获取数据源"""
        for s in self.sources:
            if s.name == name:
                return s
        return None

    def list_sources(self) -> list:
        """列出所有数据源"""
        return self.sources

    def available_sources(self) -> list:
        """列出可用数据源"""
        return [s for s in self.sources if s.is_available()]

    def _fetch_with_fallback(self, method_name: str, **kwargs) -> pd.DataFrame:
        """
        通用降级获取方法
        按优先级依次尝试，成功后直接返回
        """
        for source in self.sources:
            if not source.is_available():
                logger.debug(f"跳过不可用数据源: {source.name}")
                continue

            try:
                func = getattr(source, method_name)
                result = func(**kwargs)
                if result is not None and not result.empty:
                    self._stats[source.name]["success"] += 1
                    logger.info(f"[{source.name}] {method_name} 成功: {len(result)} 条")
                    return result
                self._stats[source.name]["fail"] += 1
                logger.warning(f"[{source.name}] {method_name} 返回空数据")
            except Exception as e:
                self._stats[source.name]["fail"] += 1
                logger.warning(f"[{source.name}] {method_name} 失败: {e}")

        logger.error(f"所有数据源均失败: {method_name}({kwargs})")
        return pd.DataFrame()

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日线数据（自动降级）"""
        return self._fetch_with_fallback(
            "fetch_daily",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )

    def fetch_stock_list(self) -> pd.DataFrame:
        """获取股票列表（自动降级）"""
        return self._fetch_with_fallback("fetch_stock_list")

    def fetch_by_source(self, source_name: str, symbol: str,
                        start_date: str, end_date: str) -> pd.DataFrame:
        """指定数据源获取数据"""
        source = self.get_source(source_name)
        if source is None:
            logger.error(f"数据源不存在: {source_name}")
            return pd.DataFrame()
        if not source.is_available():
            logger.error(f"数据源不可用: {source_name}")
            return pd.DataFrame()
        return source.fetch_daily(symbol, start_date, end_date)

    def fetch_multi_source(self, symbol: str, start_date: str, end_date: str) -> dict:
        """
        从所有可用数据源获取数据并对比
        返回 {source_name: DataFrame}
        """
        results = {}
        for source in self.sources:
            if source.is_available():
                df = source.fetch_daily(symbol, start_date, end_date)
                if not df.empty:
                    results[source.name] = df
        return results

    def compare_sources(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        对比多个数据源的数据质量
        返回对比摘要
        """
        results = self.fetch_multi_source(symbol, start_date, end_date)
        if not results:
            return pd.DataFrame()

        rows = []
        for name, df in results.items():
            rows.append({
                "数据源": name,
                "数据条数": len(df),
                "日期范围": f"{df.index[0]} ~ {df.index[-1]}",
                "缺失close": df["close"].isna().sum() if "close" in df.columns else "N/A",
                "缺失volume": df["volume"].isna().sum() if "volume" in df.columns else "N/A",
            })
        return pd.DataFrame(rows)

    def get_stats(self) -> pd.DataFrame:
        """获取各数据源的调用统计"""
        rows = []
        for name, stat in self._stats.items():
            total = stat["success"] + stat["fail"]
            rows.append({
                "数据源": name,
                "成功": stat["success"],
                "失败": stat["fail"],
                "成功率": f"{stat['success'] / total:.0%}" if total > 0 else "N/A",
            })
        return pd.DataFrame(rows)

    def connect_all(self):
        """连接所有数据源"""
        for source in self.sources:
            try:
                source.connect()
            except Exception as e:
                logger.warning(f"[{source.name}] 连接失败: {e}")
