"""共享行业主题词表与名实核对启发（evidence C3 与 gold_report 共用，唯一出处）。"""

INDUSTRY_WORDS = ["医疗", "医药", "半导体", "新能源", "白酒", "军工", "科技", "消费",
                  "金融", "地产", "黄金", "芯片", "光伏", "汽车"]


def guess_theme(names):
    """对一组持仓/股票名做行业词计数，返回最高票的词；无命中 None；平票取词表序靠前者。"""
    if not names:
        return None
    counts = {}
    for n in names:
        if not n:
            continue
        for w in INDUSTRY_WORDS:
            if w in n:
                counts[w] = counts.get(w, 0) + 1
    if not counts:
        return None
    return max(INDUSTRY_WORDS, key=lambda w: counts.get(w, 0))


def name_theme_mismatch(name, theme):
    """name 含行业词且该词不在 theme 里 → True；任一侧空 → False。
    theme 既可能是自由文本（screen 的 theme）也可能是词表词（guess_theme 产出），
    用 `w not in (theme or "")` 子串判断以同时兼容两者。"""
    if not name or not theme:
        return False
    for w in INDUSTRY_WORDS:
        if w in name and w not in (theme or ""):
            return True
    return False
