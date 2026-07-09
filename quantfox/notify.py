"""邮件推送（用户自配自己的邮箱）。纯标准库 smtplib，无新依赖。

安全：配置存本地 data_dir/email.json（在 .gitignore 的 /data 或 ~/.quantfox 下），
不进仓库、不打印密码；文件权限 600。用户填自己邮箱的 SMTP + 授权码（Gmail/163 等需"应用专用密码"）。
"""
import json
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import data_dir


def email_config_path() -> Path:
    return data_dir() / "email.json"


def save_email_config(cfg: dict) -> Path:
    p = email_config_path()
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def load_email_config():
    p = email_config_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build_message(to: str, subject: str, body: str, from_addr: str,
                  attach: str = None, html: bool = False) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    if html:
        msg.set_content("本邮件为 HTML，请用支持 HTML 的客户端查看。")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)
    if attach:
        p = Path(attach)
        data = p.read_bytes()
        if p.suffix.lower() in (".html", ".htm", ".txt"):
            msg.add_attachment(data, maintype="text", subtype="html", filename=p.name)
        else:
            msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=p.name)
    return msg


def send_email(to: str, subject: str, body: str, attach: str = None,
               html: bool = False, config: dict = None) -> dict:
    cfg = config or load_email_config()
    if not cfg:
        raise RuntimeError("邮箱未配置：先运行 quantfox email config ...")
    msg = build_message(to, subject, body, cfg["from_addr"], attach, html)
    ctx = ssl.create_default_context()
    if cfg.get("use_ssl", True):
        with smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), context=ctx) as s:
            s.login(cfg["username"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"])) as s:
            s.starttls(context=ctx)
            s.login(cfg["username"], cfg["password"])
            s.send_message(msg)
    return {"sent_to": to, "subject": subject}
