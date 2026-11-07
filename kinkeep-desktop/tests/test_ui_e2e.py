"""Drives the real UI (headless Chromium) against the real engine over the localhost test bridge."""
import re
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
from conftest import Clock, Mailbox, PW  # noqa: E402
from kinkeep_desktop.otp import OtpService  # noqa: E402
from kinkeep_desktop.app import serve_dev  # noqa: E402
from kinkeep_desktop.bridge import Bridge  # noqa: E402

GROUP = {"assets": "fin", "liab": "fin", "cover": "fin", "docs": "pap", "ids": "pap", "will": "pap", "wish": "fam", "plan": "fam", "drive": "set"}


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # pragma: no cover
            pytest.skip("no Chromium: %s" % e)
        yield b
        b.close()


class App:
    def __init__(self, browser, folder, mail):
        self.mail, self.folder, self.browser, self.clock = mail, folder, browser, Clock()
        self.start()

    def start(self):
        self.bridge = Bridge(self.folder, sender=self.mail, clock=self.clock, otp_service=OtpService(self.clock))
        self.srv, self.url = serve_dev(self.bridge)
        self.new_page()

    def new_page(self):
        self.errors, self.requests = [], []
        self.ctx = self.browser.new_context(viewport={"width": 1300, "height": 900})
        self.pg = self.ctx.new_page()
        self.pg.on("pageerror", lambda e: self.errors.append(str(e)))
        self.pg.on("request", lambda r: self.requests.append(r.url))
        self.pg.goto(self.url)

    def restart(self):
        """Quit and reopen the app: new process state, same data folder."""
        self.clock.advance(120)  # a person takes longer than the 25 s code cooldown to come back
        self.ctx.close(); self.srv.shutdown(); self.start()

    def nav(self, v):
        pg = self.pg
        g = GROUP.get(v)
        if g and not pg.is_visible(f"[data-nav={v}]"):
            pg.click(f"[data-grp={g}]")
        pg.click(f"[data-nav={v}]")

    def register(self):
        pg = self.pg
        pg.wait_for_selector("#r-first")
        for k, v in dict(first="Asha", last="Rao", email="asha@example.com", dob="1985-04-02", user="asha").items():
            pg.fill(f"#r-{k}", v)
        pg.fill("#r-pass", PW); pg.fill("#r-pass2", PW); pg.fill("#r-spass", "app pass word here")
        for i, (q, a) in enumerate([(0, "Dosa"), (1, "Green"), (4, "Mrs Iyer")]):
            pg.select_option(f"#r-q{i}", str(q)); pg.fill(f"#r-a{i}", a)
        pg.click("[data-g=reg-next]"); pg.wait_for_selector("#g-otp")
        pg.fill("#g-otp", self.mail.last_code()); pg.click("[data-g=otp-go]")
        pg.wait_for_selector("[data-g=create]"); pg.click("[data-g=create]"); pg.wait_for_selector("#g-rk")
        self.rk = pg.inner_text("#g-rk")
        pg.check("#g-rk-ack"); pg.click("[data-g=rk-done]"); pg.wait_for_selector("#gate", state="hidden")

    def signin(self, user="asha", pw_=PW):
        pg = self.pg
        pg.wait_for_selector("#g-user")
        pg.fill("#g-user", user); pg.fill("#g-pass", pw_); pg.click("[data-g=login-go]")
        pg.wait_for_selector("#g-otp")
        pg.wait_for_timeout(100)
        pg.fill("#g-otp", self.mail.last_code()); pg.click("[data-g=otp-go]"); pg.wait_for_selector("#gate", state="hidden")

    def close(self):
        self.ctx.close(); self.srv.shutdown()


@pytest.fixture
def app(browser, tmp_path):
    a = App(browser, tmp_path / "data", Mailbox())
    yield a
    a.close()


def msg(app, text):
    app.pg.locator("#g-msg", has_text=text).wait_for(timeout=5000)


def add_asset(app, name, value):
    app.nav("assets")
    f = app.pg.locator("form[data-coll=assets]")
    f.locator("[name=name]").fill(name); f.locator("[name=value]").fill(str(value))
    f.locator("button[type=submit]").first.click()


def test_register_use_every_screen_without_errors(app):
    app.register()
    for v in ["dash", "rem", "emerg", "assets", "liab", "cover", "docs", "ids", "will", "wish", "plan", "drive"]:
        app.nav(v); app.pg.wait_for_timeout(80)
        assert len(app.pg.inner_text("#main")) > 300, v
    assert app.errors == []


def test_page_makes_no_external_requests_and_stores_nothing_in_browser(app):
    app.register(); add_asset(app, "Checking", 100)
    app.pg.wait_for_timeout(900)
    assert all(u.startswith(app.url) or u.startswith("data:") for u in app.requests), [u for u in app.requests if not u.startswith(app.url)]
    assert app.pg.evaluate("localStorage.length") == 0 and app.pg.evaluate("sessionStorage.length") == 0
    assert app.pg.evaluate("indexedDB.databases ? indexedDB.databases().then(d => d.length) : 0") == 0


def test_data_survives_restart_and_needs_password_and_code(app):
    app.register(); add_asset(app, "My Savings", 4321)
    app.pg.wait_for_timeout(1200)  # debounce + save
    app.restart()
    app.pg.wait_for_selector("#g-user")
    assert "My Savings" not in app.pg.content()  # nothing visible before sign-in
    app.pg.fill("#g-user", "asha"); app.pg.fill("#g-pass", PW); app.pg.click("[data-g=login-go]")
    app.pg.wait_for_selector("#g-otp")
    assert app.pg.is_visible("#gate")  # password alone does not open the app
    app.pg.fill("#g-otp", "000000"); app.pg.click("[data-g=otp-go]")
    msg(app, "not right")
    app.pg.fill("#g-otp", app.mail.last_code()); app.pg.click("[data-g=otp-go]"); app.pg.wait_for_selector("#gate", state="hidden")
    app.nav("assets")
    assert "My Savings" in app.pg.inner_text("#main")


def test_lock_clears_screen_and_password_unlocks(app):
    app.register(); add_asset(app, "Hidden Gold", 7)
    app.pg.wait_for_timeout(900)
    app.pg.click("#rail [data-act=st-lock]")
    app.pg.wait_for_selector("#g-pass")
    assert "Hidden Gold" not in app.pg.content()
    app.pg.fill("#g-pass", "wrong"); app.pg.click("[data-g=login-go]")
    msg(app, "not correct")
    app.pg.fill("#g-pass", PW); app.pg.click("[data-g=login-go]"); app.pg.wait_for_selector("#gate", state="hidden")
    app.nav("assets")
    assert "Hidden Gold" in app.pg.inner_text("#main")


def test_files_written_and_spreadsheet_opens(app):
    from kinkeep_desktop import officecrypt, xlsx_io
    app.register(); add_asset(app, "Sheet Row", 55)
    app.pg.wait_for_timeout(1200)
    data, meta = xlsx_io.read_workbook(officecrypt.decrypt((app.folder / "kinkeep.data.xlsx").read_bytes(), PW))
    assert [a["name"] for a in data["assets"]] == ["Sheet Row"]
    assert b"Sheet Row" not in (app.folder / "kinkeep.vault.json").read_bytes()


def test_backup_buttons_write_files(app):
    app.register()
    app.nav("drive"); app.pg.wait_for_selector("[data-act=st-export]")
    app.pg.click("[data-act=st-export]"); app.pg.locator(".logbox", has_text="Saved").wait_for()
    app.pg.click("[data-act=st-export-x]"); app.pg.locator(".logbox", has_text=re.compile(r"Saved[\s\S]*Saved")).wait_for()
    names = [p.name for p in (app.folder / "exports").iterdir()]
    assert any(n.endswith(".kinkeep.json") for n in names) and any(n.endswith(".xlsx") for n in names)


def test_forgot_password_with_recovery_key_in_ui(app):
    app.register(); add_asset(app, "Kept Through Reset", 1); app.pg.wait_for_timeout(1200)
    app.restart(); app.pg.wait_for_selector("#g-user")
    app.pg.click("[data-g=forgot]"); app.pg.wait_for_selector("#f-a0")
    for i, a in enumerate(["dosa", "green", "mrs iyer"]):
        app.pg.fill(f"#f-a{i}", a)
    app.pg.wait_for_timeout(100)
    app.pg.click("[data-g=forgot-go]")
    try:
        app.pg.wait_for_selector("#g-otp", timeout=6000)
    except Exception:
        raise AssertionError("no otp screen: " + app.pg.inner_text("#gate")[:300])
    app.pg.fill("#g-otp", app.mail.last_code()); app.pg.click("[data-g=otp-go]"); app.pg.wait_for_selector("#n-rk"); app.pg.wait_for_timeout(150)
    app.pg.fill("#n-pass", "a completely new password"); app.pg.fill("#n-pass2", "a completely new password"); app.pg.fill("#n-rk", app.rk)
    app.pg.click("[data-g=newpass-go]")
    try:
        app.pg.wait_for_selector("#gate", state="hidden", timeout=8000)
    except Exception:
        raise AssertionError("gate still shown: %r rk=%r" % (app.pg.inner_html("#gate")[-600:], app.rk))
    app.nav("assets")
    assert "Kept Through Reset" in app.pg.inner_text("#main")


def test_viewer_sees_read_only_screens(app):
    app.register()
    b = app.bridge
    st = b.load_state()["state"]
    st["access"].append({"id": "v1", "name": "Vera Viewer", "role": "Viewer", "scope": "", "status": "Active"})
    st["assets"].append({"id": "a1", "name": "Family Bank", "type": "Bank", "owner": "A", "country": "US", "currency": "USD", "value": 1, "date": "", "source": "Statement"})
    b.save_state(st); assert b.member_add("v1", "vera", "vera@example.com", "vera long password")["ok"]
    app.pg.wait_for_timeout(300)
    app.pg.click("#rail [data-act=st-lock]"); app.pg.wait_for_selector("#g-pass")
    app.pg.click("[data-g=signout]"); app.pg.wait_for_selector("#g-user")
    app.pg.fill("#g-user", "vera"); app.pg.fill("#g-pass", "vera long password"); app.pg.click("[data-g=login-go]")
    app.pg.wait_for_selector("#g-otp"); app.pg.fill("#g-otp", app.mail.last_code()); app.pg.click("[data-g=otp-go]"); app.pg.wait_for_selector("#gate", state="hidden")
    nav = app.pg.inner_text("#rail")
    assert "Finance" not in nav and "Will and Trust" not in nav  # Viewer has no finance or legacy screens
    app.nav("docs")
    assert app.pg.locator("form[data-coll=docs]").count() == 0 or not app.pg.locator("form[data-coll=docs]").first.is_visible()
    assert "cannot change" in app.pg.inner_text("#main")
    app.nav("drive")
    txt = app.pg.inner_text("#main")
    assert "Change my password" in txt and "Recovery key" not in txt and "Backup copies" not in txt and "Family sign-ins" not in txt
    assert app.errors == []
