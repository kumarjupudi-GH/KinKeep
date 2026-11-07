import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinkeep_desktop import crypto  # noqa: E402
from kinkeep_desktop.bridge import Bridge  # noqa: E402
from kinkeep_desktop.otp import OtpService  # noqa: E402

crypto.set_kdf_cost(1, 64, 1)  # fast for tests; production cost is checked in test_crypto


class Mailbox:
    """Fake email server: records every message so tests can read the code like a person would."""
    def __init__(self):
        self.sent = []

    def __call__(self, to, subject, body):
        self.sent.append((to, subject, body))

    def last_code(self):
        import re
        return re.search(r"code is (\d{6})", self.sent[-1][2]).group(1)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


PROFILE = dict(first="Asha", last="Rao", email="asha@example.com", dob="1985-04-02", login="asha")
ANSWERS = [{"qi": 0, "answer": "Dosa"}, {"qi": 1, "answer": "Green"}, {"qi": 4, "answer": "Mrs Iyer"}]
PW = "correct horse battery"


@pytest.fixture
def mail():
    return Mailbox()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_bridge(tmp_path, mail, clock):
    def make(folder=None):
        return Bridge(folder or tmp_path / "data", sender=mail, clock=clock, otp_service=OtpService(clock))
    return make


@pytest.fixture
def bridge(make_bridge):
    return make_bridge()


def register(b, mail, pw=PW, **over):
    p = {**PROFILE, "password": pw, "password2": pw, "questions": ANSWERS, "smtp": {}, **over}
    r = b.register_start(p)
    assert r["ok"], r
    v = b.otp_verify(mail.last_code())
    assert v["ok"], v
    return b.register_finish({"start": over.get("start", "empty")})


def signin(b, mail, clock, login="asha", pw=PW):
    r = b.login(login, pw)
    if not r["ok"]:
        return r
    clock.advance(30)
    return b.otp_verify(mail.last_code())


@pytest.fixture
def owner(bridge, mail):
    r = register(bridge, mail)
    assert r["ok"], r
    bridge.recovery_key = r["recoveryKey"]
    return bridge


def add_person(b, name, role, status="Active"):
    st = b.load_state()["state"]
    st["access"].append({"id": "p-" + name.lower(), "name": name, "role": role, "scope": "x", "status": status})
    assert b.save_state(st)["ok"]
    return "p-" + name.lower()
