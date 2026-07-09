import re
from pathlib import Path

_PATH = Path(__file__).parent / "analysis_framework.md"


def framework_path() -> Path:
    return _PATH


def framework_version() -> str:
    m = re.search(r"<!--\s*version:\s*(\S+)\s*-->", _PATH.read_text(encoding="utf-8"))
    return m.group(1) if m else "0"
