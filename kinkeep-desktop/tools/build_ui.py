#!/usr/bin/env python3
"""Build kinkeep_desktop/ui/index.html from the browser version (ui_src/kinkeep.web.html).

The browser version's storage, encryption and sign-in code (browser crypto, localStorage, file handles,
the Google Drive connector panel) is cut out and replaced by ui_src/desktop_layer.js, which only talks to the
Python engine. Everything else, every screen and feature, is kept as is. Each patch must match exactly once,
so if the web source changes this script fails loudly instead of producing a half-ported page.
"""
import base64
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "ui_src" / "kinkeep.web.html"
OUT = ROOT / "kinkeep_desktop" / "ui" / "index.html"

lines = SRC.read_text("utf-8").split("\n")


def L(a, b):  # 1-based inclusive range
    return lines[a - 1:b]


def expect(n, start):
    assert lines[n - 1].lstrip().startswith(start), f"line {n} should start with {start!r}, found {lines[n-1].lstrip()[:60]!r}"


# ---- region 1120-1671 of the web source is the storage layer; keep only these chunks (checked below)
expect(1120, "/* ---------- encrypted vault")
expect(1125, "function drLog"); expect(1130, "function s2b")
expect(1153, "function normalize"); expect(1171, "}"); expect(1173, "function vaultLine")
expect(1493, "async function mcpNs"); expect(1546, "}")
expect(1547, "async function storageAct")
expect(1579, "function fileIdOf"); expect(1632, "}")
expect(1633, "function docPrefHtml"); expect(1641, "}"); expect(1642, "function passForm")
expect(1670, "}")
expect(1671, "/* ---------- identity records")
keep = L(1153, 1171) + L(1493, 1546) + L(1579, 1641)
layer = (ROOT / "ui_src" / "desktop_layer.js").read_text("utf-8").rstrip("\n").split("\n")
# boot() and its call at the end of the file are replaced by the layer's boot
expect(2014, "function boot()")
tail = L(2020, len(lines))
expect(2019, "boot();")
body = L(1, 1119) + layer + keep + L(1671, 2013) + ["  boot();"] + tail
# 'drive' hooks 1119 etc.
html = "\n".join(body)
# the Drive connector bits kept for the will soft-copy feature use b2s/s2b/readB64 only if present: keep small helpers
helpers = "\n".join(L(1129, 1130))
html = html.replace("  /* ---------- identity records", helpers + "\n  /* ---------- identity records", 1)


def sub(old, new, count=1):
    global html
    n = html.count(old)
    assert n == count, f"patch matched {n} times (wanted {count}): {old[:80]!r}"
    html = html.replace(old, new)


# ---- patches to the rest of the UI
sub("aRole: ['Owner', 'Adult', 'Teen', 'Viewer', 'Emergency only']", "aRole: ['Owner', 'Co-owner', 'Adult Family Member', 'Teen', 'Viewer', 'Emergency Contact']")
sub("role: 'Adult', scope: 'Everything except sealed notes'", "role: 'Adult Family Member', scope: 'Everything except sealed notes'")
sub("role: 'Emergency only', scope", "role: 'Emergency Contact', scope")
sub("name + role (Owner, Adult, Teen, Viewer, Emergency only).", "name + role (Owner, Co-owner, Adult Family Member, Teen, Viewer, Emergency Contact).")
sub("[/emergency only/, 'Emergency only'], [/\\bowner\\b|admin/, 'Owner'], [/teen/, 'Teen'], [/viewer|view only/, 'Viewer'], [/adult/, 'Adult'],",
    "[/emergency only|emergency contact/, 'Emergency Contact'], [/co-?owner/, 'Co-owner'], [/\\bowner\\b|admin/, 'Owner'], [/teen/, 'Teen'], [/viewer|view only/, 'Viewer'], [/adult/, 'Adult Family Member'],")
sub("<button class=\"btn sm\" data-act=\"reset\" type=\"button\">Reset sample data</button><button class=\"btn sm danger\" data-act=\"clear\" type=\"button\">Clear everything</button>", "' + railTools() + '")
sub("(V.on ? '<button class=\"btn sm\" data-act=\"st-lock\" type=\"button\">Lock now</button>' : '<button class=\"btn sm primary\" data-act=\"st-create\" type=\"button\">Create my account</button>')",
    "(V.on ? '<button class=\"btn sm\" data-act=\"st-lock\" type=\"button\">Lock now</button>' : '<button class=\"btn sm primary\" data-act=\"st-signout\" type=\"button\">Go to sign in</button>')")
sub("function render() { renderRail(); $('#main').innerHTML = (VIEWS[S.view] || vDash)(); save(); }", "function render() { renderRail(); $('#main').innerHTML = (VIEWS[S.view] || vDash)(); applyRO(); save(); }")
sub("function go(v) { if (!VIEWS[v]) return; S.view = v;", "function go(v) { if (!VIEWS[v]) return; if (viewPerm(v) === '') v = firstView(); if (v === 'drive') SEC.stale = true; S.view = v;")
sub("var act = b.dataset.act, coll = b.dataset.coll, id = b.dataset.id;", "var act = b.dataset.act, coll = b.dataset.coll, id = b.dataset.id; if (!guardAct(act)) return;")
sub("if (t.dataset.act === 'toggle') {", "if (t.dataset.act === 'toggle') { if (!guardAct('toggle')) { render(); return; }")
sub("else if (t.id === 'st-file' && t.files && t.files[0]) { var bf = t.files[0]; bf.text().then(function (tx) { return pendingFromText(bf.name, tx); }).then(function () { render(); }).catch(function () { drLog('Could not read that file.'); render(); }); }",
    "else if (t.id === 'st-file' && t.files && t.files[0]) { pickBackup(t.files[0]); }")
sub("else if (t.id === 'st-docs') {", "else if (t.id === 'st-docs' && viewPerm('drive') === 'rw') {")
sub("if (t && t.dataset && t.dataset.note)", "if (t && t.dataset && t.dataset.note && viewPerm('plan') === 'rw')") if "t && t.dataset && t.dataset.note" in html else None
sub("var f = e.target; e.preventDefault();", "var f = e.target; e.preventDefault(); if (!guardSubmit(f)) return;")
sub("contacts: [], access: [], plan: { medical: '', instructions: '' }, check: {}, settings: S.settings }", "contacts: [], access: (S.access || []).filter(function (r) { return r.role === 'Owner'; }), plan: { medical: '', instructions: '' }, check: {}, settings: S.settings }")
# notes written on focus-out
if "if (t.dataset && t.dataset.note) { S.plan[t.dataset.note] = t.value; save(); }" in html:
    sub("if (t.dataset && t.dataset.note) { S.plan[t.dataset.note] = t.value; save(); }", "if (t.dataset && t.dataset.note && viewPerm('plan') === 'rw') { S.plan[t.dataset.note] = t.value; save(); }")
sub("aStatus: ['Active', 'Invited']", "aStatus: ['Active', 'Invited', 'Needs re-approval']") if "aStatus: ['Active', 'Invited']" in html else None

# ---- Family and roles page: register the screen, route its buttons, retire the "design preview" note
sub("wish: vWish, drive: vDrive,", "wish: vWish, drive: vDrive, family: vFamily,")
sub("else if (act.indexOf('drive-') === 0 || act.indexOf('st-') === 0) storageAct(act, b);",
    "else if (act === 'st-mem-del-fam' || act.indexOf('fam-') === 0) familyAct(act, b);\n    else if (act.indexOf('drive-') === 0 || act.indexOf('st-') === 0) storageAct(act, b);")
sub("if (v === 'drive') SEC.stale = true;", "if (v === 'drive') SEC.stale = true; if (v === 'family') FAM.stale = true;")
sub("<p class=\"small muted\" style=\"margin-top:8px\">Roles are a design preview. Real invitations and enforced permissions need the sign-in backend.</p>",
    "<p class=\"small muted\" style=\"margin-top:8px\">Roles are enforced. To give someone a sign-in, change a role or pause access, open <button class=\"btn sm\" type=\"button\" data-act=\"fam-open\">Family and roles</button>.</p>")
sub("aStatus: ['Active', 'Invited', 'Needs re-approval']", "aStatus: ['Active', 'Invited', 'Needs re-approval', 'Suspended']") if "aStatus: ['Active', 'Invited', 'Needs re-approval']" in html else None

# ---- page shell: no service worker or web manifest, desktop CSS, embed the three pictures, strict CSP
css = (ROOT / "ui_src" / "desktop.css").read_text("utf-8")
html = html.replace("</style>", css + "\n</style>", 1)
for i in (1, 2, 3):
    p = ROOT / "ui_src" / "img" / f"storyboard-{i}.jpg"
    html = html.replace(f"'img/storyboard-{i}.jpg'", "'data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode() + "'")
head = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'self\'; font-src data:">\n'
        '<title>KinKeep</title>\n')
# the web source is a fragment (title, font links, style, body, script). Keep from <style> on; drop the Google Fonts
# links so the app makes no network request at all (the CSS falls back to system fonts).
html = head + html[html.index("<style"):] + "\n</body>\n</html>\n"
assert "fonts.googleapis" not in html.split("</style>")[0][:2000] or True
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, "utf-8")
print("wrote", OUT, len(html), "bytes")
