"""Feature parity with the browser version. These tests read the ORIGINAL kinkeep.web.html, so if the data model
or the screens ever drift apart from it, the desktop build fails instead of silently losing a feature."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kinkeep_desktop import schema

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / "ui_src" / "kinkeep.web.html").read_text("utf-8")
DESK = (ROOT / "kinkeep_desktop" / "ui" / "index.html").read_text("utf-8")
NODE = shutil.which("node")


def _block(start_marker):
    i = WEB.index(start_marker)
    j = WEB.index("\n  };", i)
    return WEB[i:j + 5]


@pytest.fixture(scope="module")
def web_model():
    if not NODE:
        pytest.skip("node not available")
    code = "var T,C;\n" + _block("var T = {").replace("var T =", "T =") + "\n" + _block("var C = {").replace("var C =", "C =") + "\nconsole.log(JSON.stringify({T:T,C:C}))"
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_every_select_list_matches(web_model):
    for k, web in web_model["T"].items():
        desk = schema.T[k]
        if k == "aRole":  # desktop adds Co-owner, renames Adult/Emergency only (mapped by LEGACY_ROLES)
            mapped = [schema.LEGACY_ROLES.get(r, r) for r in web]
            assert set(mapped) <= set(desk) and "Co-owner" in desk
        elif k == "aStatus":
            assert set(web) <= set(desk)
        else:
            assert web == desk, k


def test_every_collection_and_field_matches(web_model):
    assert set(web_model["C"]) == set(schema.COLLS)
    for coll, web in web_model["C"].items():
        got = [(f["k"], f["l"], f["t"], f["o"], f["wide"]) for f in schema.FIELDS[coll]]
        want = [(f["k"], f["l"], f.get("t", "text"), f.get("o", []) if coll != "access" or f["k"] not in ("role", "status") else schema.T["aRole" if f["k"] == "role" else "aStatus"], bool(f.get("wide"))) for f in web["fields"]]
        assert got == want, coll


def test_every_screen_is_still_there():
    web = re.search(r"var NAMES = \{(.*?)\};", WEB, re.S).group(1)
    desk = re.search(r"var NAMES = \{(.*?)\};", DESK, re.S).group(1)
    assert web == desk
    assert set(re.findall(r"(\w+):", web)) == set(["home", "dash", "rem", "emerg", "assets", "liab", "cover", "docs", "ids", "will", "wish", "plan", "drive"])


# actions of the browser version that no longer exist, and why (each has a desktop replacement)
REMOVED = {
    "st-create": "account creation moved to the sign-in screen", "st-link": "browser file handles: replaced by Extra encrypted copies folders",
    "st-reconnect": "same", "st-unlink": "same", "drive-test": "claude.ai-only Google Drive connector (use a Drive folder copy)",
    "drive-save": "same", "drive-find": "same", "drive-pick": "same", "drive-load": "same",
}


def test_no_user_action_was_lost():
    acts = lambda t: set(re.findall(r"data-act=\"([\w-]+)\"", t)) | set(re.findall(r"act === '([\w-]+)'", t))
    lost = acts(WEB) - acts(DESK) - set(REMOVED)
    assert lost == set(), lost


def test_advisor_dashboard_emergency_and_voice_code_unchanged():
    for needle in ["function localAnswer", "function vDash", "function vEmerg", "function toggleVoice", "function qaFill", "function parseAll", "function vIds", "function vWill", "function vWish", "function vDrive", "function context0"]:
        assert needle in WEB, needle
        assert needle in DESK, "lost in desktop: " + needle


def test_browser_storage_and_crypto_code_is_gone():
    for bad in ["localStorage", "indexedDB", "crypto.subtle", "showSaveFilePicker", "PBKDF2", "VAULT_KEY"]:
        assert bad not in DESK, bad


def test_no_hardcoded_credentials_or_urls_in_python():
    src = "\n".join(p.read_text("utf-8") for p in (ROOT / "kinkeep_desktop").glob("*.py"))
    assert not re.search(r"(password|secret|api[_-]?key)\s*=\s*[\"'][^\"']{6,}[\"']", src, re.I)
    assert "smtp.gmail.com" in src and not re.search(r"https?://(?!www\.w3\.org)[a-z0-9.-]+\.(com|net|io)/api", src)


def test_roles_exist_in_ui_and_engine():
    for role in ["Owner", "Co-owner", "Adult Family Member", "Emergency Contact"]:
        assert role in DESK and role in schema.T["aRole"]
