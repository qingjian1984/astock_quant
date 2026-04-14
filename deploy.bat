@echo off
chcp 65001 >nul 2>&1
echo ============================================
echo   A股量化交易系统 - Windows 11 一键部署
echo ============================================
echo.

:: 1. 检查 Python
echo [1/6] 检查 Python...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 未检测到 Python！
    echo.
    echo 安装步骤:
    echo 1. 打开 https://www.python.org/downloads/
    echo 2. 下载 Python 3.10+ (推荐 3.12)
    echo 3. 安装时务必勾选 "Add Python to PATH"
    echo 4. 重新运行此脚本
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] Python %PYVER%

:: 2. 创建虚拟环境
echo [2/6] 创建虚拟环境...
if exist "venv" (
    echo [提示] venv 已存在，跳过创建
) else (
    python -m venv venv
    if %errorLevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [OK] 虚拟环境创建成功
)

:: 3. 激活并升级 pip
echo [3/6] 升级 pip...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo [OK] pip 已升级

:: 4. 安装核心依赖
echo [4/6] 安装核心依赖（可能需要几分钟）...
pip install akshare baostock pandas numpy sqlalchemy loguru matplotlib --quiet
if %errorLevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络
    echo [解决] 手动运行: pip install akshare baostock pandas numpy sqlalchemy loguru matplotlib
    pause
    exit /b 1
)
echo [OK] 核心依赖安装完成

:: 5. 创建目录
echo [5/6] 创建项目目录...
if not exist "results" mkdir results
if not exist "logs" mkdir logs
if not exist "data" mkdir data
echo [OK] 目录创建完成

:: 6. 配置中文字体
echo [6/6] 配置中文字体（matplotlib 绘图用）...
set "FONT_CACHE=%LOCALAPPDATA%\matplotlib"
if exist "%FONT_CACHE%" rmdir /s /q "%FONT_CACHE%" >nul 2>&1
echo [OK] 字体缓存已清理

echo.
echo ============================================
echo   部署完成！
echo ============================================
echo.
echo 使用方法:
echo   1. 激活环境: call venv\Scripts\activate.bat
echo   2. 查看数据源: python backtest\run.py list-sources
echo   3. 运行回测:   python backtest\run.py backtest --symbol 000001
echo   4. 查看结果:   打开 results 文件夹查看图表
echo.
echo 可选依赖:
echo   pip install tushare       # Tushare Pro 数据源
echo   pip install yfinance      # 港股/美股数据
echo.
echo 环境变量（创建 .env 文件填写）:
echo   TUSHARE_TOKEN=xxx         # Tushare Pro token
echo   DINGTALK_WEBHOOK=xxx      # 钉钉告警
echo.
pause
