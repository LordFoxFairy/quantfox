from quantfox.themes import guess_theme, name_theme_mismatch


def test_guess_theme_majority():
    names = ["中芯国际", "北方华创半导体", "半导体ETF", "贵州茅台"]
    assert guess_theme(names) == "半导体"


def test_guess_theme_none_when_no_hit():
    assert guess_theme(["某某股份", "另一公司"]) is None
    assert guess_theme([]) is None


def test_mismatch_semantics():
    assert name_theme_mismatch("示例医疗精选", "半导体") is True
    assert name_theme_mismatch("示例医疗精选", "医疗") is False
    assert name_theme_mismatch(None, "医疗") is False
    assert name_theme_mismatch("示例医疗精选", None) is False
