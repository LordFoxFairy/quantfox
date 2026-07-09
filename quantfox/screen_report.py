"""把全市场深筛结果渲染成"初筛报告"（自包含 HTML，可转 PDF 发邮件）。

含：大盘估值(B2) + 主题分布 + Top-k 表格(过热标红) + 相对分≠能买 的免责。
表格是静态的（PDF/邮箱都能看，不依赖 JS）。风险列(估值/回撤)留给短名单二级精筛，不首屏全拉。
"""
import html as _html
from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parent / "assets" / "screen_report_template.html"


def _pct(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f'<span class="{"pos" if v >= 0 else "neg"}">{v:+.1f}%</span>'


def build_screen_report(candidates: list, meta: dict) -> str:
    rows = []
    for i, c in enumerate(candidates, 1):
        oh = c.get("overheated")
        rows.append(
            f'<tr class="{"oh" if oh else ""}">'
            f'<td>{i}</td>'
            f'<td class="l">{_html.escape(str(c.get("code", "")))}</td>'
            f'<td class="l">{_html.escape(str(c.get("name", "")))}</td>'
            f'<td class="l">{_html.escape(str(c.get("theme", "")))}</td>'
            f'<td class="score">{c.get("score", "")}</td>'
            f'<td>{"<span class=oh-tag>⚠️山顶</span>" if oh else ""}</td>'
            f'<td>{_pct(c.get("r_1m"))}</td><td>{_pct(c.get("r_3m"))}</td>'
            f'<td>{_pct(c.get("r_6m"))}</td><td>{_pct(c.get("r_1y"))}</td>'
            f'<td>{_pct(c.get("r_3y"))}</td>'
            f'<td>{_html.escape(str(c.get("fee", "") or ""))}</td></tr>')

    mv = meta.get("market_valuation") or {}
    market = ""
    if mv.get("available"):
        market = (f'<b>大盘估值</b>：全A近10年 {mv.get("percentile_10y", 0) * 100:.0f}% 分位'
                  f'（{mv.get("level", "")}）&nbsp;&nbsp;&nbsp;')
    theme = meta.get("theme_spread") or {}
    theme_str = "<b>主题分布</b>：" + (" · ".join(f"{k}×{v}" for k, v in theme.items()) or "—")
    footer = ('深筛分是"相对分"（幸存者里动能质量最好），<b>≠ 现在能买</b>；⚠️山顶=站在超买/抛物线，别追。'
              "须再逐只精筛（估值分位/RSI/回撤/持仓）+ 舆情。幸存者偏差：榜单只含仍存续的基金。"
              "过去收益≠未来收益；非投资建议，决策与风险自负。 · 生成：" + str(meta.get("generated_at", "")))

    return (_TEMPLATE.read_text(encoding="utf-8")
            .replace("__TITLE__", _html.escape(meta.get("title", "全市场深筛报告")))
            .replace("__SUBTITLE__", _html.escape(meta.get("subtitle", "")))
            .replace("__MARKET__", market)
            .replace("__THEME__", theme_str)
            .replace("__ROWS__", "".join(rows))
            .replace("__FOOTER__", footer))
