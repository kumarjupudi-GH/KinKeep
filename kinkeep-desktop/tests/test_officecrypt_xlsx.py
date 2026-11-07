import json
import shutil
import subprocess
import sys
import zipfile
import io
from pathlib import Path

import pytest

from kinkeep_desktop import officecrypt, schema, xlsx_io

PW = "pässword 123!"


def sample():
    d = schema.empty_state()
    d["assets"].append({"id": "a1", "name": "Checking =1+1", "type": "Bank", "owner": "Asha", "country": "US", "currency": "USD",
                        "value": 1234.5, "date": "2026-01-02", "source": "Statement"})
    d["reminders"].append({"id": "r1", "title": "Renew passport", "due": "2027-01-01", "type": "Renewal", "done": True})
    d["plan"]["medical"] = "Allergic to penicillin"
    d["check"] = {"hospital": {"0": True, "1": False}}
    return schema.normalize(d)


@pytest.mark.parametrize("mode", ["agile", "standard"])
def test_encrypt_roundtrip(mode):
    d = sample()
    blob = xlsx_io.encrypt_workbook(d, 5, PW, mode)
    assert officecrypt.is_encrypted(blob)
    assert not blob.startswith(b"PK")  # not a plain zip: nothing readable without the password
    assert b"Checking" not in blob and b"penicillin" not in blob
    data, meta = xlsx_io.read_workbook(officecrypt.decrypt(blob, PW))
    assert xlsx_io.content_hash(data) == xlsx_io.content_hash(d)
    assert meta["vault_seq"] == 5


@pytest.mark.parametrize("mode", ["agile", "standard"])
def test_wrong_password(mode):
    blob = xlsx_io.encrypt_workbook(sample(), 1, PW, mode)
    with pytest.raises(officecrypt.WrongPassword):
        officecrypt.decrypt(blob, "nope")


def test_agile_tamper_detected():
    from kinkeep_desktop import cfb
    streams = cfb.read_streams(xlsx_io.encrypt_workbook(sample(), 1, PW, "agile"))
    pkg = bytearray(streams["EncryptedPackage"])
    pkg[200] ^= 0xFF  # flip one bit inside the encrypted workbook
    streams["EncryptedPackage"] = bytes(pkg)
    with pytest.raises(officecrypt.FormatError):
        officecrypt.decrypt(cfb.write_streams(streams), PW)


def test_each_module_has_its_own_sheet():
    plain = officecrypt.decrypt(xlsx_io.encrypt_workbook(sample(), 1, PW), PW)
    from openpyxl import load_workbook
    names = load_workbook(io.BytesIO(plain)).sheetnames
    for coll in schema.COLLS:
        assert schema.SHEET[coll] in names
    for extra in ("README", "Settings", "Checklists", "Meta"):
        assert extra in names


def test_formula_injection_is_stored_as_text():
    plain = officecrypt.decrypt(xlsx_io.encrypt_workbook(sample(), 1, PW), PW)
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(plain))["Assets"]
    assert ws["B2"].value == "Checking =1+1" and ws["B2"].data_type == "s"


def test_no_account_secrets_in_spreadsheet():
    plain = officecrypt.decrypt(xlsx_io.encrypt_workbook(sample(), 1, PW), PW)
    z = zipfile.ZipFile(io.BytesIO(plain))
    blob = b"".join(z.read(n) for n in z.namelist()).lower()
    for needle in (b"salt", b"smtp", b"recovery", b"argon"):
        assert needle not in blob


def test_non_kinkeep_workbook_rejected():
    from openpyxl import Workbook
    bio = io.BytesIO(); Workbook().save(bio)
    with pytest.raises(ValueError):
        xlsx_io.read_workbook(bio.getvalue())


LO = shutil.which("soffice")
try:
    import uno  # noqa: F401
    HAS_UNO = True
except Exception:
    HAS_UNO = False


@pytest.mark.skipif(not (LO and HAS_UNO), reason="LibreOffice with python-uno not available")
@pytest.mark.parametrize("mode", ["agile", "standard"])
def test_libreoffice_opens_without_kinkeep(tmp_path, mode):
    """Disaster recovery: an independent spreadsheet program opens the file with the master password."""
    f = tmp_path / "kk.xlsx"
    f.write_bytes(xlsx_io.encrypt_workbook(sample(), 1, PW, mode))
    tool = Path(__file__).resolve().parents[1] / "tools" / "lo_open.py"
    ok = subprocess.run([sys.executable, str(tool), str(f), PW], capture_output=True, text=True, timeout=120)
    assert ok.returncode == 0, ok.stderr
    sheets = json.loads(ok.stdout)
    assert sheets["Assets"][1][:2] == ["a1", "Checking =1+1"]
    assert sheets["Settings"][4] == ["plan.medical", "Allergic to penicillin"]
    bad = subprocess.run([sys.executable, str(tool), str(f), "wrong"], capture_output=True, text=True, timeout=120)
    assert bad.returncode == 3
