"""策略管理器 - 支持热加载和自动发现"""
import importlib
import importlib.util
import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger

from strategy.base import BaseStrategy


@dataclass
class StrategyInfo:
    """策略信息"""
    name: str              # 策略标识名
    module_path: str       # 模块文件路径
    class_name: str        # 策略类名
    description: str       # 策略描述
    params: Dict[str, Any] = field(default_factory=dict)  # 默认参数
    file_hash: str = ""    # 文件hash，用于检测变更
    instance: Optional[BaseStrategy] = None  # 当前实例
    loaded_at: Optional[datetime] = None    # 加载时间
    error: Optional[str] = None            # 加载错误信息


class StrategyManager:
    """
    策略管理器
    支持策略的自动发现、热加载、参数管理

    用法:
        manager = StrategyManager(engine)
        manager.discover_strategies()       # 自动扫描策略目录
        manager.load_strategy("ma_cross")   # 手动加载
        manager.watch_for_changes()         # 开启文件监控
    """

    def __init__(self, strategy_dir: str = None, engine=None):
        self._strategies: Dict[str, StrategyInfo] = {}
        self._strategy_dir = Path(strategy_dir) if strategy_dir else Path(__file__).parent.parent / "strategy"
        self._engine = engine
        self._watching = False
        self._file_hashes: Dict[str, str] = {}

    def discover_strategies(self) -> List[str]:
        """自动扫描策略目录，发现所有策略"""
        discovered = []

        if not self._strategy_dir.exists():
            logger.warning(f"策略目录不存在: {self._strategy_dir}")
            return discovered

        for py_file in self._strategy_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_name = py_file.stem
            try:
                info = self._scan_file(py_file)
                if info:
                    self._strategies[module_name] = info
                    discovered.append(module_name)
                    logger.info(f"发现策略: {module_name} -> {info.class_name}")
            except Exception as e:
                logger.error(f"扫描策略文件失败 {py_file.name}: {e}")

        return discovered

    def _scan_file(self, file_path: Path) -> Optional[StrategyInfo]:
        """扫描策略文件，提取策略类信息"""
        content = file_path.read_text(encoding="utf-8")

        # 查找继承自 BaseStrategy 的类
        import re
        class_match = re.search(r'class\s+(\w+)\s*\(\s*BaseStrategy\s*\)', content)
        if not class_match:
            return None

        class_name = class_match.group(1)

        # 查找描述字符串
        desc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
        description = desc_match.group(1).strip().split("\n")[0] if desc_match else ""

        # 查找默认参数
        params = self._extract_params(content)

        return StrategyInfo(
            name=file_path.stem,
            module_path=str(file_path),
            class_name=class_name,
            description=description,
            params=params,
            file_hash=hashlib.md5(content.encode()).hexdigest()
        )

    def _extract_params(self, content: str) -> Dict[str, Any]:
        """从策略代码中提取参数定义（从 __init__ 签名）"""
        import re
        import ast

        # 尝试用 AST 解析 __init__ 的参数默认值
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                            params = {}
                            for arg in item.args.args:
                                if arg.arg == 'self':
                                    continue
                            # 获取默认值
                            defaults = item.args.defaults
                            num_defaults = len(defaults)
                            all_args = item.args.args
                            # 默认值对应最后 N 个参数
                            start_idx = len(all_args) - num_defaults
                            for i, default in enumerate(defaults):
                                arg_name = all_args[start_idx + i].arg
                                if arg_name == 'self':
                                    continue
                                # 解析默认值
                                try:
                                    if isinstance(default, ast.Constant):
                                        params[arg_name] = default.value
                                    elif isinstance(default, ast.Num):
                                        params[arg_name] = default.n
                                except Exception:
                                    pass
                            return params
        except Exception:
            pass

        # 回退：正则匹配 __init__(self, fast: int = 5, slow: int = 20)
        init_match = re.search(r'def __init__\s*\(self\s*(.*?)\)', content, re.DOTALL)
        if init_match:
            params = {}
            args_str = init_match.group(1)
            # 匹配 param: type = value 或 param = value
            for match in re.finditer(r'(\w+)\s*(?::\s*\w+\s*)?=\s*([^,)]+)', args_str):
                name = match.group(1)
                default = match.group(2).strip().strip("\"'")
                try:
                    params[name] = int(default)
                except ValueError:
                    try:
                        params[name] = float(default)
                    except ValueError:
                        params[name] = default
            return params

        return {}

    def load_strategy(self, name: str, params: Dict = None) -> Optional[BaseStrategy]:
        """加载并实例化策略"""
        if name not in self._strategies:
            logger.error(f"未知策略: {name}")
            return None

        info = self._strategies[name]

        try:
            # 动态加载模块
            spec = importlib.util.spec_from_file_location(f"strategy.{name}", info.module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 获取策略类
            strategy_class = getattr(module, info.class_name)

            # 合并默认参数和自定义参数
            final_params = {**info.params, **(params or {})}

            # 检查策略类是否接受 name/params 签名，还是直接接受 kwargs
            import inspect
            sig = inspect.signature(strategy_class.__init__)
            param_names = set(sig.parameters.keys())

            if 'params' in param_names:
                # 标准 BaseStrategy 签名: __init__(self, name, params)
                instance = strategy_class(name=name, params=final_params)
            elif 'name' in param_names:
                # 混合签名: __init__(self, name, **kwargs)
                instance = strategy_class(name=name, **final_params)
            else:
                # 直接参数签名: __init__(self, fast=5, slow=20)
                instance = strategy_class(**final_params)

            # 更新信息
            info.instance = instance
            info.loaded_at = datetime.now()
            info.error = None

            logger.info(f"策略加载成功: {name} ({info.class_name})")
            return instance

        except Exception as e:
            info.error = str(e)
            logger.error(f"策略加载失败 {name}: {e}")
            return None

    def unload_strategy(self, name: str):
        """卸载策略"""
        if name in self._strategies:
            info = self._strategies[name]
            if info.instance:
                info.instance = None
            info.loaded_at = None
            logger.info(f"策略已卸载: {name}")

    def reload_strategy(self, name: str, params: Dict = None) -> Optional[BaseStrategy]:
        """热重载策略"""
        if name not in self._strategies:
            return None

        info = self._strategies[name]

        # 检查文件是否变更
        try:
            content = Path(info.module_path).read_text(encoding="utf-8")
            new_hash = hashlib.md5(content.encode()).hexdigest()

            if new_hash == info.file_hash:
                logger.debug(f"策略文件未变更，无需重载: {name}")
                return info.instance

            info.file_hash = new_hash
            logger.info(f"检测到策略文件变更，正在重载: {name}")

        except Exception as e:
            logger.error(f"检查策略文件失败: {e}")

        return self.load_strategy(name, params)

    def get_strategy_instance(self, name: str) -> Optional[BaseStrategy]:
        """获取策略实例"""
        if name in self._strategies:
            return self._strategies[name].instance
        return None

    def list_strategies(self) -> List[Dict]:
        """列出所有已发现的策略"""
        result = []
        for name, info in self._strategies.items():
            result.append({
                "name": name,
                "class_name": info.class_name,
                "description": info.description,
                "params": info.params,
                "loaded": info.instance is not None,
                "loaded_at": info.loaded_at.isoformat() if info.loaded_at else None,
                "error": info.error,
                "file_path": info.module_path,
            })
        return result

    def watch_for_changes(self, interval: float = 5.0):
        """启动文件监控（后台线程）"""
        if self._watching:
            return

        self._watching = True

        def _watch_loop():
            while self._watching:
                for name, info in list(self._strategies.items()):
                    if not info.instance:
                        continue

                    try:
                        content = Path(info.module_path).read_text(encoding="utf-8")
                        new_hash = hashlib.md5(content.encode()).hexdigest()

                        if new_hash != info.file_hash:
                            logger.info(f"检测到策略变更，自动重载: {name}")
                            self.reload_strategy(name)

                    except Exception as e:
                        logger.error(f"监控策略文件失败 {name}: {e}")

                time.sleep(interval)

        import threading
        t = threading.Thread(target=_watch_loop, name="StrategyWatcher", daemon=True)
        t.start()
        logger.info(f"策略文件监控已启动 (间隔: {interval}s)")

    def stop_watching(self):
        """停止文件监控"""
        self._watching = False
        logger.info("策略文件监控已停止")

    @property
    def loaded_strategies(self) -> Dict[str, BaseStrategy]:
        """获取所有已加载的策略实例"""
        return {name: info.instance for name, info in self._strategies.items() if info.instance}
