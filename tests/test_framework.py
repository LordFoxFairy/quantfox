from quantfox.prompts import framework_path, framework_version


def test_framework_exists_and_versioned():
    p = framework_path()
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "信号档位" in text
    assert "风险" in text
    assert "保本优先" in text
    assert framework_version() == "14"


def test_framework_v14_iron_rules():
    from quantfox.prompts import framework_path, framework_version

    assert framework_version() == "14"
    text = framework_path().read_text(encoding="utf-8")
    for kw in ("诚实铁律", "产物与留痕铁律", "from_similar_valuation", "QUANTFOX_HOME",
               "watch expect", "mandate show", "幸存者偏差"):
        assert kw in text, f"框架缺关键词: {kw}"
