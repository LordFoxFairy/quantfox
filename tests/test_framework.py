from quantfox.prompts import framework_path, framework_version


def test_framework_exists_and_versioned():
    p = framework_path()
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "信号档位" in text
    assert "风险" in text
    assert framework_version() == "8"
