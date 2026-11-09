"""The mic buttons use the computer's own dictation; no speech service runs inside the page."""
import pytest

from kinkeep_desktop.bridge import Bridge, Host

pw = pytest.importorskip("playwright.sync_api")
from test_ui_e2e import App, browser  # noqa: E402,F401  (fixtures)
from conftest import Mailbox  # noqa: E402


def make_host(result):
    class H(Host):
        def open_dictation(self):
            if isinstance(result, Exception):
                raise result
            return result
    return H


def test_bridge_reports_whether_the_os_dictation_was_opened(tmp_path):
    for result, expect in ((False, False), (True, True), (RuntimeError("no"), False)):
        b = Bridge(tmp_path / "d", host=make_host(result)(tmp_path / "x"))
        r = b.os_dictation()
        assert r["ok"] and r["opened"] is expect


def test_default_host_does_nothing_and_never_crashes(tmp_path):
    assert Bridge(tmp_path / "d").os_dictation()["opened"] is False


@pytest.fixture
def app(browser, tmp_path):
    a = App(browser, tmp_path / "data", Mailbox())
    yield a
    a.close()


def _text(app, sel):
    return app.pg.inner_text(sel).lower()


def test_page_has_no_cloud_speech_recognition(app):
    app.register()
    assert app.pg.evaluate("typeof window.webkitSpeechRecognition") in ("undefined", "function")  # browser may have it...
    app.pg.click("#fab"); app.pg.click("#mic")
    app.pg.wait_for_timeout(500)
    assert "listening" not in _text(app, "#micState")  # ...but KinKeep never starts it


def test_advisor_mic_focuses_box_and_explains_windows_voice_typing(app):
    app.register()
    app.bridge.host = make_host(True)(app.folder / "x")
    app.pg.click("#fab"); app.pg.click("#mic")
    app.pg.locator("#micState", has_text="should now be open").wait_for(timeout=5000)
    assert "windows voice typing" in _text(app, "#micState")
    assert app.pg.evaluate("document.activeElement && document.activeElement.id") == app.pg.evaluate("document.querySelector('#advisor textarea').id")
    assert app.errors == []


def test_advisor_mic_gives_the_keyboard_shortcut_when_it_cannot_open_it(app):
    app.register()
    app.pg.click("#fab"); app.pg.click("#mic")
    app.pg.wait_for_timeout(600)
    t = _text(app, "#micState")
    assert "windows key + h" in t and "press enter" in t


def test_record_box_mic_works_the_same(app):
    app.register(); app.nav("assets")
    app.pg.click("[data-act=qa-mic][data-coll=assets]")
    app.pg.wait_for_timeout(600)
    assert "windows key + h" in _text(app, "#qa-st-assets")
    assert app.pg.evaluate("document.activeElement.id") == "qa-assets"
    assert app.errors == []


def test_mac_wording(browser, tmp_path):
    a = App(browser, tmp_path / "data", Mailbox())
    try:
        a.ctx.add_init_script("Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'})")
        a.pg.reload()
        a.register()
        a.pg.click("#fab"); a.pg.click("#mic"); a.pg.wait_for_timeout(600)
        t = _text(a, "#micState")
        assert "fn key twice" in t and "mac" in t and "windows" not in t
    finally:
        a.close()
