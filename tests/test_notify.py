from quantfox.notify import build_message, load_email_config, save_email_config


def test_config_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    assert load_email_config() is None
    cfg = {"smtp_host": "smtp.gmail.com", "smtp_port": 465, "username": "me@x.com",
           "password": "app-pw", "from_addr": "me@x.com", "use_ssl": True}
    p = save_email_config(cfg)
    assert p.exists()
    assert load_email_config()["from_addr"] == "me@x.com"


def test_build_message_plain():
    msg = build_message("you@x.com", "标题", "正文内容", "me@x.com")
    assert msg["To"] == "you@x.com"
    assert msg["From"] == "me@x.com"
    assert msg["Subject"] == "标题"
    assert "正文内容" in msg.get_content()


def test_build_message_html_with_attach(tmp_path):
    f = tmp_path / "report.html"
    f.write_text("<h1>报告</h1>", encoding="utf-8")
    msg = build_message("you@x.com", "报告", "<b>hi</b>", "me@x.com", attach=str(f), html=True)
    assert msg.is_multipart()
    filenames = [part.get_filename() for part in msg.iter_attachments()]
    assert "report.html" in filenames
