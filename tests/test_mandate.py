import json

import pytest

from quantfox.mandate import derived, load_mandate, mandate_path, save_mandate


def _base():
    return {"schema_version": "1.0", "mandate_as_of": "2026-07-10", "currency": "CNY",
            "total_wealth": 100000.0, "deployable_capital": 60000.0,
            "target_date": "2027-02-10", "target_net_return": 0.08,
            "maximum_loss_amount": 10000.0, "maximum_single_instrument_weight": 0.2,
            "maximum_theme_weight": 0.35}


def test_save_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    assert load_mandate() is None
    save_mandate(_base())
    assert load_mandate()["deployable_capital"] == 60000.0


def test_save_backs_up_previous(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_mandate(_base())
    m2 = _base()
    m2["deployable_capital"] = 50000.0
    save_mandate(m2)
    bak = json.loads(mandate_path().with_suffix(".json.bak").read_text(encoding="utf-8"))
    assert bak["deployable_capital"] == 60000.0


def test_partial_mandate_ok(monkeypatch, tmp_path):
    # 字段可部分缺省：只给可投金额也合法
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_mandate({"schema_version": "1.0", "mandate_as_of": "2026-07-10",
                  "deployable_capital": 30000.0})
    assert load_mandate()["deployable_capital"] == 30000.0


def test_save_defaults_schema_version(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_mandate({"deployable_capital": 30000.0})
    assert load_mandate()["schema_version"] == "1.0"


def test_validation_rejects_bad_values(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    bad = _base()
    bad["deployable_capital"] = 200000.0  # 超过 total_wealth
    with pytest.raises(ValueError):
        save_mandate(bad)
    bad2 = _base()
    bad2["target_date"] = "2020-01-01"  # 早于 mandate_as_of
    with pytest.raises(ValueError):
        save_mandate(bad2)
    bad3 = _base()
    bad3["maximum_single_instrument_weight"] = 1.5  # 比率出界
    with pytest.raises(ValueError):
        save_mandate(bad3)


def test_derived_caps():
    d = derived(_base())
    assert d["single_instrument_amount_cap"] == 12000.0   # 60000*0.2
    assert d["theme_amount_cap"] == 21000.0               # 60000*0.35
    assert d["days_to_target"] == 215
