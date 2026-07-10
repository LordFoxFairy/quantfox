import json
import os
import stat

from quantfox.config import config_path, load_config, reports_dir, save_config


def test_load_config_empty_home(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg["schema_version"] == "1.0"
    assert cfg["smtp"] == {} and cfg["prefs"] == {}


def test_migrates_legacy_email_json(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    legacy = {"smtp_host": "smtp.qq.com", "smtp_port": 465, "username": "a@qq.com",
              "password": "pw", "from_addr": "a@qq.com", "notify_to": "b@qq.com", "use_ssl": True}
    (tmp_path / "email.json").write_text(json.dumps(legacy), encoding="utf-8")
    cfg = load_config()
    assert cfg["smtp"]["smtp_host"] == "smtp.qq.com"
    assert "notify_to" not in cfg["smtp"]
    assert cfg["notify"]["to"] == "b@qq.com"
    assert config_path().exists()  # 迁移后落盘


def test_config_file_permission_0600(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_config({"schema_version": "1.0", "smtp": {"password": "x"}, "notify": {}, "prefs": {}})
    mode = stat.S_IMODE(os.stat(config_path()).st_mode)
    assert mode == 0o600


def test_data_dir_permission_0700(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path / "home"))
    reports_dir()  # 触发创建
    mode = stat.S_IMODE(os.stat(tmp_path / "home").st_mode)
    assert mode == 0o700


def test_reports_dir_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    assert reports_dir() == tmp_path / "reports"
    assert reports_dir().is_dir()
