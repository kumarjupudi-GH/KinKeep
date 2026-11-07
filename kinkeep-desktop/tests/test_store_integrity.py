import json
import os
from pathlib import Path

import pytest

from kinkeep_desktop import crypto, officecrypt, schema, store as storemod, xlsx_io
from kinkeep_desktop.store import Store

from conftest import PROFILE, PW


def new_store(tmp_path, data=None):
    st = Store(tmp_path / "d")
    s, rk = st.create(dict(PROFILE, q=[]), PW, data)
    return st, s, rk


def with_asset(s, name="Savings", value=10):
    s.data["assets"].append({"id": schema.nid(), "name": name, "type": "Bank", "owner": "Asha", "country": "US",
                             "currency": "USD", "value": value, "date": "2026-01-01", "source": "Statement"})
    s.commit()


def test_vault_and_xlsx_created_and_in_sync(tmp_path):
    st, s, _ = new_store(tmp_path)
    assert st.vault_path.exists() and st.xlsx_path.exists()
    plain = officecrypt.decrypt(st.xlsx_path.read_bytes(), PW)
    data, meta = xlsx_io.read_workbook(plain)
    assert xlsx_io.content_hash(data) == s.snapshot_hash() and meta["vault_seq"] == s.seq


def test_no_plaintext_anywhere_on_disk(tmp_path):
    st, s, rk = new_store(tmp_path)
    with_asset(s, "UniqueMarkerXYZ")
    for p in Path(st.dir).rglob("*"):
        if p.is_file():
            b = p.read_bytes()
            assert b"UniqueMarkerXYZ" not in b, p
            assert PW.encode() not in b and rk.encode() not in b, p


def test_every_save_updates_both_files(tmp_path):
    st, s, _ = new_store(tmp_path)
    for i in range(3):
        with_asset(s, f"A{i}", i)
    data, meta = xlsx_io.read_workbook(officecrypt.decrypt(st.xlsx_path.read_bytes(), PW))
    assert [a["name"] for a in data["assets"]] == ["A0", "A1", "A2"] and meta["vault_seq"] == s.seq


def test_wrong_password_and_login(tmp_path):
    st, s, _ = new_store(tmp_path)
    st.account_path.write_text(json.dumps({"login": "asha", "email": "asha@example.com", "first": "Asha", "last": "Rao", "q": []}))
    with pytest.raises(crypto.WrongPassword):
        st.unlock("asha", "wrong password")
    with pytest.raises(crypto.WrongPassword):
        st.unlock("nobody", PW)
    assert st.unlock("ASHA", PW).role == "Owner"


def test_corrupt_main_vault_recovers_from_previous_copy(tmp_path):
    st, s, _ = new_store(tmp_path)
    with_asset(s, "Keep me")
    with_asset(s, "Second")
    st.vault_path.write_text("{ half written garbage")
    s2 = st.unlock("asha", PW)
    assert s2.recovered_from and {a["name"] for a in s2.data["assets"]} >= {"Keep me"}
    assert json.loads(st.vault_path.read_text())["app"] == "KinKeep"  # healed on disk


def test_truncated_vault_recovers(tmp_path):
    st, s, _ = new_store(tmp_path)
    with_asset(s, "One"); with_asset(s, "Two")
    full = st.vault_path.read_bytes()
    st.vault_path.write_bytes(full[: len(full) // 2])
    assert st.unlock("asha", PW).recovered_from


def test_interrupted_write_leaves_old_file_intact(tmp_path, monkeypatch):
    st, s, _ = new_store(tmp_path)
    with_asset(s, "Before")
    before = st.vault_path.read_bytes()
    real = os.replace

    def boom(a, b):
        raise OSError("power cut")
    monkeypatch.setattr(os, "replace", boom)
    s.data["assets"][0]["name"] = "After"
    with pytest.raises(OSError):
        s.commit()
    monkeypatch.setattr(os, "replace", real)
    assert st.vault_path.read_bytes() == before
    assert not list(Path(st.dir).glob(".kk-*.tmp"))  # no stray temp files
    assert st.unlock("asha", PW).data["assets"][0]["name"] == "Before"


def test_failure_writing_xlsx_does_not_corrupt_vault(tmp_path, monkeypatch):
    st, s, _ = new_store(tmp_path)
    good_x = st.xlsx_path.read_bytes()
    monkeypatch.setattr(xlsx_io, "encrypt_workbook", lambda *a, **k: b"garbage")
    with pytest.raises(Exception):
        with_asset(s, "x")
    assert st.xlsx_path.read_bytes() == good_x
    assert crypto.parse_envelope(st.vault_path.read_text())  # vault is still valid


def test_missing_spreadsheet_is_regenerated(tmp_path):
    st, s, _ = new_store(tmp_path)
    st.xlsx_path.unlink()
    st.account_path.write_text(json.dumps({"login": "asha", "email": "a@b.co", "q": []}))
    s2 = st.unlock("asha", PW)
    assert s2.sync["state"] == "regenerated" and st.xlsx_path.exists()


def test_unreadable_spreadsheet_is_kept_and_replaced(tmp_path):
    st, s, _ = new_store(tmp_path)
    st.xlsx_path.write_bytes(b"junk")
    s2 = st.unlock("asha", PW)
    assert s2.sync["state"] == "regenerated"
    assert any("unreadable" in p.name for p in st.backup_dir.iterdir())


def test_external_spreadsheet_edit_is_offered_not_applied(tmp_path):
    st, s, _ = new_store(tmp_path)
    with_asset(s, "Original")
    data = json.loads(json.dumps(s.data)); data["assets"][0]["name"] = "Edited in Excel"
    st.xlsx_path.write_bytes(xlsx_io.encrypt_workbook(data, s.seq, PW))
    s2 = st.unlock("asha", PW)
    assert s2.sync["state"] == "external_edits"
    assert s2.data["assets"][0]["name"] == "Original"  # nothing silently overwritten
    st.resolve_sync(s2, "import")
    assert st.unlock("asha", PW).data["assets"][0]["name"] == "Edited in Excel"


def test_keep_choice_rewrites_spreadsheet(tmp_path):
    st, s, _ = new_store(tmp_path)
    with_asset(s, "Original")
    data = json.loads(json.dumps(s.data)); data["assets"][0]["name"] = "Edited"
    st.xlsx_path.write_bytes(xlsx_io.encrypt_workbook(data, s.seq, PW))
    s2 = st.unlock("asha", PW)
    st.resolve_sync(s2, "keep")
    d, _ = xlsx_io.read_workbook(officecrypt.decrypt(st.xlsx_path.read_bytes(), PW))
    assert d["assets"][0]["name"] == "Original"


def test_spreadsheet_import_cannot_grant_access(tmp_path):
    st, s, _ = new_store(tmp_path)
    data = json.loads(json.dumps(s.data))
    data["access"].append({"id": "evil", "name": "Mallory", "role": "Co-owner", "scope": "all", "status": "Active"})
    data["access"][0]["role"] = "Viewer"  # try to demote the owner as well
    st.xlsx_path.write_bytes(xlsx_io.encrypt_workbook(data, s.seq, PW))
    s2 = st.unlock("asha", PW)
    st.resolve_sync(s2, "import")
    acc = st.unlock("asha", PW).data["access"]
    mal = next(r for r in acc if r["id"] == "evil")
    assert mal["status"] == "Needs re-approval"
    assert any(r["role"] == "Owner" for r in acc)


def test_spreadsheet_behind_vault_is_refreshed(tmp_path):
    st, s, _ = new_store(tmp_path)
    old = st.xlsx_path.read_bytes()
    with_asset(s, "New")
    st.xlsx_path.write_bytes(old)  # simulate a crash between the two writes
    s2 = st.unlock("asha", PW)
    assert s2.sync["state"] == "regenerated"
    d, _ = xlsx_io.read_workbook(officecrypt.decrypt(st.xlsx_path.read_bytes(), PW))
    assert d["assets"][0]["name"] == "New"


def test_backup_rotation_is_bounded(tmp_path):
    st, s, _ = new_store(tmp_path)
    for i in range(storemod.KEEP_BACKUPS + 8):
        with_asset(s, f"x{i}")
    assert len(list(st.backup_dir.glob("kinkeep.data.*.xlsx"))) <= storemod.KEEP_BACKUPS


def test_lock_prevents_second_writer(tmp_path):
    st = Store(tmp_path / "d")
    st.acquire_lock()
    other = Store(tmp_path / "d")
    # same pid is treated as ours; simulate a live foreign process by pid 1
    st.lock_path.write_text(json.dumps({"pid": 1, "t": __import__("time").time()}))
    with pytest.raises(storemod.Locked):
        other.acquire_lock()
    st.lock_path.write_text(json.dumps({"pid": 99999999, "t": __import__("time").time()}))
    other.acquire_lock()  # stale lock from a dead process is taken over
    other.release_lock()


def test_change_password_rewraps_and_updates_xlsx(tmp_path):
    st, s, _ = new_store(tmp_path)
    st.account_path.write_text(json.dumps({"login": "asha", "email": "a@b.co", "q": []}))
    with pytest.raises(crypto.WrongPassword):
        st.change_password(s, "wrong", "brand new password")
    st.change_password(s, PW, "brand new password")
    with pytest.raises(crypto.WrongPassword):
        st.unlock("asha", PW)
    assert st.unlock("asha", "brand new password")
    officecrypt.decrypt(st.xlsx_path.read_bytes(), "brand new password")
    with pytest.raises(officecrypt.WrongPassword):
        officecrypt.decrypt(st.xlsx_path.read_bytes(), PW)


def test_recovery_key_unlocks_after_password_reset(tmp_path):
    st, s, rk = new_store(tmp_path)
    with_asset(s, "Precious")
    s2 = st.unlock_with_recovery(rk)
    st.reset_password_after_recovery(s2, "another long password")
    st.account_path.write_text(json.dumps({"login": "asha", "email": "a@b.co", "q": []}))
    s3 = st.unlock("asha", "another long password")
    assert s3.data["assets"][0]["name"] == "Precious"
    officecrypt.decrypt(st.xlsx_path.read_bytes(), "another long password")


# ---------------------------------------------------------------- backup / restore
def test_vault_backup_roundtrip_and_cross_machine_restore(tmp_path):
    st, s, rk = new_store(tmp_path)
    with_asset(s, "Portable")
    s.data["access"].append({"id": "k1", "name": "Ravi", "role": "Adult Family Member", "scope": "x", "status": "Active"})
    s.commit()
    out = st.export_vault_backup(s, tmp_path / "b.kinkeep.json")
    # "new computer": a different folder, a different master password
    st2 = Store(tmp_path / "other")
    s2, rk2, kind = st2.restore_new(dict(PROFILE, q=[]), "new machine password", out.read_bytes(), PW)
    assert kind == "vault"
    assert s2.data["assets"][0]["name"] == "Portable"
    ravi = next(r for r in s2.data["access"] if r["name"] == "Ravi")
    assert ravi["role"] == "Adult Family Member" and ravi["status"] == "Needs re-approval"  # relationship kept, access not
    assert s2.members == []


def test_xlsx_backup_restores(tmp_path):
    st, s, _ = new_store(tmp_path)
    with_asset(s, "FromSheet")
    out = st.export_xlsx_backup(s, tmp_path / "b.xlsx")
    st2 = Store(tmp_path / "other")
    s2, _, kind = st2.restore_new(dict(PROFILE, q=[]), "new machine password", out.read_bytes(), PW)
    assert kind == "spreadsheet" and s2.data["assets"][0]["name"] == "FromSheet"


def test_restore_with_wrong_password_changes_nothing(tmp_path):
    st, s, _ = new_store(tmp_path)
    out = st.export_vault_backup(s, tmp_path / "b.json")
    before = st.vault_path.read_bytes()
    with pytest.raises(crypto.WrongPassword):
        st.restore_into(s, out.read_bytes(), "wrong")
    assert st.vault_path.read_bytes() == before


def test_restore_into_revokes_family_logins(tmp_path):
    st, s, _ = new_store(tmp_path)
    aid = schema.nid()
    s.data["access"].append({"id": aid, "name": "Ravi", "role": "Adult Family Member", "scope": "x", "status": "Invited"})
    s.commit()
    st.add_member(s, aid, "ravi", "ravi@example.com", "ravi long password")
    out = st.export_vault_backup(s, tmp_path / "b.json")
    assert all(x["id"] in ("owner", "recovery") for x in crypto.parse_envelope(out.read_text())["slots"])  # no family keys in backups
    st.restore_into(s, out.read_bytes(), PW)
    assert s.members == [] and all(x["id"] in ("owner", "recovery") for x in s.slots)
    assert next(r for r in s.data["access"] if r["id"] == aid)["status"] == "Needs re-approval"


def test_backup_of_browser_version_imports(tmp_path):
    web = schema.empty_state()
    web["assets"].append({"id": "w1", "name": "From the web app", "type": "Bank", "owner": "A", "country": "US", "currency": "USD",
                          "value": 5, "date": "", "source": ""})
    web["access"] = [{"id": "x", "name": "Teen One", "role": "Teen", "scope": "", "status": "Active"}]
    text = crypto.make_legacy_web_vault(web, "old browser pass", iters=2000)
    st = Store(tmp_path / "d")
    s, _, kind = st.restore_new(dict(PROFILE, q=[]), PW, text, "old browser pass")
    assert kind == "browser-version vault" and s.data["assets"][0]["name"] == "From the web app"
