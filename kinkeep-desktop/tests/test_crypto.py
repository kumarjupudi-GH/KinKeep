import json
import os

import pytest

from kinkeep_desktop import crypto


def test_password_slot_roundtrip_and_wrong_password():
    dek = os.urandom(32)
    slot = crypto.make_password_slot("pässword ✓", dek, "owner")
    assert crypto.open_password_slot(slot, "pässword ✓") == dek
    with pytest.raises(crypto.WrongPassword):
        crypto.open_password_slot(slot, "pässword x")


def test_unicode_normalization_of_passwords():
    dek = os.urandom(32)
    slot = crypto.make_password_slot("é", dek, "owner")  # precomposed
    assert crypto.open_password_slot(slot, "é") == dek  # decomposed


def test_slot_bound_to_its_id():
    dek = os.urandom(32)
    slot = crypto.make_password_slot("pw-pw-pw-pw", dek, "owner")
    slot["id"] = "m-other"
    with pytest.raises(crypto.WrongPassword):
        crypto.open_password_slot(slot, "pw-pw-pw-pw")


def test_recovery_key_roundtrip_and_format_tolerance():
    dek = os.urandom(32)
    rk = crypto.new_recovery_key()
    assert len(rk.replace("-", "")) == 32
    slot = crypto.make_recovery_slot(rk, dek)
    assert crypto.open_recovery_slot(slot, rk.lower().replace("-", " ")) == dek
    with pytest.raises(crypto.WrongPassword):
        crypto.open_recovery_slot(slot, crypto.new_recovery_key())
    with pytest.raises(crypto.WrongPassword):
        crypto.open_recovery_slot(slot, "ABCD")


def _env(payload=None):
    dek = os.urandom(32)
    slots = [crypto.make_password_slot("pw-pw-pw-pw", dek, "owner")]
    return dek, crypto.seal(payload or {"data": {"x": 1}}, dek, slots, 7)


def test_envelope_roundtrip_has_no_plaintext():
    dek, text = _env({"data": {"secret": "TOPSECRET-VALUE"}})
    assert "TOPSECRET" not in text and "secret" not in text
    assert crypto.open_with_dek(crypto.parse_envelope(text), dek)["data"]["secret"] == "TOPSECRET-VALUE"


def test_tampered_ciphertext_is_rejected():
    dek, text = _env()
    env = json.loads(text)
    ct = bytearray(crypto.unb64(env["ct"]))
    ct[3] ^= 1
    env["ct"] = crypto.b64(bytes(ct))
    with pytest.raises(crypto.FormatError):
        crypto.open_with_dek(env, dek)


def test_rollback_of_sequence_number_is_detected():
    dek, text = _env()
    env = json.loads(text)
    env["seq"] = 6  # attacker relabels the file as an older generation
    with pytest.raises(crypto.FormatError):
        crypto.open_with_dek(env, dek)


def test_foreign_and_garbage_files_rejected():
    for bad in ("not json", "[]", json.dumps({"app": "Other"})):
        with pytest.raises(crypto.FormatError):
            crypto.parse_envelope(bad)


def test_hostile_kdf_parameters_refused():
    with pytest.raises(crypto.FormatError):
        crypto.argon2_key(b"x", b"s" * 16, 1, 1 << 30, 1)
    with pytest.raises(crypto.FormatError):
        crypto.argon2_key(b"x", b"s" * 16, 10_000, 64, 1)


def test_production_kdf_cost_is_strong():
    # conftest lowers the cost for speed; the shipped default must not be weak
    import importlib
    src = importlib.import_module("kinkeep_desktop.crypto").__file__
    text = open(src).read()
    assert 'KDF_COST = {"t": 3, "m": 65536, "p": 4}' in text


def test_security_answers_are_salted_hashes_and_normalised():
    a = crypto.hash_answer("  Dosa!! ")
    b = crypto.hash_answer("dosa")
    assert a["h"] != b["h"] and a["salt"] != b["salt"]  # salted
    assert "dosa" not in json.dumps(a).lower()
    assert crypto.check_answer("DOSA", a) and crypto.check_answer(" dosa ", b)
    assert not crypto.check_answer("idli", a)


def test_legacy_browser_backup_opens():
    data = {"assets": [], "rate": 83}
    text = crypto.make_legacy_web_vault(data, "old pass phrase", iters=2000)
    assert crypto.open_legacy_web_vault(text, "old pass phrase") == data
    with pytest.raises(crypto.WrongPassword):
        crypto.open_legacy_web_vault(text, "wrong")
