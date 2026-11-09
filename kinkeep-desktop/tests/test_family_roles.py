"""The Family and roles page: who may add people, change roles, pause, reset passwords and remove sign-ins."""
import pytest

from conftest import add_person, signin
from kinkeep_desktop import access

PWD = "member long password"


def add(b, name="Ravi", role="Adult Family Member", **kw):
    r = b.family_add(name, role, **kw)
    assert r["ok"], r
    return next(p for p in b.family_overview()["people"] if p["name"] == name)["id"]


def member_bridge(owner, make_bridge, clock):
    b = make_bridge(owner.dir)
    clock.advance(60)
    return b


def coowner(owner, make_bridge, mail, clock):
    cid = add(owner, "Priya", "Co-owner")
    assert owner.member_add(cid, "priya", "priya@example.com", PWD)["ok"]
    b = member_bridge(owner, make_bridge, clock)
    assert signin(b, mail, clock, "priya", PWD)["ok"]
    return b, cid


def test_overview_lists_people_roles_and_matrix(owner):
    add(owner, "Ravi")
    o = owner.family_overview()
    assert o["ok"] and {p["name"] for p in o["people"]} >= {"Asha Rao", "Ravi"}
    assert [m["role"] for m in o["matrix"]] == ["Owner", "Co-owner", "Adult Family Member", "Teen", "Viewer", "Emergency Contact"]
    assert o["assignable"] == ["Co-owner", "Adult Family Member", "Teen", "Viewer", "Emergency Contact"]
    adult = next(m for m in o["matrix"] if m["role"] == "Adult Family Member")
    assert adult["views"]["will"] == "r" and adult["views"]["assets"] == "rw" and adult["family"] == ""


def test_owner_adds_person_with_role_and_gets_invited_status(owner):
    aid = add(owner, "Mia", "Teen", scope="Own documents")
    row = next(p for p in owner.family_overview()["people"] if p["id"] == aid)
    assert row["role"] == "Teen" and row["status"] == "Invited" and row["scope"] == "Own documents" and row["login"] == ""


def test_cannot_create_a_second_owner_or_duplicate_name_or_bad_role(owner):
    assert not owner.family_add("Evil", "Owner")["ok"]
    assert not owner.family_add("X", "Superuser")["ok"]
    add(owner, "Ravi")
    assert "already" in owner.family_add("ravi", "Viewer")["error"]
    assert not owner.family_add("   ", "Viewer")["ok"]


def test_add_with_signin_creates_login_in_one_step(owner, make_bridge, mail, clock):
    r = owner.family_add("Ravi", "Adult Family Member", "", "ravi", "ravi@example.com", PWD)
    assert r["ok"]
    b = member_bridge(owner, make_bridge, clock)
    s = signin(b, mail, clock, "ravi", PWD)
    assert s["ok"] and s["user"]["role"] == "Adult Family Member"


def test_add_with_bad_signin_details_leaves_no_half_created_person(owner):
    r = owner.family_add("Ravi", "Adult Family Member", "", "ravi", "not-an-email", PWD)
    assert not r["ok"]
    assert all(p["name"] != "Ravi" for p in owner.family_overview()["people"])
    r = owner.family_add("Ravi", "Adult Family Member", "", "ravi", "r@example.com", "short")
    assert not r["ok"] and all(p["name"] != "Ravi" for p in owner.family_overview()["people"])


def test_role_change_takes_effect_at_next_sign_in(owner, make_bridge, mail, clock):
    aid = add(owner, "Ravi", "Adult Family Member")
    owner.member_add(aid, "ravi", "ravi@example.com", PWD)
    assert owner.family_update(aid, "Viewer", "Read only")["ok"]
    b = member_bridge(owner, make_bridge, clock)
    s = signin(b, mail, clock, "ravi", PWD)
    assert s["user"]["role"] == "Viewer" and s["perms"]["views"]["assets"] == ""
    assert s["state"]["assets"] == []


def test_owner_row_cannot_be_edited_paused_reset_or_deleted_here(owner):
    oid = next(p["id"] for p in owner.family_overview()["people"] if p["role"] == "Owner")
    for r in (owner.family_update(oid, "Viewer", ""), owner.family_pause(oid, True), owner.family_delete(oid),
              owner.member_reset_password(oid, "another long password")):
        assert not r["ok"]


def test_coowner_limits(owner, make_bridge, mail, clock):
    co, cid = coowner(owner, make_bridge, mail, clock)
    ov = co.family_overview()
    assert ov["ok"] and ov["assignable"] == ["Adult Family Member", "Teen", "Viewer", "Emergency Contact"]
    assert not next(p for p in ov["people"] if p["role"] == "Owner")["canManage"]
    assert not co.family_add("Boss", "Co-owner")["ok"]
    assert not co.family_add("Boss", "Owner")["ok"]
    assert co.family_add("Ravi", "Adult Family Member")["ok"]
    assert not co.family_update(cid, "Viewer", "")["ok"]          # cannot demote a Co-owner (even themselves)
    assert not co.family_pause(cid, True)["ok"]
    rid = next(p["id"] for p in co.family_overview()["people"] if p["name"] == "Ravi")
    assert co.family_update(rid, "Teen", "x")["ok"]
    assert not co.family_update(rid, "Co-owner", "x")["ok"]       # cannot promote either


@pytest.mark.parametrize("role", ["Adult Family Member", "Teen", "Viewer"])
def test_other_roles_cannot_open_or_use_family_page(owner, make_bridge, mail, clock, role):
    aid = add(owner, "Pat", role)
    owner.member_add(aid, "pat", "pat@example.com", PWD)
    b = member_bridge(owner, make_bridge, clock)
    r = signin(b, mail, clock, "pat", PWD)
    assert r["ok"] and r["perms"]["views"]["family"] == ""
    for res in (b.family_overview(), b.family_add("Z", "Viewer"), b.family_update(aid, "Viewer", ""),
                b.family_pause(aid, True), b.family_delete(aid), b.member_reset_password(aid, "another long password")):
        assert not res["ok"] and res.get("denied")


def test_pause_blocks_sign_in_and_resume_restores_it(owner, make_bridge, mail, clock):
    aid = add(owner, "Ravi")
    owner.member_add(aid, "ravi", "ravi@example.com", PWD)
    assert owner.family_pause(aid, True)["ok"]
    assert next(p for p in owner.family_overview()["people"] if p["id"] == aid)["status"] == "Suspended"
    b = member_bridge(owner, make_bridge, clock)
    r = b.login("ravi", PWD)
    assert not r["ok"] and "paused" in r["error"] and b.load_state()["ok"] is False
    assert owner.family_pause(aid, False)["ok"]
    assert next(p for p in owner.family_overview()["people"] if p["id"] == aid)["status"] == "Active"
    assert signin(member_bridge(owner, make_bridge, clock), mail, clock, "ravi", PWD)["ok"]


def test_pause_does_not_reveal_anything_to_wrong_password(owner, make_bridge, clock):
    aid = add(owner, "Ravi")
    owner.member_add(aid, "ravi", "ravi@example.com", PWD)
    owner.family_pause(aid, True)
    b = member_bridge(owner, make_bridge, clock)
    assert "paused" not in b.login("ravi", "wrong password!!")["error"]  # same generic message as any wrong password


def test_pausing_person_without_login_then_resuming_is_invited(owner):
    aid = add(owner, "Ravi")
    owner.family_pause(aid, True)
    owner.family_pause(aid, False)
    assert next(p for p in owner.family_overview()["people"] if p["id"] == aid)["status"] == "Invited"


def test_owner_resets_member_password(owner, make_bridge, mail, clock):
    aid = add(owner, "Ravi")
    assert not owner.member_reset_password(aid, "another long password")["ok"]  # no sign-in yet
    owner.member_add(aid, "ravi", "ravi@example.com", PWD)
    assert not owner.member_reset_password(aid, "short")["ok"]
    assert owner.member_reset_password(aid, "a different long password")["ok"]
    assert not make_bridge(owner.dir).login("ravi", PWD)["ok"]
    assert signin(member_bridge(owner, make_bridge, clock), mail, clock, "ravi", "a different long password")["ok"]


def test_delete_removes_person_and_login(owner, make_bridge):
    aid = add(owner, "Ravi")
    owner.member_add(aid, "ravi", "ravi@example.com", PWD)
    assert owner.family_delete(aid)["ok"]
    assert all(p["id"] != aid for p in owner.family_overview()["people"])
    assert not make_bridge(owner.dir).login("ravi", PWD)["ok"]


def test_family_changes_reach_the_encrypted_spreadsheet(owner):
    import io
    from openpyxl import load_workbook
    from kinkeep_desktop import officecrypt
    from conftest import PW
    aid = add(owner, "Ravi", "Teen")
    owner.family_pause(aid, True)
    plain = officecrypt.decrypt(owner.store.xlsx_path.read_bytes(), PW)
    wb = load_workbook(io.BytesIO(plain))
    assert "FamilyAccess" in wb.sheetnames
    rows = [[c.value for c in r] for r in wb["FamilyAccess"].iter_rows()]
    assert any("Ravi" in map(str, r) and "Suspended" in map(str, r) for r in rows)


def test_signed_in_member_is_cut_off_after_pause_when_they_next_reload(owner, make_bridge, mail, clock):
    aid = add(owner, "Ravi")
    owner.member_add(aid, "ravi", "ravi@example.com", PWD)
    b = member_bridge(owner, make_bridge, clock)
    assert signin(b, mail, clock, "ravi", PWD)["ok"]
    owner.family_pause(aid, True)
    b.lock(); clock.advance(1)
    r = b.unlock(PWD)
    assert not r["ok"] and "paused" in r["error"] and not b.load_state()["ok"]
