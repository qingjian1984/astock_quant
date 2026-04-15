#!/bin/bash
# A股量化交易系统 - 统一启动脚本
# 用法: ./run.sh [命令]
#   web       - 启动Web面板
#   backtest  - 运行回测
#   trade     - 启动交易(模拟盘/实盘)
#   test      - 运行测试
#   install   - 安装依赖

set -e
cd "$(dirname "$0")"

# 激活虚拟环境
source venv/bin/activate

case "$1" in
    web)
        echo "启动Web管理面板: http://0.0.0.0:5000"
        python web/app.py
        ;;
    backtest)
        shift
        python backtest/run.py backtest "$@"
        ;;
    trade)
        shift
        python live/run.py "$@"
        ;;
    test)
        python live/test_paper_trading.py
        ;;
    install)
        pip install -r requirements.txt
        pip install -r requirements_web.txt
        echo "依赖安装完成"
        ;;
    *)
        echo "用法: $0 {web|backtest|trade|test|install}"
        echo ""
        echo "示例:"
        echo "  $0 web                    # 启动Web面板"
        echo "  $0 backtest --symbol 000001  # 运行回测"
        echo "  $0 trade --mode paper     # 模拟盘"
        echo "  $0 test                   # 运行测试"
        ;;
esac
