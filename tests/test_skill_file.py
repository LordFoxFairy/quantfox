import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "fund-analyze"


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


def test_publishable_marketplace_manifest():
    # 可发布结构：根目录 .claude-plugin/marketplace.json，且指向该 skill
    mf = ROOT / ".claude-plugin" / "marketplace.json"
    assert mf.exists()
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data["name"]
    assert data["owner"]["name"]
    assert data["plugins"], "至少要有一个 plugin"
    all_skills = [s for p in data["plugins"] for s in p.get("skills", [])]
    assert "./skills/fund-analyze" in all_skills
