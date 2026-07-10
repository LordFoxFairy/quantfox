"""个人投资档案（InvestorMandate-lite）：个性化决策的地基。
字段摘自可信决策核心设计 6.1，去掉一切 validated-模型依赖；
除 schema_version 外全部可选——缺什么就少个性化什么，绝不阻断分析。"""
import datetime as _dt
import json
from pathlib import Path

from .config import data_dir

SCHEMA_VERSION = "1.0"


def mandate_path() -> Path:
    return data_dir() / "mandate.json"


def validate(m: dict) -> list[str]:
    errors = []
    tw, dc = m.get("total_wealth"), m.get("deployable_capital")
    if tw is not None and tw <= 0:
        errors.append("total_wealth 必须 > 0")
    if dc is not None and dc <= 0:
        errors.append("deployable_capital 必须 > 0")
    if tw is not None and dc is not None and dc > tw:
        errors.append("deployable_capital 不得超过 total_wealth")
    for k in ("minimum_cash_reserve", "maximum_loss_amount"):
        v = m.get(k)
        if v is not None and v < 0:
            errors.append(f"{k} 不得为负")
    for k in ("maximum_single_instrument_weight", "maximum_theme_weight"):
        v = m.get(k)
        if v is not None and not (0 < v <= 1):
            errors.append(f"{k} 必须在 (0,1]")
    td, as_of = m.get("target_date"), m.get("mandate_as_of")
    if td:
        try:
            base = _dt.date.fromisoformat(as_of) if as_of else _dt.date.today()
            if _dt.date.fromisoformat(td) <= base:
                errors.append("target_date 必须晚于 mandate_as_of")
        except ValueError:
            errors.append("target_date/mandate_as_of 必须是 YYYY-MM-DD")
    return errors


def save_mandate(m: dict) -> Path:
    errors = validate(m)
    if errors:
        raise ValueError("；".join(errors))
    p = mandate_path()
    if p.exists():
        p.replace(p.with_suffix(".json.bak"))  # 覆盖前留一版
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def load_mandate():
    p = mandate_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def derived(m: dict) -> dict:
    """派生量：能算几个算几个（单标的/主题金额上限、距目标天数）。"""
    out = {}
    dc = m.get("deployable_capital")
    if dc and m.get("maximum_single_instrument_weight"):
        out["single_instrument_amount_cap"] = round(dc * m["maximum_single_instrument_weight"], 2)
    if dc and m.get("maximum_theme_weight"):
        out["theme_amount_cap"] = round(dc * m["maximum_theme_weight"], 2)
    if m.get("target_date") and m.get("mandate_as_of"):
        try:
            out["days_to_target"] = (_dt.date.fromisoformat(m["target_date"])
                                     - _dt.date.fromisoformat(m["mandate_as_of"])).days
        except ValueError:
            pass
    return out
