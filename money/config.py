import os
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("MONEY_HOME", Path.home() / ".money"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path() -> Path:
    return data_dir() / "ledger.db"
