#!/usr/bin/env python3
"""Open your KinKeep data WITHOUT the KinKeep app.

  python kk_recover.py kinkeep.data.xlsx            -> asks for your master password, writes a readable copy
  python kk_recover.py kinkeep.vault.json           -> asks for your master password or recovery key, writes JSON
  options: --out FOLDER   --csv   (one CSV file per sheet instead of an .xlsx)

Needs Python 3.10+ and:  pip install cryptography openpyxl
The readable copy is NOT encrypted. Save it somewhere safe and delete it when you are done.
You do not need this tool to read the spreadsheet: Excel or LibreOffice open it with your password (see docs/RECOVERY.md).
"""
import argparse
import csv
import getpass
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinkeep_desktop import crypto, officecrypt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--out", default="."); ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()
    blob = Path(a.file).read_bytes()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pw = getpass.getpass("Password (or recovery key for a vault file): ")
    if officecrypt.is_encrypted(blob):
        try:
            plain = officecrypt.decrypt(blob, pw)
        except officecrypt.WrongPassword:
            sys.exit("That password did not open the spreadsheet.")
        if not a.csv:
            dest = out / "KinKeep-readable.xlsx"; dest.write_bytes(plain); print("Wrote", dest); return
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(plain), data_only=True)
        for ws in wb:
            with open(out / f"{ws.title}.csv", "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows(ws.iter_rows(values_only=True))
        print("Wrote one CSV per sheet in", out); return
    env = crypto.parse_envelope(blob.decode("utf-8"))
    for slot in env["slots"]:
        try:
            dek = crypto.open_recovery_slot(slot, pw) if slot["type"] == "recovery" else crypto.open_password_slot(slot, pw)
            payload = crypto.open_with_dek(env, dek)
            dest = out / "KinKeep-readable.json"; dest.write_text(json.dumps(payload["data"], indent=1, ensure_ascii=False), "utf-8"); print("Wrote", dest); return
        except crypto.WrongPassword:
            continue
    sys.exit("That password or recovery key did not open the vault.")


if __name__ == "__main__":
    main()
