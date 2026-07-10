"""本地 launchd 调度（macOS）。生成 ~/Library/LaunchAgents 下的 plist：
周报（周五21:30）/ 收盘巡检（工作日21:35）/ 盘中巡检（可选，工作日14:30）。
云端 /schedule 摸不到本地 ~/.quantfox，故只支持本机调度；睡眠错过由 launchd 唤醒后补跑。"""
import platform
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from .config import data_dir

_WEEKDAYS = [1, 2, 3, 4, 5]

JOBS = {
    "com.quantfox.weekly": {"args": ["gold-report", "--email"],
                            "calendar": [{"Weekday": 5, "Hour": 21, "Minute": 30}]},
    "com.quantfox.patrol": {"args": ["patrol", "--email"],
                            "calendar": [{"Weekday": w, "Hour": 21, "Minute": 35} for w in _WEEKDAYS]},
    "com.quantfox.intraday": {"args": ["patrol", "--intraday", "--email"],
                              "calendar": [{"Weekday": w, "Hour": 14, "Minute": 30} for w in _WEEKDAYS]},
}


def _default_launchctl(args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True).stdout


def _default_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_xml(label, program_args, calendar, log_path) -> str:
    def dic(entries):
        inner = "".join(f"<key>{k}</key><integer>{v}</integer>" for k, v in entries.items())
        return f"<dict>{inner}</dict>"

    cal = "".join(dic(c) for c in calendar)
    args = "".join(f"<string>{escape(str(a))}</string>" for a in program_args)
    label = escape(str(label))
    log_path = escape(str(log_path))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array>{args}</array>
<key>StartCalendarInterval</key><array>{cal}</array>
<key>StandardOutPath</key><string>{log_path}</string>
<key>StandardErrorPath</key><string>{log_path}</string>
</dict></plist>
"""


def _jobs(intraday):
    names = ["com.quantfox.weekly", "com.quantfox.patrol"] + (
        ["com.quantfox.intraday"] if intraday else [])
    return {n: JOBS[n] for n in names}


def install(intraday=False, exe=None, agents_dir=None, launchctl=None, log_dir=None):
    if platform.system() != "Darwin" and agents_dir is None:
        raise RuntimeError("仅支持 macOS launchd；其他平台请自行 crontab，例如：30 21 * * 5 quantfox gold-report --email")
    exe = exe or shutil.which("quantfox")
    if not exe:
        raise RuntimeError("找不到 quantfox 可执行文件：先 `uv tool install .` 装成全局命令")
    agents_dir = Path(agents_dir or _default_agents_dir())
    agents_dir.mkdir(parents=True, exist_ok=True)
    launchctl = launchctl or _default_launchctl
    logs = Path(log_dir) if log_dir is not None else data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    written = []
    for label, job in _jobs(intraday).items():
        p = agents_dir / f"{label}.plist"
        p.write_text(plist_xml(label, [exe, *job["args"]], job["calendar"],
                               str(logs / f"{label}.log")), encoding="utf-8")
        launchctl(["unload", str(p)])
        launchctl(["load", "-w", str(p)])
        written.append(p)
    return written


def uninstall(agents_dir=None, launchctl=None):
    agents_dir = Path(agents_dir or _default_agents_dir())
    launchctl = launchctl or _default_launchctl
    removed = []
    for label in JOBS:
        p = agents_dir / f"{label}.plist"
        if p.exists():
            launchctl(["unload", str(p)])
            p.unlink()
            removed.append(p)
    return removed


def status(agents_dir=None, launchctl=None, log_dir=None):
    agents_dir = Path(agents_dir or _default_agents_dir())
    launchctl = launchctl or _default_launchctl
    log_dir = Path(log_dir) if log_dir is not None else data_dir() / "logs"
    loaded = launchctl(["list"]) or ""
    out = {}
    for label in JOBS:
        p = agents_dir / f"{label}.plist"
        log = Path(log_dir) / f"{label}.log"
        tail = ""
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            tail = lines[-1] if lines else ""
        out[label] = {"installed": p.exists(), "loaded": label in loaded, "last_log": tail}
    return out
