import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "skills"
EXPECTED = ["fund-analyze", "fund-position", "fund-compare", "fund-portfolio", "fund-review"]


def test_all_skills_valid_frontmatter():
    for name in EXPECTED:
        p = SKILLS / name / "SKILL.md"
        assert p.exists(), f"缺少 {name}/SKILL.md"
        text = p.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert f"name: {name}" in text
        assert "description:" in text


def test_fund_analyze_closed_loop():
    # 主 skill 内部要闭环：取数→评分卡→报告→存档
    text = (SKILLS / "fund-analyze" / "SKILL.md").read_text(encoding="utf-8")
    for cmd in ("money evidence", "money report", "money log-signal"):
        assert cmd in text
    assert "analysis_framework" in text


def test_fund_analyze_has_report_assets():
    assert (SKILLS / "fund-analyze" / "references" / "evidence-card.md").exists()
    assert (SKILLS / "fund-analyze" / "assets" / "report_template.html").exists()
    assert (SKILLS / "fund-analyze" / "scripts" / "setup.sh").exists()


def test_marketplace_lists_all_skills():
    mf = ROOT / ".claude-plugin" / "marketplace.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    listed = [s for p in data["plugins"] for s in p.get("skills", [])]
    for name in EXPECTED:
        assert f"./skills/{name}" in listed
