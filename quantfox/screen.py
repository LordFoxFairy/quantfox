"""全市场多因子深筛（只用榜单的多周期收益列 + 基金名，跑全市场，不逐只抓净值）。

针对"短线1-3月、靠谱、高概率、别追山顶"：
- **已确立赢家**：近1/2/3年一致靠前（趋势成立、非昙花一现）。
- **动能还在**：近3/6月为正；否则降权（短线要动能）。
- **不过热**：近3月抛物线暴涨(>55%)、近1月/3月站在极端顶（超买）→ 重罚 + 标 `overheated`。
- **回调不追高**：近期(近1周)相对温和/小回调的加分——顶准别顶在山顶。
- **去重去集中**：A/C 等份额按同名合并；每个主题限流，避免又是一串半导体。
精筛（估值/RSI/持仓）与舆情由 fund-screener 技能在短名单上做。
"""
import re

import pandas as pd

# 风格：过热惩罚强度 / 回调加分强度
_STYLES = {
    "balanced": {"overheat": 0.6, "pullback": 0.15},   # 默认：动能但不追山顶
    "steady": {"overheat": 1.0, "pullback": 0.10},     # 更怕过热、偏稳
    "momentum": {"overheat": 0.25, "pullback": 0.05},  # 更认动能（仍标过热）
    "pullback": {"overheat": 0.7, "pullback": 0.35},   # 重点找回调买点
}
PARABOLIC_3M = 55.0  # 近3月涨超此值=抛物线，血崩前兆，重罚

_THEME_KW = {
    "半导体/芯片": ["半导体", "芯片", "集成电路", "存储", "专精特新"],
    "AI/算力/科技": ["人工智能", "算力", "数字经济", "软件", "通信", "云计算", "科技", "TMT"],
    "医药医疗": ["医药", "医疗", "生物", "健康", "创新药"],
    "新能源": ["新能源", "光伏", "电池", "锂", "储能", "碳中和"],
    "白酒消费": ["白酒", "消费", "食品", "饮料"],
    "红利/价值/低波": ["红利", "价值", "低波", "股息", "分红"],
    "宽基指数": ["沪深300", "中证500", "中证800", "上证50", "创业板", "科创50", "中证1000", "MSCI"],
    "军工": ["军工", "国防", "航天", "航空"],
    "金融地产": ["银行", "证券", "保险", "地产", "金融"],
    "黄金/资源": ["黄金", "有色", "资源", "煤炭", "石油", "化工"],
    "海外/QDII": ["纳斯达克", "标普", "港股", "恒生", "美国", "全球", "海外", "日经", "德国"],
}


def _theme(name: str) -> str:
    for theme, kws in _THEME_KW.items():
        if any(k in name for k in kws):
            return theme
    return "其它"


def _base_name(name: str) -> str:
    """去份额后缀（A/C/E/联接A…）合并同一只基金的不同份额。"""
    n = re.sub(r"[（(].*?[)）]", "", str(name))
    n = re.sub(r"[ABCEDR]类$", "", n)
    n = re.sub(r"[ABCEDR]$", "", n)
    return n.strip()


def score_universe(df: pd.DataFrame, style: str = "balanced") -> pd.DataFrame:
    cfg = _STYLES.get(style, _STYLES["balanced"])
    w = df.dropna(subset=["r_1y"]).copy()  # 至少要有近1年
    if w.empty:
        return w

    def num(c):
        return pd.to_numeric(w[c], errors="coerce") if c in w.columns else pd.Series(float("nan"), index=w.index)

    def rank(c):
        return num(c).rank(pct=True).fillna(0.5) if c in w.columns else pd.Series(0.5, index=w.index)

    # 已确立赢家：1/2/3年一致靠前
    winner = 0.35 * rank("r_1y") + 0.30 * rank("r_2y") + 0.35 * rank("r_3y")
    p1m, p3m, pw = rank("r_1m"), rank("r_3m"), rank("r_1w")
    r3m = num("r_3m")
    # 过热：站在极端顶（超买）
    overheat = (p1m - 0.85).clip(lower=0) + (p3m - 0.90).clip(lower=0)
    # 回调加分：近期相对冷/小回调
    pullback = (0.5 - pw).clip(lower=0)
    momentum_ok = (num("r_3m") > 0) & (num("r_6m") > 0)

    w["overheated"] = (p3m >= 0.95) | (p1m >= 0.95) | (r3m > PARABOLIC_3M)
    score = 100 * winner + cfg["pullback"] * 100 * pullback - cfg["overheat"] * 100 * overheat
    score = score - w["overheated"].astype(float) * 30      # 抛物线/山顶重罚
    score = score - (~momentum_ok).astype(float) * 15       # 动能不成立降权
    w["score"] = score.round(2)
    w["consistent"] = (rank("r_1y") >= 0.7) & (rank("r_3y") >= 0.7)
    w["theme"] = w["name"].map(_theme)
    w["_base"] = w["name"].map(_base_name)
    return w.sort_values("score", ascending=False).reset_index(drop=True)


def screen(df: pd.DataFrame, top: int = 30, style: str = "balanced",
           per_theme: int = 2, exclude_overheated: bool = False) -> list[dict]:
    ranked = score_universe(df, style)
    if ranked.empty:
        return []
    if exclude_overheated:
        ranked = ranked[~ranked["overheated"]]
    ranked = ranked.drop_duplicates(subset=["_base"], keep="first")  # 合并 A/C
    out, theme_count = [], {}
    cols = ["code", "name", "theme", "score", "overheated", "consistent",
            "r_1m", "r_3m", "r_6m", "r_1y", "r_3y", "fee"]
    for _, r in ranked.iterrows():
        t = r["theme"]
        if theme_count.get(t, 0) >= per_theme:  # 每主题限流，强制分散
            continue
        theme_count[t] = theme_count.get(t, 0) + 1
        out.append({c: r[c] for c in cols if c in ranked.columns})
        if len(out) >= top:
            break
    return out
