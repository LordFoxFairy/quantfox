import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "skills"
EXPECTED = ["fund-analyze", "fund-screener", "fund-compare", "fund-watch", "position-sizer", "portfolio-manager", "signal-postmortem"]


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
    for cmd in ("quantfox evidence", "quantfox report", "quantfox log-signal"):
        assert cmd in text
    assert "analysis_framework" in text


def test_fund_analyze_has_report_assets():
    assert (SKILLS / "fund-analyze" / "references" / "evidence-card.md").exists()
    assert (SKILLS / "fund-analyze" / "scripts" / "setup.sh").exists()
    # 报告模板/echarts 已打进 Python 包，全局安装也能用
    assert (ROOT / "quantfox" / "assets" / "report_template.html").exists()
    assert (ROOT / "quantfox" / "assets" / "echarts.min.js").exists()


def test_marketplace_lists_all_skills():
    mf = ROOT / ".claude-plugin" / "marketplace.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    listed = [s for p in data["plugins"] for s in p.get("skills", [])]
    for name in EXPECTED:
        assert f"./skills/{name}" in listed


def test_honesty_matrix_all_skills():
    # 7 skill × 铁律关键词全覆盖（grep 矩阵验收，spec §3）
    keywords = ["中位", "0.85", "幸存者偏差", "from_similar_valuation", "QUANTFOX_HOME", "mandate", "v16"]
    for name in EXPECTED:
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        for kw in keywords:
            assert kw in text, f"{name}/SKILL.md 缺铁律关键词: {kw}"


def test_fund_screener_expectation_calibration():
    # 第 0 步诉求校准
    text = (SKILLS / "fund-screener" / "SKILL.md").read_text(encoding="utf-8")
    assert "诉求校准" in text, "fund-screener/SKILL.md 缺第 0 步诉求校准"


def test_fund_analyze_theme_guess():
    # 名实核对与 theme_guess 消费
    text = (SKILLS / "fund-analyze" / "SKILL.md").read_text(encoding="utf-8")
    assert "theme_guess" in text, "fund-analyze/SKILL.md 缺 theme_guess 说明"


def test_forecast_step_in_analysis_skills():
    # 涉及"要不要买/持有"判断的 skill 必须有前瞻步骤
    for name in ("fund-analyze", "fund-screener", "fund-watch", "fund-compare", "portfolio-manager"):
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert "quantfox forecast" in text, f"{name}/SKILL.md 缺 quantfox forecast 步骤"
