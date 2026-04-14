"""Web 管理界面 - A股量化交易系统"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import os
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# 配置持久化目录
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_DIR.mkdir(exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "web_config.json"

# 数据目录
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "astock.log"
LOG_FILE.parent.mkdir(exist_ok=True)


def load_web_config():
    """加载持久化的 Web 配置"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_web_config(web_cfg):
    """保存 Web 配置到文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(web_cfg, f, indent=2, ensure_ascii=False)


def merge_config(web_cfg):
    """合并 web 配置和默认 config，web 配置优先"""
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
    merged = merge_config(web_cfg)
    return jsonify(merged)


@app.route("/api/config", methods=["POST"])
def save_config():
    """保存部分配置"""
    data = request.json
    web_cfg = load_web_config()

    # 支持的配置项
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
    return jsonify({"status": "success", "swing_config": swing})


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
        web_cfg["data_sources"] = data["sources"]
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
    # 返回默认配置
    default_stocks = config.LONG_TERM_STOCKS if hasattr(config, "LONG_TERM_STOCKS") else []
    return jsonify(default_stocks)


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

    # 检查是否已存在
    for s in stocks:
        if s["symbol"] == symbol:
            return jsonify({"status": "error", "message": f"{symbol} 已存在"}), 400

    stocks.append({
        "symbol": symbol,
        "name": name,
        "min_capital": capital,
        "added_at": datetime.now().isoformat(),
        "strategy": None,
        "score": None,
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
        "running": False,
        "mode": merged.get("trading_mode", "paper"),
        "long_term_count": lt_count,
        "swing_config": merged.get("swing_config", {}),
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

        # 保存优化结果到长线股
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


# ========== 数据源测试 ==========
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
            dm.register(TushareSource())
        elif source_name == "YahooFinance":
            from data.sources.yahoo_src import YahooSource
            dm.register(YahooSource())

        dm.connect_all()
        df = dm.fetch_daily(symbol, "20240101", "20240331")

        return jsonify({
            "status": "success",
            "source": source_name,
            "rows": len(df),
            "columns": list(df.columns) if not df.empty else [],
            "latest_date": str(df.index[-1]) if not df.empty else "N/A",
        })
    except Exception as e:
        return jsonify({"status": "error", "source": source_name, "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
