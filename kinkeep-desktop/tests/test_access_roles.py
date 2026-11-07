import copy
import datetime as dt

import pytest

from kinkeep_desktop import access, schema

OWNER, COOWNER, ADULT, TEEN, VIEWER, EMERGENCY = schema.T["aRole"]


def full():
    d = schema.empty_state()
    d["assets"] = [{"id": "a", "name": "Bank", "type": "Bank", "owner": "Asha", "country": "US", "currency": "USD", "value": 5, "date": "", "source": ""}]
    d["policies"] = [{"id": "p1", "kind": "Health", "name": "BlueCross", "holder": "", "limit": "", "deductible": "", "renewal": "", "beneficiary": "", "claims": "", "notes": ""},
                     {"id": "p2", "kind": "Life", "name": "Term", "holder": "", "limit": "", "deductible": "", "renewal": "", "beneficiary": "", "claims": "", "notes": ""}]
    d["wills"] = [{"id": "w", "title": "Will", "docType": "Last will", "person": "Asha", "executor": "", "backup": "", "heirs": "", "guardian": "",
                   "attorney": "", "jurisdiction": "", "signed": "", "reviewed": "", "cycle": "36", "location": "", "online": "", "softcopy": "",
                   "progress": "Signed and stored", "notes": "PRIVATE NOTE"}]
    d["docs"] = [{"id": "d1", "title": "Teen passport copy", "category": "Identity", "owner": "Mia", "expires": "", "file": "", "status": "On file"},
                 {"id": "d2", "title": "Parent deed", "category": "Property", "owner": "Asha", "expires": "", "file": "", "status": "On file"}]
    d["contacts"] = [{"id": "c", "name": "Dr Rao", "relation": "", "role": "Doctor", "phone": "1"}]
    d["access"] = [{"id": "o", "name": "Asha Rao", "role": OWNER, "scope": "", "status": "Active"},
                   {"id": "t", "name": "Mia Rao", "role": TEEN, "scope": "", "status": "Active"}]
    d["plan"] = {"medical": "allergy", "instructions": "call Ravi"}
    return schema.normalize(d)


def test_five_required_roles_exist():
    assert {OWNER, COOWNER, ADULT, EMERGENCY} <= set(schema.T["aRole"])


def test_owner_and_coowner_see_everything():
    f = full()
    for r in (OWNER, COOWNER):
        assert access.filter_state(f, r, "x") == f


def test_adult_cannot_read_private_will_notes():
    v = access.filter_state(full(), ADULT, "Ravi")
    assert v["wills"][0]["notes"] == "" and v["wills"][0]["title"] == "Will"
    assert access.view_perm(ADULT, "will") == "r"


def test_emergency_contact_sees_only_emergency_essentials():
    v = access.filter_state(full(), EMERGENCY, "Dr")
    assert v["assets"] == [] and v["wills"] == [] and v["docs"] == [] and v["ids"] == [] and v["liabs"] == []
    assert [p["kind"] for p in v["policies"]] == ["Health"]
    assert v["contacts"] and v["plan"]["medical"] == "allergy"
    assert v["access"] == []


def test_emergency_cannot_write_anything_but_checklist():
    f = full()
    inc = copy.deepcopy(f); inc["assets"] = []; inc["plan"]["medical"] = "x"; inc["check"] = {"p": {"1": True}}
    out = access.merge_back(f, inc, EMERGENCY)
    assert out["assets"] == f["assets"] and out["plan"] == f["plan"]


def test_viewer_is_read_only():
    f = full()
    inc = copy.deepcopy(f); inc["docs"] = []; inc["contacts"] = []
    assert access.merge_back(f, inc, VIEWER)["docs"] == f["docs"]


def test_teen_sees_only_own_docs():
    v = access.filter_state(full(), TEEN, "Mia Rao")
    assert [d["title"] for d in v["docs"]] == ["Teen passport copy"]


def test_adult_cannot_overwrite_sealed_notes_via_save():
    f = full()
    view = access.filter_state(f, ADULT, "Ravi")  # notes blanked in the view
    out = access.merge_back(f, view, ADULT)
    assert out["wills"] == f["wills"]  # blank notes are not written back; read-only anyway


def test_coowner_cannot_create_or_change_owner_roles():
    f = full()
    inc = copy.deepcopy(f); inc["access"].append({"id": "n", "name": "N", "role": COOWNER, "scope": "", "status": "Active"})
    with pytest.raises(access.Denied):
        access.merge_back(f, inc, COOWNER)
    inc = copy.deepcopy(f); inc["access"][0]["role"] = VIEWER
    with pytest.raises(access.Denied):
        access.merge_back(f, inc, COOWNER)
    inc = copy.deepcopy(f); inc["access"] = inc["access"][1:]  # delete the owner row
    with pytest.raises(access.Denied):
        access.merge_back(f, inc, COOWNER)


def test_coowner_can_manage_ordinary_members():
    f = full()
    inc = copy.deepcopy(f); inc["access"][1]["role"] = VIEWER
    assert access.merge_back(f, inc, COOWNER)["access"][1]["role"] == VIEWER


def test_owner_cannot_remove_last_owner():
    f = full()
    inc = copy.deepcopy(f); inc["access"] = inc["access"][1:]
    with pytest.raises(access.Denied):
        access.merge_back(f, inc, OWNER)


def test_owner_only_actions():
    for a in ("clear", "reset", "delete_vault", "grant_emergency"):
        for r in (COOWNER, ADULT, TEEN, VIEWER, EMERGENCY):
            with pytest.raises(access.Denied):
                access.check_action(r, a)
        access.check_action(OWNER, a)


def test_emergency_window():
    now = dt.datetime.now(dt.timezone.utc)
    assert not access.emergency_active({})
    assert access.emergency_active({"emergency_until": (now + dt.timedelta(hours=1)).isoformat()})
    assert not access.emergency_active({"emergency_until": (now - dt.timedelta(hours=1)).isoformat()})
    assert not access.emergency_active({"emergency_until": "garbage"})
