import json
import os
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("QUANTFOX_HOME", Path.home() / ".quantfox"))
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def ledger_path() -> Path:
    return data_dir() / "ledger.db"


def reports_dir() -> Path:
    d = data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def save_config(cfg: dict) -> Path:
    p = config_path()
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)  # 含 SMTP 授权码，只允许本用户读
    except OSError:
        pass
    return p


def load_config() -> dict:
    """统一配置入口。首次读取若只有旧 email.json 则自动迁移生成 config.json。"""
    p = config_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    legacy = data_dir() / "email.json"
    if legacy.exists():
        smtp = json.loads(legacy.read_text(encoding="utf-8"))
        cfg = {"schema_version": "1.0",
               "smtp": {k: v for k, v in smtp.items() if k != "notify_to"},
               "notify": {"to": smtp.get("notify_to")},
               "prefs": {}}
        save_config(cfg)
        return cfg
    return {"schema_version": "1.0", "smtp": {}, "notify": {}, "prefs": {}}
