"""可视化模块"""
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from pathlib import Path
import config

# 配置中文字体
CJK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
import matplotlib.font_manager as fm
fm.fontManager.addfont(CJK_FONT)
prop = fm.FontProperties(fname=CJK_FONT)
plt.rcParams["font.family"] = prop.get_name()
plt.rcParams["axes.unicode_minus"] = False


def plot_equity_curve(equity_df: pd.DataFrame, output_path: str = None):
    """绘制净值曲线 + 回撤"""
    if output_path is None:
        output_path = str(config.PROJECT_ROOT / "results" / "equity_curve.png")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    equity = equity_df.copy()
    equity["date"] = pd.to_datetime(equity["date"])
    equity.set_index("date", inplace=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True)

    # 净值曲线
    equity["equity"].plot(ax=ax1, color="#2196F3", linewidth=1.5)
    ax1.axhline(y=equity["equity"].iloc[0], color="gray", linestyle="--", alpha=0.5, label="初始资金")
    ax1.set_ylabel("净值")
    ax1.set_title("净值曲线")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 回撤
    peak = equity["equity"].cummax()
    drawdown = (equity["equity"] - peak) / peak * 100
    ax2.fill_between(equity.index, drawdown, 0, alpha=0.4, color="#f44336")
    ax2.plot(equity.index, drawdown, color="#f44336", linewidth=1)
    ax2.set_ylabel("回撤 %")
    ax2.set_title("最大回撤")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_trades(equity_df: pd.DataFrame, trades_df: pd.DataFrame, output_path: str = None):
    """绘制净值曲线 + 买卖点"""
    if output_path is None:
        output_path = str(config.PROJECT_ROOT / "results" / "trades.png")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    equity = equity_df.copy()
    equity["date"] = pd.to_datetime(equity["date"])
    equity.set_index("date", inplace=True)

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(equity.index, equity["equity"], color="#2196F3", linewidth=1.5, label="净值")

    if not trades_df.empty:
        buys = trades_df[trades_df["action"] == "buy"]
        sells = trades_df[trades_df["action"] == "sell"]

        has_buy_label = False
        has_sell_label = False
        for _, t in buys.iterrows():
            d = pd.Timestamp(t["date"])
            if d in equity.index:
                ax.scatter(d, equity.loc[d, "equity"], marker="^", color="green", s=80, zorder=5,
                           label="买入" if not has_buy_label else "")
                has_buy_label = True

        for _, t in sells.iterrows():
            d = pd.Timestamp(t["date"])
            if d in equity.index:
                ax.scatter(d, equity.loc[d, "equity"], marker="v", color="red", s=80, zorder=5,
                           label="卖出" if not has_sell_label else "")
                has_sell_label = True

    ax.set_ylabel("净值")
    ax.set_title("交易信号")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_monthly_returns(equity_df: pd.DataFrame, output_path: str = None):
    """绘制月度收益热力图"""
    if output_path is None:
        output_path = str(config.PROJECT_ROOT / "results" / "monthly_returns.png")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    equity = equity_df.copy()
    equity["date"] = pd.to_datetime(equity["date"])
    equity.set_index("date", inplace=True)

    monthly = equity["equity"].resample("ME").last().pct_change() * 100
    monthly = monthly.dropna()

    if len(monthly) == 0:
        return None

    # 构建月度矩阵
    years = sorted(monthly.index.year.unique())
    months = list(range(1, 13))
    data = []
    for y in years:
        row = []
        for m in months:
            vals = monthly[(monthly.index.year == y) & (monthly.index.month == m)]
            if len(vals) > 0:
                row.append(float(vals.iloc[-1]))
            else:
                row.append(None)
        data.append(row)

    df = pd.DataFrame(data, index=[str(y) for y in years],
                      columns=["1月", "2月", "3月", "4月", "5月", "6月",
                               "7月", "8月", "9月", "10月", "11月", "12月"])

    fig, ax = plt.subplots(figsize=(12, max(len(years) * 0.8, 2)))
    im = ax.imshow(df.values.astype(float), cmap="RdYlGn", aspect="auto", vmin=-10, vmax=10)

    for i in range(len(years)):
        for j in range(12):
            val = df.values[i, j]
            if val is not None and not pd.isna(val):
                color = "white" if abs(float(val)) > 5 else "black"
                ax.text(j, i, f"{float(val):.1f}%", ha="center", va="center", color=color, fontsize=9)

    ax.set_xticks(range(12))
    ax.set_xticklabels(df.columns)
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels(df.index)
    ax.set_title("月度收益热力图 (%)")
    plt.colorbar(im, ax=ax, label="收益%")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path
