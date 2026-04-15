"""Web 管理界面 - A股量化交易系统"""
from flask import Flask, render_template, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
import json
import os
import threading
import uuid
import time
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ========== 目录 ==========
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_DIR.mkdir(exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "web_config.json"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "astock.log"
LOG_FILE.parent.mkdir(exist_ok=True)

# ========== 回测任务管理 ==========
_backtest_tasks = {}  # {task_id: {status, progress, stats, error, log}}
_backtest_lock = threading.Lock()

# ========== 波段股运行状态 ==========
_swing_state = {
    "running": False,
    "task": None,
    "log": [],
    "last_scan": None,
    "candidates": [],
    "positions": [],
    "start_time": None,
    "scan_count": 0,
    "trade_count": 0,
}
_swing_lock = threading.Lock()


def _run_backtest_task(task_id, params):
    """后台执行回测任务"""
    try:
        from backtest.run import run_backtest, STRATEGIES, get_data_manager

        with _backtest_lock:
            _backtest_tasks[task_id]["status"] = "running"
            _backtest_tasks[task_id]["progress"] = 10
            _backtest_tasks[task_id]["log"].append(f"开始回测: {params}")

        symbols = [s.strip() for s in params["symbols"].split(",") if s.strip()]
        strategy_name = params.get("strategy", "ma_cross")
        initial_capital = float(params.get("capital", 1000000))
        slippage = float(params.get("slippage", 0.001))
        source = params.get("source") or None

        with _backtest_lock:
            _backtest_tasks[task_id]["log"].append(
                f"策略: {strategy_name}, 标的: {symbols}, 资金: {initial_capital:,.0f}")
            _backtest_tasks[task_id]["progress"] = 20

        stats = run_backtest(
            symbols=symbols,
            start=params.get("start", "20240101"),
            end=params.get("end", "20241231"),
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            slippage=slippage,
            plot=True,
            source=source,
        )

        with _backtest_lock:
            _backtest_tasks[task_id]["progress"] = 100
            if stats:
                _backtest_tasks[task_id]["status"] = "completed"
                _backtest_tasks[task_id]["stats"] = stats
                _backtest_tasks[task_id]["log"].append("回测完成!")

                # 读取生成的结果文件
                trades_file = RESULTS_DIR / "trades.csv"
                equity_file = RESULTS_DIR / "equity.csv"
                if trades_file.exists():
                    import pandas as pd
                    tdf = pd.read_csv(trades_file)
                    _backtest_tasks[task_id]["trades"] = tdf.to_dict("records")
                if equity_file.exists():
                    import pandas as pd
                    edf = pd.read_csv(equity_file)
                    _backtest_tasks[task_id]["equity"] = edf.to_dict("records")
            else:
                _backtest_tasks[task_id]["status"] = "error"
                _backtest_tasks[task_id]["error"] = "回测无结果"
                _backtest_tasks[task_id]["log"].append("回测无结果")

    except Exception as e:
        with _backtest_lock:
            _backtest_tasks[task_id]["status"] = "error"
            _backtest_tasks[task_id]["error"] = str(e)
            _backtest_tasks[task_id]["progress"] = 0
            _backtest_tasks[task_id]["log"].append(f"错误: {e}")


# ========== 配置持久化 ==========
def load_web_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_web_config(web_cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(web_cfg, f, indent=2, ensure_ascii=False)


def merge_config(web_cfg):
    defaults = {
        "trading_mode": config.TRADING_MODE,
        "long_term_stocks": config.LONG_TERM_STOCKS if hasattr(config, "LONG_TERM_STOCKS") else [],
        "swing_config": {
            "scan_interval": 3600,
            "max_positions": 5,
            "strategies": ["ma_cross", "macd"],
            "stop_loss_pct": -0.05,
            "take_profit_pct": 0.10,
        },
        "trade_limits": config.DAILY_LIMITS,
        "trade_params": config.TRADE_CONFIG,
        "risk_params": config.RISK_CONFIG,
        "data_sources": config.DATA_SOURCES,
        "broker_config": config.BROKER_CONFIG,
    }
    merged = defaults.copy()
    for key, val in web_cfg.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


# ========== 页面 ==========
@app.route("/")
def index():
    return render_template("index.html")


# ========== 配置 API ==========
@app.route("/api/config")
def get_config():
    web_cfg = load_web_config()
    return jsonify(merge_config(web_cfg))


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.json
    web_cfg = load_web_config()
    allowed_keys = ["trading_mode", "swing_config", "trade_limits",
                    "trade_params", "risk_params", "data_sources", "broker_config"]
    for key in allowed_keys:
        if key in data:
            web_cfg[key] = data[key]
    save_web_config(web_cfg)
    return jsonify({"status": "success", "message": "配置已保存"})


@app.route("/api/config/trading_mode", methods=["POST"])
def save_trading_mode():
    data = request.json
    web_cfg = load_web_config()
    web_cfg["trading_mode"] = data.get("mode", "paper")
    save_web_config(web_cfg)
    return jsonify({"status": "success", "mode": web_cfg["trading_mode"]})


@app.route("/api/config/swing", methods=["POST"])
def save_swing_config():
    data = request.json
    web_cfg = load_web_config()
    swing = web_cfg.get("swing_config", {})
    swing.update({
        "scan_interval": int(data.get("scan_interval", 3600)),
        "max_positions": int(data.get("max_positions", 5)),
        "strategies": [s.strip() for s in data.get("strategies", "ma_cross,macd").split(",") if s.strip()],
        "stop_loss_pct": float(data.get("stop_loss_pct", -0.05)),
        "take_profit_pct": float(data.get("take_profit_pct", 0.10)),
    })
    web_cfg["swing_config"] = swing
    save_web_config(web_cfg)
    
    # 记录配置变更日志
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _swing_lock:
        _swing_state["log"].append(f"[{ts}] 波段配置已更新: 扫描间隔={swing['scan_interval']}s, 最大持仓={swing['max_positions']}, 策略={swing['strategies']}, 止损={swing['stop_loss_pct']:.0%}, 止盈={swing['take_profit_pct']:.0%}")
        # 保持日志最近 200 条
        if len(_swing_state["log"]) > 200:
            _swing_state["log"] = _swing_state["log"][-200:]
    
    return jsonify({"status": "success", "swing_config": swing})


# ========== 波段股运行管理 ==========
def _run_swing_engine():
    """后台运行波段股扫描引擎"""
    try:
        from data.manager import DataSourceManager
        from data.sources.baostock_src import BaoStockSource
        from live.scanner import StockScanner
        from live.trader import TradeSimulator
        from strategy.ma_cross import MACrossStrategy
        from strategy.macd import MACDStrategy
        from strategy.rsi import RSIStrategy
        import config as sys_config
        
        web_cfg = load_web_config()
        merged = merge_config(web_cfg)
        swing_cfg = merged.get("swing_config", {})
        
        scan_interval = swing_cfg.get("scan_interval", 3600)
        max_positions = swing_cfg.get("max_positions", 5)
        strategies = swing_cfg.get("strategies", ["ma_cross", "macd"])
        stop_loss = swing_cfg.get("stop_loss_pct", -0.05)
        take_profit = swing_cfg.get("take_profit_pct", 0.10)
        
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _swing_lock:
            _swing_state["log"].append(f"[{ts}] 波段引擎启动 - 扫描间隔: {scan_interval}s, 策略: {strategies}")
            _swing_state["start_time"] = datetime.now().isoformat()
            _swing_state["scan_count"] = 0
            _swing_state["trade_count"] = 0
        
        # 初始化数据源
        dm = DataSourceManager()
        dm.register(BaoStockSource())
        dm.connect_all()
        
        # 初始化扫描器
        scanner = StockScanner(dm)
        
        # 策略映射
        strat_map = {
            "ma_cross": lambda: MACrossStrategy(fast=5, slow=20),
            "macd": lambda: MACDStrategy(fast=12, slow=26, signal=9),
            "rsi": lambda: RSIStrategy(period=14),
        }
        
        # 获取股票池 (简化版，取部分股票)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _swing_lock:
            _swing_state["log"].append(f"[{ts}] 正在获取股票池...")
        
        stock_pool = ["000001", "000002", "000063", "000100", "000157", "000333",
                      "000568", "000651", "000725", "000858", "002027", "002049",
                      "002230", "002304", "002352", "002415", "002475", "002594",
                      "300015", "300059", "300750", "600000", "600016", "600028",
                      "600030", "600031", "600036", "600048", "600050", "600104",
                      "600276", "600309", "600519", "600585", "600887", "601012",
                      "601166", "601318", "601398", "601668", "601857", "603288"]
        
        with _swing_lock:
            _swing_state["log"].append(f"[{ts}] 股票池: {len(stock_pool)} 只股票")
        
        # 运行扫描
        candidates = []
        for strat_name in strategies:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with _swing_lock:
                _swing_state["log"].append(f"[{ts}] 使用 {strat_name} 策略扫描...")
                _swing_state["scan_count"] += 1
            
            strat_func = strat_map.get(strat_name)
            if not strat_func:
                continue
            
            strat = strat_func()
            scan_results = []
            
            for symbol in stock_pool[:20]:  # 每次扫描前20只
                try:
                    end_date = datetime.now().strftime("%Y%m%d")
                    start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
                    df = dm.fetch_daily(symbol, start_date, end_date)
                    if df.empty or len(df) < 30:
                        continue
                    
                    # 快速信号检测
                    from backtest.engine import BacktestEngine
                    engine = BacktestEngine(strat_func(), initial_capital=100000)
                    engine.run({symbol: df})
                    trades = engine.get_trades()
                    
                    if not trades.empty:
                        last_trade = trades.iloc[-1]
                        if last_trade["action"] == "buy":
                            scan_results.append({
                                "symbol": symbol,
                                "strategy": strat_name,
                                "reason": f"{strat_name} 买入信号",
                            })
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            with _swing_lock:
                                _swing_state["log"].append(f"[{ts}] 📈 {symbol} - {strat_name} 发出买入信号")
                except Exception as e:
                    pass
            
            candidates.extend(scan_results)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with _swing_lock:
                _swing_state["log"].append(f"[{ts}] {strat_name} 扫描完成，发现 {len(scan_results)} 只候选")
        
        # 更新候选列表
        with _swing_lock:
            _swing_state["candidates"] = candidates[:max_positions]
            _swing_state["last_scan"] = datetime.now().isoformat()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _swing_state["log"].append(f"[{ts}] 扫描完成，共 {len(candidates)} 只候选股票")
        
    except Exception as e:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _swing_lock:
            _swing_state["log"].append(f"[{ts}] ❌ 波段引擎异常: {str(e)}")
    finally:
        with _swing_lock:
            _swing_state["running"] = False
            _swing_state["task"] = None
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _swing_state["log"].append(f"[{ts}] 波段引擎已停止")


@app.route("/api/swing/status")
def swing_status():
    """获取波段股运行状态"""
    with _swing_lock:
        return jsonify({
            "running": _swing_state["running"],
            "last_scan": _swing_state["last_scan"],
            "candidates": _swing_state["candidates"],
            "positions": _swing_state["positions"],
            "start_time": _swing_state["start_time"],
            "scan_count": _swing_state["scan_count"],
            "trade_count": _swing_state["trade_count"],
            "log": _swing_state["log"][-50:],  # 最近50条日志
        })


@app.route("/api/swing/run", methods=["POST"])
def swing_run():
    """启动波段股扫描"""
    with _swing_lock:
        if _swing_state["running"]:
            return jsonify({"status": "error", "message": "波段引擎正在运行中"})
        
        _swing_state["running"] = True
        _swing_state["log"].append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 启动波段扫描...")
        
        t = threading.Thread(target=_run_swing_engine, daemon=True)
        t.start()
        _swing_state["task"] = t
    
    return jsonify({"status": "success", "message": "波段扫描已启动"})


@app.route("/api/swing/stop", methods=["POST"])
def swing_stop():
    """停止波段股扫描"""
    with _swing_lock:
        if not _swing_state["running"]:
            return jsonify({"status": "error", "message": "波段引擎未在运行"})
        
        _swing_state["running"] = False
        _swing_state["log"].append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏹ 手动停止波段扫描")
    
    return jsonify({"status": "success", "message": "波段扫描已停止"})


@app.route("/api/swing/log")
def swing_log():
    """获取波段股运行日志"""
    with _swing_lock:
        return jsonify({
            "running": _swing_state["running"],
            "log": _swing_state["log"][-100:],
        })


@app.route("/api/config/limits", methods=["POST"])
def save_trade_limits():
    data = request.json
    web_cfg = load_web_config()
    limits = web_cfg.get("trade_limits", config.DAILY_LIMITS.copy())
    for key in config.DAILY_LIMITS.keys():
        if key in data:
            limits[key] = int(data[key])
    web_cfg["trade_limits"] = limits
    save_web_config(web_cfg)
    return jsonify({"status": "success", "trade_limits": limits})


@app.route("/api/config/trade_params", methods=["POST"])
def save_trade_params():
    data = request.json
    web_cfg = load_web_config()
    params = web_cfg.get("trade_params", config.TRADE_CONFIG.copy())
    for key in config.TRADE_CONFIG.keys():
        if key in data:
            params[key] = float(data[key])
    web_cfg["trade_params"] = params
    save_web_config(web_cfg)
    return jsonify({"status": "success", "trade_params": params})


@app.route("/api/config/risk", methods=["POST"])
def save_risk_config():
    data = request.json
    web_cfg = load_web_config()
    risk = web_cfg.get("risk_params", config.RISK_CONFIG.copy())
    for key in config.RISK_CONFIG.keys():
        if key in data:
            if key == "blacklist":
                risk[key] = data[key] if isinstance(data[key], list) else []
            else:
                risk[key] = float(data[key])
    web_cfg["risk_params"] = risk
    save_web_config(web_cfg)
    return jsonify({"status": "success", "risk_params": risk})


@app.route("/api/config/data_sources", methods=["POST"])
def save_data_sources():
    data = request.json
    web_cfg = load_web_config()
    if "sources" in data:
        existing = web_cfg.get("data_sources", config.DATA_SOURCES)
        for src in data["sources"]:
            for ex in existing:
                if ex["name"] == src["name"]:
                    ex["enabled"] = src.get("enabled", ex.get("enabled", True))
                    break
        web_cfg["data_sources"] = existing
    if "tushare_token" in data:
        web_cfg["tushare_token"] = data["tushare_token"]
    save_web_config(web_cfg)
    return jsonify({"status": "success", "data_sources": web_cfg.get("data_sources", config.DATA_SOURCES)})


# ========== 长线股管理 ==========
@app.route("/api/longterm", methods=["GET"])
def get_long_term():
    long_term_file = DATA_DIR / "long_term_stocks.json"
    if long_term_file.exists():
        with open(long_term_file, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify(config.LONG_TERM_STOCKS if hasattr(config, "LONG_TERM_STOCKS") else [])


@app.route("/api/longterm", methods=["POST"])
def add_long_term():
    data = request.json
    symbol = data.get("symbol", "")
    name = data.get("name", "")
    capital = data.get("capital", 100000)
    long_term_file = DATA_DIR / "long_term_stocks.json"
    stocks = []
    if long_term_file.exists():
        with open(long_term_file, "r", encoding="utf-8") as f:
            stocks = json.load(f)
    for s in stocks:
        if s["symbol"] == symbol:
            return jsonify({"status": "error", "message": f"{symbol} 已存在"}), 400
    stocks.append({
        "symbol": symbol, "name": name, "min_capital": capital,
        "added_at": datetime.now().isoformat(), "strategy": None, "score": None,
    })
    with open(long_term_file, "w", encoding="utf-8") as f:
        json.dump(stocks, f, indent=2, ensure_ascii=False)
    return jsonify({"status": "success", "stocks": stocks})


@app.route("/api/longterm", methods=["DELETE"])
def remove_long_term():
    data = request.json
    symbol = data.get("symbol", "")
    long_term_file = DATA_DIR / "long_term_stocks.json"
    if long_term_file.exists():
        with open(long_term_file, "r", encoding="utf-8") as f:
            stocks = json.load(f)
        stocks = [s for s in stocks if s["symbol"] != symbol]
        with open(long_term_file, "w", encoding="utf-8") as f:
            json.dump(stocks, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "success", "stocks": stocks})
    return jsonify({"status": "error", "message": "文件不存在"}), 404


# ========== 状态 ==========
@app.route("/api/status")
def get_status():
    web_cfg = load_web_config()
    merged = merge_config(web_cfg)
    long_term_file = DATA_DIR / "long_term_stocks.json"
    lt_count = len(merged.get("long_term_stocks", []))
    if long_term_file.exists():
        with open(long_term_file, "r", encoding="utf-8") as f:
            lt_count = len(json.load(f))
    return jsonify({
        "running": False, "mode": merged.get("trading_mode", "paper"),
        "long_term_count": lt_count, "swing_config": merged.get("swing_config", {}),
        "trade_limits": merged.get("trade_limits", {}),
        "risk_params": merged.get("risk_params", {}),
    })


# ========== 日志 ==========
@app.route("/api/logs")
def get_logs():
    lines = request.args.get("lines", 200, type=int)
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return jsonify({"logs": all_lines[-lines:]})
    return jsonify({"logs": ["暂无日志文件"]})


# ========== 策略优化 ==========
@app.route("/api/optimize", methods=["POST"])
def run_optimize():
    try:
        from core.optimizer import StrategyOptimizer
        from data.manager import DataSourceManager
        from data.sources.baostock_src import BaoStockSource
        data = request.json
        symbol = data.get("symbol", "000001")
        dm = DataSourceManager()
        dm.register(BaoStockSource())
        dm.connect_all()
        df = dm.fetch_daily(symbol, "20200101", "20241231")
        if df.empty:
            return jsonify({"status": "error", "message": "无法获取数据"}), 400
        optimizer = StrategyOptimizer()
        result = optimizer.optimize(symbol, df)
        long_term_file = DATA_DIR / "long_term_stocks.json"
        stocks = []
        if long_term_file.exists():
            with open(long_term_file, "r", encoding="utf-8") as f:
                stocks = json.load(f)
        for s in stocks:
            if s["symbol"] == symbol:
                s["strategy"] = result.get("strategy")
                s["score"] = result.get("score")
                s["optimized_at"] = datetime.now().isoformat()
                break
        with open(long_term_file, "w", encoding="utf-8") as f:
            json.dump(stocks, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ========== 数据源 ==========
@app.route("/api/data_sources/test", methods=["POST"])
def test_data_source():
    data = request.json
    source_name = data.get("source", "AKShare")
    symbol = data.get("symbol", "000001")
    try:
        from data.manager import DataSourceManager
        dm = DataSourceManager()
        if source_name == "AKShare":
            from data.sources.akshare_src import AKShareSource
            dm.register(AKShareSource())
        elif source_name == "BaoStock":
            from data.sources.baostock_src import BaoStockSource
            dm.register(BaoStockSource())
        elif source_name == "Tushare":
            from data.sources.tushare_src import TushareSource
            dm.register(TushareSource(token=config.TUSHARE_TOKEN))
        elif source_name == "YahooFinance":
            from data.sources.yahoo_src import YahooFinanceSource
            dm.register(YahooFinanceSource())
        dm.connect_all()
        df = dm.fetch_daily(symbol, "20240101", "20240331")
        return jsonify({
            "status": "success", "source": source_name,
            "rows": len(df), "columns": list(df.columns) if not df.empty else [],
            "latest_date": str(df.index[-1]) if not df.empty else "N/A",
        })
    except Exception as e:
        return jsonify({"status": "error", "source": source_name, "message": str(e)}), 500


@app.route("/api/data_sources/list")
def list_data_sources():
    """列出所有数据源状态"""
    try:
        from data.manager import DataSourceManager
        dm = DataSourceManager()
        web_cfg = load_web_config()
        merged = merge_config(web_cfg)
        for ds_cfg in merged.get("data_sources", config.DATA_SOURCES):
            if not ds_cfg.get("enabled"):
                continue
            name = ds_cfg["name"]
            if name == "AKShare":
                from data.sources.akshare_src import AKShareSource
                dm.register(AKShareSource(retry=config.AKSHARE_RETRY))
            elif name == "BaoStock":
                from data.sources.baostock_src import BaoStockSource
                dm.register(BaoStockSource())
            elif name == "Tushare" and config.TUSHARE_TOKEN:
                from data.sources.tushare_src import TushareSource
                dm.register(TushareSource(token=config.TUSHARE_TOKEN))
            elif name == "YahooFinance":
                from data.sources.yahoo_src import YahooFinanceSource
                dm.register(YahooFinanceSource())

        sources_info = []
        for s in dm.list_sources():
            sources_info.append({
                "name": s.name,
                "priority": s.priority,
                "available": s.is_available(),
            })
        return jsonify({"status": "success", "sources": sources_info})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/data_sources/compare", methods=["POST"])
def compare_data_sources():
    """对比多个数据源的数据质量"""
    try:
        from data.manager import DataSourceManager
        data = request.json
        symbol = data.get("symbol", "000001")
        start = data.get("start", "20240101")
        end = data.get("end", "20241231")

        dm = DataSourceManager()
        web_cfg = load_web_config()
        merged = merge_config(web_cfg)
        for ds_cfg in merged.get("data_sources", config.DATA_SOURCES):
            if not ds_cfg.get("enabled"):
                continue
            name = ds_cfg["name"]
            if name == "AKShare":
                from data.sources.akshare_src import AKShareSource
                dm.register(AKShareSource(retry=config.AKSHARE_RETRY))
            elif name == "BaoStock":
                from data.sources.baostock_src import BaoStockSource
                dm.register(BaoStockSource())
            elif name == "Tushare" and config.TUSHARE_TOKEN:
                from data.sources.tushare_src import TushareSource
                dm.register(TushareSource(token=config.TUSHARE_TOKEN))
            elif name == "YahooFinance":
                from data.sources.yahoo_src import YahooFinanceSource
                dm.register(YahooFinanceSource())

        dm.connect_all()
        comparison = dm.compare_sources(symbol, start, end)
        if comparison.empty:
            return jsonify({"status": "error", "message": "无可用数据"})
        return jsonify({
            "status": "success",
            "comparison": comparison.to_dict("records"),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ========== 回测 API ==========
@app.route("/api/backtest/strategies")
def get_strategies():
    """获取可用策略列表"""
    return jsonify({
        "strategies": [
            {"name": "ma_cross", "label": "双均线策略", "desc": "MA5上穿MA20买入，下穿卖出", "params": {"fast": [3, 10], "slow": [15, 30]}},
            {"name": "rsi", "label": "RSI均值回归", "desc": "RSI<30超卖买入，>70超买卖出", "params": {"period": [10, 21]}},
            {"name": "macd", "label": "MACD趋势跟踪", "desc": "DIF上穿DEA买入，下穿卖出", "params": {"fast": [8, 15], "slow": [21, 30], "signal": [5, 12]}},
            {"name": "multi_factor", "label": "多因子选股", "desc": "动量+波动率+成交量综合评分", "params": {"top_n": [3, 10], "rebalance_days": [10, 30]}},
        ],
        "data_sources": [s["name"] for s in config.DATA_SOURCES if s.get("enabled")],
    })


@app.route("/api/backtest/run", methods=["POST"])
def start_backtest():
    """启动回测任务"""
    data = request.json
    task_id = str(uuid.uuid4())[:8]
    with _backtest_lock:
        _backtest_tasks[task_id] = {
            "status": "pending", "progress": 0, "stats": None,
            "error": None, "log": [], "trades": None, "equity": None,
            "created_at": datetime.now().isoformat(),
            "params": data,
        }
    t = threading.Thread(target=_run_backtest_task, args=(task_id, data), daemon=True)
    t.start()
    return jsonify({"status": "started", "task_id": task_id})


@app.route("/api/backtest/status/<task_id>")
def backtest_status(task_id):
    """查询回测任务状态"""
    with _backtest_lock:
        task = _backtest_tasks.get(task_id)
    if not task:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    return jsonify({
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "stats": task["stats"],
        "error": task["error"],
        "log": task["log"][-20:],
        "trades_count": len(task["trades"]) if task["trades"] else 0,
        "equity_count": len(task["equity"]) if task["equity"] else 0,
    })


@app.route("/api/backtest/result/<task_id>")
def backtest_result(task_id):
    """获取回测完整结果"""
    with _backtest_lock:
        task = _backtest_tasks.get(task_id)
    if not task:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    if task["status"] != "completed":
        return jsonify({"status": "error", "message": f"任务未完成: {task['status']}"}), 400

    # 分页返回交易记录
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    trades = task.get("trades") or []
    equity = task.get("equity") or []

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    return jsonify({
        "status": "success",
        "task_id": task_id,
        "stats": task["stats"],
        "trades": trades[start_idx:end_idx],
        "trades_total": len(trades),
        "equity": equity,
        "params": task["params"],
    })


# ========== 历史回测结果 ==========
@app.route("/api/backtest/history")
def backtest_history():
    """列出历史回测结果文件"""
    if not RESULTS_DIR.exists():
        return jsonify({"files": []})
    files = []
    for f in RESULTS_DIR.iterdir():
        if f.is_file():
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "type": f.suffix,
            })
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({"files": files})


@app.route("/api/results/<filename>")
def serve_result_file(filename):
    """提供结果文件下载/查看"""
    filepath = RESULTS_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "文件不存在"}), 404
    if filename.endswith(".csv"):
        import pandas as pd
        df = pd.read_csv(filepath)
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 100, type=int)
        total = len(df)
        start = (page - 1) * per_page
        end = start + per_page
        return jsonify({
            "columns": list(df.columns),
            "data": df.iloc[start:end].to_dict("records"),
            "total": total,
            "page": page,
            "per_page": per_page,
        })
    elif filename.endswith(".png"):
        return send_file(filepath, mimetype="image/png")
    return send_file(filepath)


@app.route("/api/results/images")
def result_images():
    """列出结果图片"""
    if not RESULTS_DIR.exists():
        return jsonify({"images": []})
    images = []
    for f in RESULTS_DIR.glob("*.png"):
        images.append({
            "name": f.name,
            "url": f"/api/results/{f.name}",
        })
    return jsonify({"images": images})


# ========== 股票列表 ==========
# 内置股票代码映射表 (备用方案，避免外部API超时)
BUILTIN_STOCK_LIST = [
    {"symbol": "000001", "name": "平安银行"}, {"symbol": "000002", "name": "万 科Ａ"},
    {"symbol": "000063", "name": "中兴通讯"}, {"symbol": "000100", "name": "TCL科技"},
    {"symbol": "000157", "name": "中联重科"}, {"symbol": "000333", "name": "美的集团"},
    {"symbol": "000568", "name": "泸州老窖"}, {"symbol": "000651", "name": "格力电器"},
    {"symbol": "000725", "name": "京东方Ａ"}, {"symbol": "000858", "name": "五 粮 液"},
    {"symbol": "002027", "name": "分众传媒"}, {"symbol": "002049", "name": "紫光国微"},
    {"symbol": "002230", "name": "科大讯飞"}, {"symbol": "002304", "name": "洋河股份"},
    {"symbol": "002352", "name": "顺丰控股"}, {"symbol": "002415", "name": "海康威视"},
    {"symbol": "002475", "name": "立讯精密"}, {"symbol": "002594", "name": "比亚迪"},
    {"symbol": "002714", "name": "牧原股份"}, {"symbol": "300015", "name": "爱尔眼科"},
    {"symbol": "300059", "name": "东方财富"}, {"symbol": "300322", "name": "硕贝德"},
    {"symbol": "300450", "name": "先导智能"}, {"symbol": "300750", "name": "宁德时代"},
    {"symbol": "600000", "name": "浦发银行"}, {"symbol": "600009", "name": "上海机场"},
    {"symbol": "600016", "name": "民生银行"}, {"symbol": "600018", "name": "上港集团"},
    {"symbol": "600028", "name": "中国石化"}, {"symbol": "600030", "name": "中信证券"},
    {"symbol": "600031", "name": "三一重工"}, {"symbol": "600036", "name": "招商银行"},
    {"symbol": "600048", "name": "保利发展"}, {"symbol": "600050", "name": "中国联通"},
    {"symbol": "600104", "name": "上汽集团"}, {"symbol": "600111", "name": "北方稀土"},
    {"symbol": "600196", "name": "复星医药"}, {"symbol": "600276", "name": "恒瑞医药"},
    {"symbol": "600309", "name": "万华化学"}, {"symbol": "600436", "name": "片仔癀"},
    {"symbol": "600438", "name": "通威股份"}, {"symbol": "600519", "name": "贵州茅台"},
    {"symbol": "600585", "name": "海螺水泥"}, {"symbol": "600588", "name": "用友网络"},
    {"symbol": "600690", "name": "海尔智家"}, {"symbol": "600745", "name": "闻泰科技"},
    {"symbol": "600809", "name": "山西汾酒"}, {"symbol": "600887", "name": "伊利股份"},
    {"symbol": "600900", "name": "长江电力"}, {"symbol": "601012", "name": "隆基绿能"},
    {"symbol": "601088", "name": "中国神华"}, {"symbol": "601166", "name": "兴业银行"},
    {"symbol": "601225", "name": "陕西煤业"}, {"symbol": "601288", "name": "农业银行"},
    {"symbol": "601318", "name": "中国平安"}, {"symbol": "601398", "name": "工商银行"},
    {"symbol": "601601", "name": "中国太保"}, {"symbol": "601628", "name": "中国人寿"},
    {"symbol": "601668", "name": "中国建筑"}, {"symbol": "601669", "name": "中国电建"},
    {"symbol": "601766", "name": "中国中车"}, {"symbol": "601816", "name": "京沪高铁"},
    {"symbol": "601857", "name": "中国石油"}, {"symbol": "601888", "name": "中国中免"},
    {"symbol": "601899", "name": "紫金矿业"}, {"symbol": "601919", "name": "中远海控"},
    {"symbol": "601985", "name": "中国核电"}, {"symbol": "601988", "name": "中国银行"},
    {"symbol": "603259", "name": "药明康德"}, {"symbol": "603288", "name": "海天味业"},
    {"symbol": "603501", "name": "韦尔股份"}, {"symbol": "603799", "name": "华友钴业"},
    {"symbol": "603986", "name": "兆易创新"}, {"symbol": "605117", "name": "德业股份"},
]

@app.route("/api/stocks", methods=["GET"])
def get_stock_list():
    """获取股票列表 (内置表 + 外部API 降级)"""
    import threading
    import concurrent.futures
    
    limit = request.args.get("limit", 5000, type=int)
    
    # 快速返回内置列表 (不阻塞)
    stocks = BUILTIN_STOCK_LIST[:limit]
    
    # 后台尝试从外部API加载 (不阻塞响应)
    def _fetch_external():
        try:
            from data.manager import DataSourceManager
            from data.sources.baostock_src import BaoStockSource
            dm = DataSourceManager()
            dm.register(BaoStockSource())
            dm.connect_all()
            external_list = dm.fetch_stock_list()
            if not external_list.empty:
                # 更新内置缓存
                global BUILTIN_STOCK_LIST
                external_stocks = external_list.head(5000).to_dict("records")
                if len(external_stocks) > len(BUILTIN_STOCK_LIST):
                    BUILTIN_STOCK_LIST = external_stocks
        except Exception:
            pass  # 静默失败，不影响前端
    
    # 启动后台线程加载外部数据
    t = threading.Thread(target=_fetch_external, daemon=True)
    t.start()
    
    return jsonify({
        "status": "success",
        "total": len(stocks),
        "stocks": stocks,
    })


# ========== 数据下载 ==========
@app.route("/api/data/fetch", methods=["POST"])
def fetch_data():
    """手动下载股票数据"""
    try:
        from data.manager import DataSourceManager
        data = request.json
        symbol = data.get("symbol", "000001")
        start = data.get("start", "20240101")
        end = data.get("end", "20241231")

        dm = DataSourceManager()
        web_cfg = load_web_config()
        merged = merge_config(web_cfg)
        for ds_cfg in merged.get("data_sources", config.DATA_SOURCES):
            if not ds_cfg.get("enabled"):
                continue
            name = ds_cfg["name"]
            if name == "AKShare":
                from data.sources.akshare_src import AKShareSource
                dm.register(AKShareSource(retry=config.AKSHARE_RETRY))
            elif name == "BaoStock":
                from data.sources.baostock_src import BaoStockSource
                dm.register(BaoStockSource())
            elif name == "Tushare" and config.TUSHARE_TOKEN:
                from data.sources.tushare_src import TushareSource
                dm.register(TushareSource(token=config.TUSHARE_TOKEN))
        dm.connect_all()
        df = dm.fetch_daily(symbol, start, end)
        if df.empty:
            return jsonify({"status": "error", "message": "未获取到数据"})
        return jsonify({
            "status": "success",
            "symbol": symbol,
            "rows": len(df),
            "start_date": str(df.index[0]),
            "end_date": str(df.index[-1]),
            "columns": list(df.columns),
            "preview": df.head(5).to_dict("records"),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ========== 批量回测 ==========
@app.route("/api/backtest/batch", methods=["POST"])
def batch_backtest():
    """批量回测多个策略"""
    data = request.json
    symbols = [s.strip() for s in data.get("symbols", "000001").split(",") if s.strip()]
    strategies = data.get("strategies", ["ma_cross", "rsi", "macd"])
    start = data.get("start", "20240101")
    end = data.get("end", "20241231")
    capital = float(data.get("capital", 1000000))

    try:
        from backtest.run import run_backtest
        results = []
        for strategy in strategies:
            stats = run_backtest(
                symbols=symbols, start=start, end=end,
                strategy_name=strategy, initial_capital=capital,
                plot=False,
            )
            if stats:
                results.append({"strategy": strategy, "stats": stats})
        return jsonify({"status": "success", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
