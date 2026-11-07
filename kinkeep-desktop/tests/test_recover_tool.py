import json
import subprocess
import sys
from pathlib import Path

from kinkeep_desktop import schema, store as storemod
from conftest import PROFILE, PW

TOOL = Path(__file__).resolve().parents[1] / "tools" / "kk_recover.py"


def run(args, pw):
    return subprocess.run([sys.executable, str(TOOL), *args], input=pw + "\n", capture_output=True, text=True,
                          env={"PATH": "", "PYTHONPATH": str(TOOL.parents[1])})


def test_recover_without_app(tmp_path, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *_: PW)
    st = storemod.Store(tmp_path / "d")
    s, rk = st.create(dict(PROFILE, q=[]), PW)
    s.data["assets"].append({"id": "a", "name": "Recovered Gold", "type": "Gold", "owner": "A", "country": "IN", "currency": "INR", "value": 9, "date": "", "source": ""})
    s.commit()
    # run the tool in-process (it reads the password with getpass)
    import importlib.util
    spec = importlib.util.spec_from_file_location("kk_recover", TOOL); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    for src, args in ((st.xlsx_path, ["--csv"]), (st.vault_path, [])):
        monkeypatch.setattr(sys, "argv", ["kk_recover", str(src), "--out", str(tmp_path / ("o" + src.suffix)), *args])
        mod.main()
    assert "Recovered Gold" in (tmp_path / "o.xlsx" / "Assets.csv").read_text("utf-8-sig")
    assert json.loads((tmp_path / "o.json" / "KinKeep-readable.json").read_text())["assets"][0]["name"] == "Recovered Gold"
    monkeypatch.setattr("getpass.getpass", lambda *_: rk)
    monkeypatch.setattr(sys, "argv", ["kk_recover", str(st.vault_path), "--out", str(tmp_path / "o2")])
    mod.main()  # the recovery key also opens the vault
    assert (tmp_path / "o2" / "KinKeep-readable.json").exists()
