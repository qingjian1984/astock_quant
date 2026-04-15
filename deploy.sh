#!/bin/bash
# A股量化交易系统 - Linux 部署脚本
# 用法: ./deploy.sh [install|start|stop|restart|status|test|paper|live]

set -e

# 配置
APP_NAME="astock_quant"
APP_DIR="/opt/data/workspace/astock_quant"
LOG_DIR="$APP_DIR/logs"
PID_DIR="$APP_DIR/pids"
VENV_DIR="$APP_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查依赖
check_dependencies() {
    log_info "检查系统依赖..."

    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装"
        exit 1
    fi

    if ! command -v git &> /dev/null; then
        log_warn "Git 未安装，跳过 git 操作"
    fi

    log_info "依赖检查完成"
}

# 创建虚拟环境
setup_venv() {
    log_info "创建虚拟环境..."

    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
        log_info "虚拟环境创建成功"
    else
        log_info "虚拟环境已存在"
    fi

    # 升级 pip
    $PIP install --upgrade pip -q
}

# 安装依赖
install_dependencies() {
    log_info "安装项目依赖..."

    # 核心依赖
    $PIP install -r "$APP_DIR/requirements.txt" -q
    log_info "核心依赖安装完成"

    # Web 依赖
    $PIP install -r "$APP_DIR/requirements_web.txt" -q
    log_info "Web 依赖安装完成"

    # 可选：vnpy（实盘需要）
    read -p "是否安装 vnpy（实盘交易需要）? [y/N]: " install_vnpy
    if [[ $install_vnpy =~ ^[Yy]$ ]]; then
        log_info "安装 vnpy..."
        $PIP install vnpy vnpy-ctp -q
        log_info "vnpy 安装完成"
    fi
}

# 创建必要目录
setup_directories() {
    log_info "创建必要目录..."

    mkdir -p "$LOG_DIR"
    mkdir -p "$PID_DIR"
    mkdir -p "$APP_DIR/config"
    mkdir -p "$APP_DIR/data"
    mkdir -p "$APP_DIR/results"

    log_info "目录创建完成"
}

# 安装
install() {
    log_info "===== 开始安装 A股量化交易系统 ====="

    check_dependencies
    setup_venv
    install_dependencies
    setup_directories

    log_info "===== 安装完成 ====="
    log_info "运行测试: ./deploy.sh test"
    log_info "启动模拟盘: ./deploy.sh paper"
    log_info "启动 Web 面板: ./deploy.sh web"
}

# 启动模拟盘
start_paper() {
    log_info "启动模拟盘..."

    cd "$APP_DIR"

    # 检查是否已在运行
    if [ -f "$PID_DIR/paper.pid" ]; then
        pid=$(cat "$PID_DIR/paper.pid")
        if ps -p $pid > /dev/null 2>&1; then
            log_warn "模拟盘已在运行 (PID: $pid)"
            return 1
        fi
    fi

    # 启动
    nohup $PYTHON live/run.py --mode paper > "$LOG_DIR/paper.log" 2>&1 &
    echo $! > "$PID_DIR/paper.pid"

    log_info "模拟盘已启动 (PID: $(cat $PID_DIR/paper.pid))"
    log_info "日志: tail -f $LOG_DIR/paper.log"
}

# 启动实盘
start_live() {
    log_warn "===== 警告：即将启动实盘交易 ====="
    log_warn "请确认已完成模拟盘验证并了解风险"

    read -p "是否确认启动实盘？[y/N]: " confirm
    if [[ ! $confirm =~ ^[Yy]$ ]]; then
        log_info "取消启动"
        return 1
    fi

    log_info "启动实盘..."

    cd "$APP_DIR"

    # 检查是否已在运行
    if [ -f "$PID_DIR/live.pid" ]; then
        pid=$(cat "$PID_DIR/live.pid")
        if ps -p $pid > /dev/null 2>&1; then
            log_warn "实盘已在运行 (PID: $pid)"
            return 1
        fi
    fi

    # 启动
    nohup $PYTHON live/run.py --mode live > "$LOG_DIR/live.log" 2>&1 &
    echo $! > "$PID_DIR/live.pid"

    log_info "实盘已启动 (PID: $(cat $PID_DIR/live.pid))"
    log_info "日志: tail -f $LOG_DIR/live.log"
}

# 启动 Web 面板
start_web() {
    log_info "启动 Web 管理面板..."

    cd "$APP_DIR"

    # 检查是否已在运行
    if [ -f "$PID_DIR/web.pid" ]; then
        pid=$(cat "$PID_DIR/web.pid")
        if ps -p $pid > /dev/null 2>&1; then
            log_warn "Web 面板已在运行 (PID: $pid)"
            return 1
        fi
    fi

    # 启动
    nohup $PYTHON web/app.py > "$LOG_DIR/web.log" 2>&1 &
    echo $! > "$PID_DIR/web.pid"

    log_info "Web 面板已启动 (PID: $(cat $PID_DIR/web.pid))"
    log_info "访问: http://localhost:5000"
    log_info "日志: tail -f $LOG_DIR/web.log"
}

# 停止
stop() {
    local mode=$1
    local pid_file="$PID_DIR/${mode}.pid"

    if [ ! -f "$pid_file" ]; then
        log_warn "${mode} 未运行"
        return 1
    fi

    pid=$(cat "$pid_file")
    if ps -p $pid > /dev/null 2>&1; then
        log_info "停止 ${mode} (PID: $pid)..."
        kill $pid
        sleep 2

        # 检查是否已停止
        if ps -p $pid > /dev/null 2>&1; then
            log_warn "强制停止..."
            kill -9 $pid
        fi

        log_info "${mode} 已停止"
    else
        log_warn "${mode} 进程不存在"
    fi

    rm -f "$pid_file"
}

# 状态
status() {
    log_info "===== 系统状态 ====="

    for mode in paper live web; do
        pid_file="$PID_DIR/${mode}.pid"
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            if ps -p $pid > /dev/null 2>&1; then
                log_info "${mode}: 运行中 (PID: $pid)"
            else
                log_warn "${mode}: 进程不存在 (清理 PID)"
                rm -f "$pid_file"
            fi
        else
            log_info "${mode}: 未运行"
        fi
    done
}

# 运行测试
run_test() {
    log_info "运行系统测试..."

    cd "$APP_DIR"
    $PYTHON live/test_paper_trading.py
}

# 重启
restart() {
    local mode=$1
    stop $mode
    sleep 2
    start_$mode
}

# 显示日志
show_logs() {
    local mode=$1
    local log_file="$LOG_DIR/${mode}.log"

    if [ -f "$log_file" ]; then
        tail -f "$log_file"
    else
        log_error "日志文件不存在: $log_file"
    fi
}

# 主函数
main() {
    local action=${1:-help}

    case $action in
        install)
            install
            ;;
        start)
            start_paper
            ;;
        start-paper)
            start_paper
            ;;
        start-live)
            start_live
            ;;
        start-web)
            start_web
            ;;
        paper)
            start_paper
            ;;
        live)
            start_live
            ;;
        web)
            start_web
            ;;
        stop)
            stop paper
            stop live
            stop web
            ;;
        stop-paper)
            stop paper
            ;;
        stop-live)
            stop live
            ;;
        stop-web)
            stop web
            ;;
        restart)
            restart paper
            restart live
            restart web
            ;;
        restart-paper)
            restart paper
            ;;
        restart-live)
            restart live
            ;;
        restart-web)
            restart web
            ;;
        status)
            status
            ;;
        test)
            run_test
            ;;
        logs)
            show_logs ${2:-paper}
            ;;
        help|*)
            echo "A股量化交易系统 - 部署脚本"
            echo ""
            echo "用法: ./deploy.sh [command]"
            echo ""
            echo "命令:"
            echo "  install         安装系统"
            echo "  paper           启动模拟盘"
            echo "  live            启动实盘"
            echo "  web             启动 Web 面板"
            echo "  stop            停止所有服务"
            echo "  status          查看服务状态"
            echo "  test            运行系统测试"
            echo "  logs [mode]     查看日志 (paper|live|web)"
            echo "  help            显示帮助"
            ;;
    esac
}

main "$@"
