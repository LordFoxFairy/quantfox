"""邮件推送（用户自配自己的邮箱）。纯标准库 smtplib，无新依赖。

安全：配置存本地 data_dir/config.json（旧 email.json 自动迁移）（在 .gitignore 的 /data 或 ~/.quantfox 下），
不进仓库、不打印密码；文件权限 600。用户填自己邮箱的 SMTP + 授权码（Gmail/163 等需"应用专用密码"）。
"""
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def email_config_path() -> Path:
    from .config import config_path

    return config_path()


def save_email_config(cfg: dict) -> Path:
    from .config import load_config, save_config

    full = load_config()
    full["smtp"] = {k: v for k, v in cfg.items() if k != "notify_to"}
    full.setdefault("notify", {})["to"] = cfg.get("notify_to")
    return save_config(full)


def load_email_config():
    from .config import load_config

    cfg = load_config()
    smtp = cfg.get("smtp") or {}
    if not smtp:
        return None
    return {**smtp, "notify_to": (cfg.get("notify") or {}).get("to")}


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


def send_email(to: str = None, subject: str = "", body: str = "", attach: str = None,
               html: bool = False, config: dict = None) -> dict:
    cfg = config or load_email_config()
    if not cfg:
        raise RuntimeError("邮箱未配置：先运行 quantfox email config ...")
    # 收件人：显式 > 配置里的默认收件人 notify_to。绝不从别处猜。
    to = to or cfg.get("notify_to")
    if not to:
        raise RuntimeError("未指定收件人：给 --to，或先 quantfox email config --to <邮箱> 设默认收件人")
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
