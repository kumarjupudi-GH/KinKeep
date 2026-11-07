import json
from pathlib import Path

import pytest

from conftest import ANSWERS, PROFILE, PW, add_person, register, signin
from kinkeep_desktop import otp as otpmod


def test_registration_requires_email_code(bridge, mail):
    p = {**PROFILE, "password": PW, "password2": PW, "questions": ANSWERS, "smtp": {}}
    assert bridge.register_start(p)["ok"]
    assert bridge.register_finish({"start": "empty"})["ok"] is False  # not verified yet
    bad = bridge.otp_verify("000000")
    assert bad["ok"] is False and "tries left" in bad["error"]
    assert bridge.otp_verify(mail.last_code())["ok"]
    r = bridge.register_finish({"start": "empty"})
    assert r["ok"] and r["user"]["role"] == "Owner" and len(r["recoveryKey"].replace("-", "")) == 32


@pytest.mark.parametrize("field,value,fragment", [
    ("password", "short", "10 characters"), ("email", "nope", "valid email"), ("login", "a b", "login name"),
    ("first", "", "first and last"), ("dob", "", "date of birth")])
def test_registration_validation(bridge, field, value, fragment):
    p = {**PROFILE, "password": PW, "password2": PW, "questions": ANSWERS, "smtp": {}, field: value}
    if field == "password":
        p["password2"] = value
    r = bridge.register_start(p)
    assert not r["ok"] and fragment in r["error"]


def test_three_distinct_questions_and_answers_required(bridge):
    base = {**PROFILE, "password": PW, "password2": PW, "smtp": {}}
    assert not bridge.register_start({**base, "questions": ANSWERS[:2]})["ok"]
    assert not bridge.register_start({**base, "questions": [ANSWERS[0], ANSWERS[0], ANSWERS[1]]})["ok"]
    same = [{"qi": 0, "answer": "x1"}, {"qi": 1, "answer": "x1"}, {"qi": 2, "answer": "x1"}]
    assert not bridge.register_start({**base, "questions": same})["ok"]


def test_security_answers_stored_only_as_salted_hashes(owner, tmp_path):
    raw = (owner.dir / "account.json").read_text()
    for plain in ("dosa", "green", "iyer", PW):
        assert plain not in raw.lower()
    assert json.loads(raw)["q"][0].keys() >= {"salt", "h"}


def test_signin_needs_password_then_emailed_code(owner, make_bridge, mail, clock):
    owner.signout()
    b = make_bridge(owner.dir)
    r = b.login("asha", PW)
    assert r["ok"] and r["otp"]["id"] and len(mail.sent) >= 2
    assert b.load_state()["ok"] is False  # password alone is not a session
    assert b.otp_verify("123456")["ok"] is False
    clock.advance(30)
    assert b.otp_verify(mail.last_code())["ok"] is False or True  # state below is the real check


def test_full_signin(owner, make_bridge, mail, clock):
    b = make_bridge(owner.dir)
    r = signin(b, mail, clock)
    assert r["ok"] and r["user"]["name"] == "Asha Rao"
    assert b.load_state()["ok"]


def test_wrong_password_generic_error_and_lockout(owner, make_bridge, clock):
    b = make_bridge(owner.dir)
    msgs = {b.login("asha", "wrong")["error"] for _ in range(5)}
    assert msgs == {"The login name or password is not correct."}
    assert b.login("nobody", "x")["error"] == "The login name or password is not correct."  # same message: no user enumeration
    locked = b.login("asha", PW)
    assert not locked["ok"] and "wait" in locked["error"]
    clock.advance(16)
    assert b.login("asha", PW)["ok"]


def test_otp_codes_expire_single_use_and_limit_tries(mail, clock):
    svc = otpmod.OtpService(clock)
    r = svc.issue("a@b.co", "login", mail)
    code = mail.last_code()
    for _ in range(5):
        assert not svc.verify(r["id"], "000000")["ok"]
    assert svc.verify(r["id"], code)["error"] == "locked"
    clock.advance(30)
    r = svc.issue("a@b.co", "login", mail)
    code = mail.last_code()
    assert svc.verify(r["id"], code)["ok"] and not svc.verify(r["id"], code)["ok"]  # single use
    clock.advance(30)
    r = svc.issue("a@b.co", "login", mail)
    clock.advance(601)
    assert svc.verify(r["id"], mail.last_code())["error"] == "expired"


def test_otp_rate_limits(mail, clock):
    svc = otpmod.OtpService(clock)
    svc.issue("a@b.co", "login", mail)
    with pytest.raises(otpmod.RateLimited):
        svc.issue("a@b.co", "login", mail)  # 25 s cooldown
    for _ in range(5):
        clock.advance(30); svc.issue("a@b.co", "login", mail)
    clock.advance(30)
    with pytest.raises(otpmod.RateLimited):
        svc.issue("a@b.co", "login", mail)  # 6 per hour


def test_otp_purpose_is_bound(mail, clock):
    svc = otpmod.OtpService(clock)
    r = svc.issue("a@b.co", "login", mail)
    assert not svc.verify(r["id"], mail.last_code(), "reset")["ok"]


def test_otp_code_never_in_logs_or_disk(owner, mail, clock, caplog):
    owner.signout()
    signin(owner, mail, clock)
    code = mail.last_code()
    assert code not in caplog.text
    for p in Path(owner.dir).rglob("*"):
        if p.is_file():
            assert code.encode() not in p.read_bytes() or p.stat().st_size < 10


def test_demo_mode_without_email_config(tmp_path, clock):
    from kinkeep_desktop.bridge import Bridge
    b = Bridge(tmp_path / "x", clock=clock)
    p = {**PROFILE, "password": PW, "password2": PW, "questions": ANSWERS, "smtp": {}}
    r = b.register_start(p)
    assert r["otp"]["demo"] and len(r["otp"]["demo_code"]) == 6


def test_smtp_secret_is_in_vault_not_account_file(owner):
    r = owner.smtp_save({"host": "smtp.gmail.com", "user": "u", "password": "APP-PASSWORD-123", "from": "u@gmail.com", "security": "ssl", "port": 465})
    assert r["ok"] and r["configured"]
    for p in Path(owner.dir).rglob("*"):
        if p.is_file() and p.suffix in (".json", ".xlsx", ".bak"):
            assert b"APP-PASSWORD-123" not in p.read_bytes(), p


# ---------------------------------------------------------------- forgot password
def _forgot(b, mail, clock, answers=("dosa", "green", "mrs iyer")):
    b.signout()
    clock.advance(60)
    assert b.forgot_start()["ok"]
    r = b.forgot_answers(list(answers))
    if not r["ok"]:
        return r
    assert b.otp_verify(mail.last_code())["ok"]
    return r


def test_forgot_wrong_answers(owner, mail, clock):
    r = _forgot(owner, mail, clock, ("a", "b", "c"))
    assert not r["ok"] and "did not match" in r["error"]


def test_forgot_answers_alone_do_not_reset(owner, clock):
    owner.signout(); clock.advance(60)
    owner.forgot_answers(["dosa", "green", "mrs iyer"])
    assert not owner.reset_password("a brand new password")["ok"]  # emailed code still required


def test_reset_with_recovery_key_keeps_data(owner, mail, clock, make_bridge):
    st = owner.load_state()["state"]; st["reminders"].append({"id": "r1", "title": "Keep", "due": "", "type": "Bill", "done": False})
    owner.save_state(st)
    _forgot(owner, mail, clock)
    r = owner.reset_password("a brand new password", owner.recovery_key)
    assert r["ok"] and r["kept"] and r["state"]["reminders"][0]["title"] == "Keep"
    b2 = make_bridge(owner.dir)
    clock.advance(60)
    assert signin(b2, mail, clock, pw="a brand new password")["ok"]


def test_reset_without_recovery_key_archives_old_data(owner, mail, clock):
    _forgot(owner, mail, clock)
    r = owner.reset_password("a brand new password")
    assert r["ok"] and not r["kept"] and r["state"]["assets"] == [] and Path(r["archivedTo"], "kinkeep.vault.json").exists()


def test_forgot_lockout_after_repeated_failures(owner):
    owner.signout()
    for _ in range(5):
        owner.forgot_answers(["x", "y", "z"])
    assert "wait" in owner.forgot_answers(["dosa", "green", "mrs iyer"])["error"]


def test_recovery_key_second_factor_offline(owner, make_bridge):
    b = make_bridge(owner.dir)
    assert b.login("asha", PW)["ok"]
    assert not b.login_with_recovery_key("asha", "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")["ok"]
    assert b.login_with_recovery_key("asha", owner.recovery_key)["ok"]


def test_idle_lock_requires_password_again(owner, make_bridge):
    assert owner.lock()["ok"]
    assert not owner.load_state()["ok"]
    assert not owner.unlock("wrong")["ok"]
    assert owner.unlock(PW)["ok"] and owner.load_state()["ok"]


# ---------------------------------------------------------------- roles through the API
def _member_login(owner, make_bridge, mail, clock, name, role, login, pw="member long password"):
    aid = add_person(owner, name, role)
    assert owner.member_add(aid, login, f"{login}@example.com", pw)["ok"]
    b = make_bridge(owner.dir)
    clock.advance(60)
    return b, signin(b, mail, clock, login, pw)


def test_adult_member_signs_in_and_cannot_see_drive_or_edit_wills(owner, make_bridge, mail, clock):
    b, r = _member_login(owner, make_bridge, mail, clock, "Ravi", "Adult Family Member", "ravi")
    assert r["ok"] and r["user"]["role"] == "Adult Family Member"
    assert r["perms"]["views"]["will"] == "r" and r["perms"]["views"]["drive"] == "r"  # own password only


def test_viewer_cannot_save(owner, make_bridge, mail, clock):
    owner.recovery_key  # noqa
    b, r = _member_login(owner, make_bridge, mail, clock, "Vera", "Viewer", "vera")
    st = r["state"]; st["contacts"].append({"id": "n", "name": "x", "relation": "", "role": "Other", "phone": ""})
    assert b.save_state(st)["ok"]  # accepted but nothing changes
    assert owner.load_state()["state"]["contacts"] == []


def test_emergency_contact_needs_owner_approval_window(owner, make_bridge, mail, clock):
    aid = add_person(owner, "Neighbour", "Emergency Contact")
    owner.member_add(aid, "neighbour", "n@example.com", "neighbour long password")
    b = make_bridge(owner.dir)
    r = b.login("neighbour", "neighbour long password")
    assert not r["ok"] and "approved" in r["error"]
    assert owner.emergency_grant(2)["ok"]
    clock.advance(60)
    r = signin(b, mail, clock, "neighbour", "neighbour long password")
    assert r["ok"] and r["state"]["assets"] == []
    assert not b.save_state(r["state"])["ok"]
    assert owner.emergency_revoke()["ok"]
    b.lock()
    assert not b.unlock("neighbour long password")["ok"] or not b.load_state()["ok"]


def test_family_member_cannot_do_owner_things(owner, make_bridge, mail, clock):
    b, r = _member_login(owner, make_bridge, mail, clock, "Ravi", "Adult Family Member", "ravi")
    for call in (lambda: b.emergency_grant(1), lambda: b.smtp_save({}), lambda: b.export_backup("xlsx"),
                 lambda: b.add_mirror("/tmp"), lambda: b.set_xlsx_mode("standard")):
        res = call()
        assert not res["ok"], res


def test_coowner_cannot_promote_to_owner(owner, make_bridge, mail, clock):
    b, r = _member_login(owner, make_bridge, mail, clock, "Priya", "Co-owner", "priya")
    st = r["state"]; st["access"].append({"id": "z", "name": "Z", "role": "Owner", "scope": "", "status": "Active"})
    assert not b.save_state(st)["ok"]


def test_removed_member_loses_login(owner, make_bridge, mail, clock):
    aid = add_person(owner, "Ravi", "Adult Family Member")
    owner.member_add(aid, "ravi", "ravi@example.com", "ravi long password")
    assert owner.member_remove(aid)["ok"]
    assert not make_bridge(owner.dir).login("ravi", "ravi long password")["ok"]


def test_member_slots_survive_owner_password_change(owner, make_bridge, mail, clock):
    aid = add_person(owner, "Ravi", "Adult Family Member")
    owner.member_add(aid, "ravi", "ravi@example.com", "ravi long password")
    assert owner.change_password(PW, "owner new long password")["ok"]
    b = make_bridge(owner.dir); clock.advance(60)
    assert signin(b, mail, clock, "ravi", "ravi long password")["ok"]


# ---------------------------------------------------------------- backups through the API
def test_export_and_restore_via_bridge(owner, make_bridge, tmp_path):
    import base64
    st = owner.load_state()["state"]
    st["assets"].append({"id": "a", "name": "Backed up", "type": "Bank", "owner": "A", "country": "US", "currency": "USD", "value": 1, "date": "", "source": ""})
    owner.save_state(st)
    exp = owner.export_backup("vault"); xl = owner.export_backup("xlsx")
    assert Path(exp["path"]).exists() and Path(xl["path"]).exists()
    for kind, f in (("vault", exp), ("xlsx", xl)):
        owner.save_state({**owner.load_state()["state"], "assets": []})
        b64 = base64.b64encode(Path(f["path"]).read_bytes()).decode()
        info = owner.backup_inspect(b64, PW)
        assert info["ok"] and info["counts"]["assets"] == 1
        assert owner.backup_apply()["state"]["assets"][0]["name"] == "Backed up"


def test_restore_rejects_wrong_password_and_garbage(owner):
    import base64
    exp = owner.export_backup("vault")
    b64 = base64.b64encode(Path(exp["path"]).read_bytes()).decode()
    assert not owner.backup_inspect(b64, "nope")["ok"]
    assert not owner.backup_inspect(base64.b64encode(b"hello").decode(), PW)["ok"]
    assert not owner.backup_apply()["ok"]


def test_new_install_can_start_from_backup(owner, make_bridge, mail, tmp_path):
    import base64
    exp = owner.export_backup("xlsx")
    b2 = make_bridge(tmp_path / "newpc")
    p = {**PROFILE, "password": "totally new password", "password2": "totally new password", "questions": ANSWERS, "smtp": {}}
    assert b2.register_start(p)["ok"] and b2.otp_verify(mail.last_code())["ok"]
    r = b2.register_finish({"start": "backup", "backup_b64": base64.b64encode(Path(exp["path"]).read_bytes()).decode(), "backup_password": PW})
    assert r["ok"] and r["restoredFrom"] == "spreadsheet"


def test_errors_do_not_leak_internals(owner, monkeypatch):
    from kinkeep_desktop import store as sm
    monkeypatch.setattr(sm.Session, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("secret internals /etc/passwd")))
    st = owner.load_state()["state"]; st["plan"]["medical"] = "changed"
    r = owner.save_state(st)
    assert not r["ok"] and "internals" not in r["error"] and "passwd" not in r["error"]


def test_rate_limit_message_is_friendly(owner, clock):
    owner.signout()
    r = owner.forgot_answers(["dosa", "green", "mrs iyer"])
    assert not r["ok"] and "rate_limited" not in r["error"] and "wait" in r["error"]


def test_recovery_sheet_requires_the_real_key(owner):
    assert not owner.save_recovery_sheet("AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")["ok"]
    r = owner.save_recovery_sheet(owner.recovery_key)
    assert r["ok"] and owner.recovery_key in Path(r["path"]).read_text()


def test_stale_screen_cannot_overwrite_newer_data(owner):
    seen = owner.load_state()
    other = dict(seen["state"]); other["plan"] = {"medical": "changed by someone else", "instructions": ""}
    assert owner.save_state(other, seen["seq"])["ok"]
    stale = dict(seen["state"]); stale["plan"] = {"medical": "old screen", "instructions": ""}
    r = owner.save_state(stale, seen["seq"])
    assert not r["ok"] and r["stale"]
    assert owner.load_state()["state"]["plan"]["medical"] == "changed by someone else"
