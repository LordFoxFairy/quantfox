from pathlib import Path


def test_skill_file_valid():
    p = Path(__file__).parent.parent / ".claude" / "skills" / "fund-analyze" / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name:" in text and "description:" in text
    assert "money evidence" in text
    assert "money log-signal" in text
    assert "analysis_framework" in text
