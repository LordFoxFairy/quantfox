import quantfox.schedule_mac as sm


def test_plist_xml_contains_calendar_and_log():
    xml = sm.plist_xml("com.quantfox.weekly", ["/usr/local/bin/quantfox", "gold-report", "--email"],
                       [{"Weekday": 5, "Hour": 21, "Minute": 30}], "/tmp/x.log")
    for frag in ("<key>Label</key>", "com.quantfox.weekly", "<integer>21</integer>",
                 "<integer>30</integer>", "gold-report", "/tmp/x.log",
                 "<key>StandardErrorPath</key>"):
        assert frag in xml


def test_install_writes_two_plists_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path / "home"))
    calls = []
    paths = sm.install(exe="/opt/quantfox", agents_dir=tmp_path / "agents",
                       launchctl=lambda args: calls.append(args))
    names = sorted(p.name for p in paths)
    assert names == ["com.quantfox.patrol.plist", "com.quantfox.weekly.plist"]
    flat = [" ".join(c) for c in calls]
    assert any("load" in s for s in flat) and any("unload" in s for s in flat)
    text = (tmp_path / "agents" / "com.quantfox.patrol.plist").read_text()
    assert "<integer>21</integer>" in text and "patrol" in text


def test_install_intraday_adds_third(tmp_path):
    paths = sm.install(intraday=True, exe="/opt/quantfox", agents_dir=tmp_path / "agents",
                       launchctl=lambda args: None)
    assert any(p.name == "com.quantfox.intraday.plist" for p in paths)


def test_install_without_exe_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)
    try:
        sm.install(agents_dir=tmp_path / "agents", launchctl=lambda a: None)
        assert False, "should raise"
    except RuntimeError as e:
        assert "uv tool install" in str(e)


def test_uninstall_removes(tmp_path):
    sm.install(exe="/opt/quantfox", agents_dir=tmp_path / "agents", launchctl=lambda a: None)
    removed = sm.uninstall(agents_dir=tmp_path / "agents", launchctl=lambda a: None)
    assert len(removed) >= 2 and not list((tmp_path / "agents").glob("com.quantfox.*"))


def test_status_reports_missing(tmp_path):
    st = sm.status(agents_dir=tmp_path / "agents", launchctl=lambda a: "")
    assert st["com.quantfox.weekly"]["installed"] is False
