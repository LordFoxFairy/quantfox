from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent / ".claude" / "skills" / "fund-analyze"


def test_skill_file_valid():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name:" in text and "description:" in text
    assert "money evidence" in text
    assert "money log-signal" in text
    assert "analysis_framework" in text


def test_skill_standard_structure():
    # 标准 skill 结构：SKILL.md + references/ + scripts/
    assert (SKILL_DIR / "SKILL.md").exists()
    assert (SKILL_DIR / "references" / "evidence-card.md").exists()
    assert (SKILL_DIR / "scripts" / "setup.sh").exists()
