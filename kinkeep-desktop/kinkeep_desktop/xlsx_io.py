"""Spreadsheet side of the vault: every module gets its own sheet, readable without KinKeep.

The workbook is built in memory and encrypted in memory (officecrypt); no plaintext copy is written.
Account secrets (security answers, SMTP password, key slots) are NOT written to the spreadsheet.
"""
from __future__ import annotations
import hashlib
import io
import json
import datetime as dt

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import officecrypt, schema

FORMAT = "KinKeep spreadsheet v1"

README = [
    "KinKeep data spreadsheet",
    "",
    "This file holds a copy of all your KinKeep records, one sheet per module. It is encrypted with your",
    "KinKeep master password, so you can open it in Microsoft Excel, LibreOffice Calc or any program that",
    "supports Office password-protected workbooks, even if KinKeep itself is not available.",
    "",
    "How to read it:",
    "  - The sheets Assets, Liabilities, Insurance, Documents, Identity, WillAndTrust, MedicalAndWishes,",
    "    Reminders, Contacts and FamilyAccess each list one record per row.",
    "  - Settings holds the exchange rate and the family notes. Checklists holds ticked emergency steps.",
    "  - The first column of each record sheet (id) is KinKeep's internal reference. Leave it alone.",
    "  - Amounts are in the currency named in the Currency column. Dates are YYYY-MM-DD.",
    "",
    "If you edit this file by hand, close it, then open KinKeep: it will offer to import your changes.",
    "Edits are only picked up if you keep the sheet names, header row and id column unchanged.",
    "Never type a full ID number: KinKeep only keeps the last 4 characters.",
]


def canon(o):
    """Canonical form used for the consistency hash (ints and integral floats compare equal)."""
    if isinstance(o, dict):
        return {k: canon(o[k]) for k in sorted(o)}
    if isinstance(o, list):
        return [canon(x) for x in o]
    if isinstance(o, float) and o == int(o):
        return int(o)
    return o


def content_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(canon(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _set(ws, r, c, v):
    cell = ws.cell(row=r, column=c)
    if isinstance(v, str):
        cell.value = v
        cell.data_type = "s"  # never let a text value such as "=1+1" become a formula
    else:
        cell.value = v
    return cell


def build_workbook(data: dict, seq: int, saved_at: str) -> bytes:
    data = schema.normalize(data)
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    for i, line in enumerate(README, 1):
        _set(ws, i, 1, line)
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 110
    head_fill = PatternFill("solid", fgColor="D9F2E4")
    for coll in schema.COLLS:
        ws = wb.create_sheet(schema.SHEET[coll])
        cols = [("id", "id")] + [(f["k"], f["l"]) for f in schema.FIELDS[coll]]
        if coll == "reminders":
            cols.append(("done", "Done"))
        for ci, (_, label) in enumerate(cols, 1):
            c = _set(ws, 1, ci, label)
            c.font = Font(bold=True)
            c.fill = head_fill
            c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.column_dimensions[get_column_letter(ci)].width = 14 if ci == 1 else 24
        for ri, row in enumerate(data[coll], 2):
            for ci, (k, _) in enumerate(cols, 1):
                v = row.get(k, "")
                if k == "done":
                    v = "yes" if v else "no"
                _set(ws, ri, ci, v)
        ws.freeze_panes = "B2"
    ws = wb.create_sheet("Settings")
    rows = [("key", "value"), ("rate", data["rate"]), ("rateDate", data["rateDate"]), ("docStore", data["settings"]["docStore"]),
            ("plan.medical", data["plan"]["medical"]), ("plan.instructions", data["plan"]["instructions"])]
    for ri, (k, v) in enumerate(rows, 1):
        _set(ws, ri, 1, k)
        _set(ws, ri, 2, v)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 90
    ws = wb.create_sheet("Checklists")
    for ci, h in enumerate(("playbook", "step", "done"), 1):
        _set(ws, 1, ci, h).font = Font(bold=True)
    r = 2
    for pb, steps in sorted(data["check"].items()):
        for step, done in sorted(steps.items()):
            _set(ws, r, 1, pb); _set(ws, r, 2, step); _set(ws, r, 3, "yes" if done else "no"); r += 1
    ws = wb.create_sheet("Meta")
    counts = {coll: len(data[coll]) for coll in schema.COLLS}
    meta = [("format", FORMAT), ("vault_seq", seq), ("saved_at", saved_at), ("content_sha256", content_hash(data)),
            ("counts", json.dumps(counts, sort_keys=True))]
    for ri, (k, v) in enumerate(meta, 1):
        _set(ws, ri, 1, k)
        _set(ws, ri, 2, v)
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 70
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def encrypt_workbook(data: dict, seq: int, password: str, mode: str = "agile") -> bytes:
    saved = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return officecrypt.encrypt(build_workbook(data, seq, saved), password, mode)


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return int(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.date().isoformat() if isinstance(v, dt.datetime) else v.isoformat()
    return v


def read_workbook(plain: bytes) -> tuple[dict, dict]:
    """Return (data, meta) from a decrypted workbook. Raises ValueError if the layout is not KinKeep's."""
    try:
        wb = load_workbook(io.BytesIO(plain), data_only=True)
    except Exception as e:
        raise ValueError("The spreadsheet could not be read.") from e
    if "Meta" not in wb.sheetnames:
        raise ValueError("This spreadsheet is not a KinKeep data file.")
    meta = {}
    for row in wb["Meta"].iter_rows(values_only=True):
        if row and row[0]:
            meta[str(row[0])] = _clean(row[1]) if len(row) > 1 else ""
    if meta.get("format") != FORMAT:
        raise ValueError("This spreadsheet is not a KinKeep data file.")
    data = schema.empty_state()
    for coll in schema.COLLS:
        title = schema.SHEET[coll]
        if title not in wb.sheetnames:
            raise ValueError("The sheet %s is missing." % title)
        rows = list(wb[title].iter_rows(values_only=True))
        if not rows:
            continue
        label_to_key = {"id": "id", "Done": "done"}
        label_to_key.update({f["l"]: f["k"] for f in schema.FIELDS[coll]})
        keys = [label_to_key.get(str(h)) if h is not None else None for h in rows[0]]
        if "id" not in keys:
            raise ValueError("The sheet %s has no id column." % title)
        for r in rows[1:]:
            if not any(x not in (None, "") for x in r):
                continue
            o = {}
            for k, v in zip(keys, r):
                if k is None:
                    continue
                v = _clean(v)
                if k == "done":
                    v = str(v).strip().lower() in ("yes", "true", "1", "x")
                o[k] = v
            if not o.get("id"):
                o["id"] = schema.nid()
            data[coll].append(o)
    if "Settings" in wb.sheetnames:
        st = {str(r[0]): _clean(r[1]) for r in wb["Settings"].iter_rows(values_only=True) if r and r[0]}
        data["rate"] = st.get("rate") or 85
        data["rateDate"] = str(st.get("rateDate") or schema.iso(0))
        data["settings"]["docStore"] = st.get("docStore") or ""
        data["plan"] = {"medical": str(st.get("plan.medical") or ""), "instructions": str(st.get("plan.instructions") or "")}
    if "Checklists" in wb.sheetnames:
        for r in list(wb["Checklists"].iter_rows(values_only=True))[1:]:
            if r and r[0] and r[1] is not None:
                data["check"].setdefault(str(r[0]), {})[str(_clean(r[1]))] = str(r[2]).lower() == "yes"
    return schema.normalize(data), meta
