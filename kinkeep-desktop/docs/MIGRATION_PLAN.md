# KinKeep: browser app to desktop app, migration plan and parity record

## 1. What the existing app was
A single-file web app (`kinkeep.html`, about 2,000 lines, no framework). Findings that shaped the plan:

| Area | Browser version | Problem for a desktop product |
|---|---|---|
| Storage | Encrypted JSON in `localStorage`, optional linked file | Tied to one browser profile; easy to lose |
| Crypto | WebCrypto, PBKDF2-SHA256 250k, AES-GCM | Fine, but runs in the page, next to the UI |
| Accounts | Profile + 3 answers (PBKDF2 hashes) in `localStorage` | Same |
| 2FA | 6-digit email code from a separate Node service, or **demo mode** showing the code on screen | Needs a server; demo mode is not a second factor |
| Roles | Owner, Adult, Teen, Viewer, Emergency only, **stored as data, never enforced** | Anyone signed in saw everything |
| Drive | claude.ai Google Drive connector | Only works inside claude.ai |
| Recovery | Forgot password = 3 questions **or** email code; data then unreadable | Questions alone replaced the second factor |

## 2. Approach: reuse the whole UI, replace the engine
Rewriting about 1,900 lines of working screens in a Python GUI toolkit would risk the feature loss you asked me to avoid. Instead:

* **The UI is kept.** Every screen, form, the dashboard, the advisor, voice entry, emergency checklists, renewals and the will/medical modules are the original code, rendered in a native window (pywebview: WebView2 on Windows, WKWebView on macOS).
* **Everything that matters moved to Python.** Encryption, files, sign-in, OTP, roles and backups live in `kinkeep_desktop/` and are reachable from the page only through one narrow API (`app.make_js_api`).
* `tools/build_ui.py` builds the desktop page from the unchanged web source (`ui_src/kinkeep.web.html`): it cuts out the browser storage/crypto/sign-in code and splices in `ui_src/desktop_layer.js`. Every patch must match exactly once, so drift fails the build.

## 3. Module map
| Module | Job |
|---|---|
| `crypto.py` | Argon2id key slots, AES-256-GCM vault envelope, recovery key, salted scrypt answer hashes, opens old browser backups |
| `store.py` | Atomic saves, backup rotation, vault/spreadsheet consistency, crash recovery, restore, family logins |
| `officecrypt.py`, `cfb.py` | Password encryption of `.xlsx` in the standard Office format (MS-OFFCRYPTO), so Excel/LibreOffice open it |
| `xlsx_io.py` | One sheet per module, README, Settings, Checklists, Meta |
| `access.py` | Roles, per-screen read/write, data filtering, safe merge of saves |
| `otp.py` | Email codes through your own mailbox (SMTP): 10 min, 5 tries, 25 s cooldown, 6/hour |
| `bridge.py` | The API the screen calls; every method is role-checked |
| `app.py` | Window, native dialogs, single-instance lock, test bridge |

## 4. Requirements checklist
| # | Requirement | Status | Where / evidence |
|---|---|---|---|
| 1 | All features kept | Done, machine-checked | `tests/test_parity.py`: every collection, field, select list, screen and user action of the original is present |
| 2 | Python desktop, Windows + macOS, offline | Built; **packaging not run here** (see below) | `packaging/`, `.github/workflows/desktop.yml` |
| 3 | Encrypted JSON vault, master password | Done | `crypto.py`, `test_crypto.py`, `test_no_plaintext_anywhere_on_disk` |
| 4 | Encrypted `.xlsx`, sheet per module, file-level encryption | Done; opened by LibreOffice (agile and standard) | `test_libreoffice_opens_without_kinkeep` |
| 5 | Open without KinKeep + instructions | Done | `docs/RECOVERY.md`, `tools/kk_recover.py` |
| 6 | 2FA + 3 questions as extra check, answers salted-hashed | Done; questions can never replace the email code | `test_bridge_auth.py` |
| 7 | Roles: Owner, Co-owner, Adult Family Member, Emergency Contact (Teen, Viewer kept) | Done and enforced | `test_access_roles.py`, `test_viewer_sees_read_only_screens` |
| 8 | Backups: vault JSON, spreadsheet, export/import, cross-platform | Done | `test_store_integrity.py` |
| 9 | 6-digit email OTP, minimal setup | Done: provider presets + app password | `otp.py` |
| 10 | JSON and spreadsheet consistent; autosave; interrupted writes | Done | atomic writes, verify-before-replace, sequence numbers, `test_interrupted_write...`, `test_stale_screen...` |
| 11 | No hardcoded credentials; trade-offs explained | Done | `docs/SECURITY.md` |

## 5. Deliberate changes from the browser version (please review)
1. **Roles are now enforced.** *Adult* became **Adult Family Member**; *Emergency only* became **Emergency Contact**; **Co-owner** is new. Old values are mapped automatically. Teen and Viewer are kept.
2. **Forgot password needs the 3 answers AND the emailed code** (the browser version accepted either). The recovery key is what keeps your records; without it the old vault is archived and you start empty.
3. **Demo mode still exists** (no email configured) but is labelled as *not a real second factor*.
4. **Google Drive connector panel removed** (it only worked inside claude.ai). Replacement: *Extra encrypted copies* to any folder, such as Google Drive for desktop, OneDrive or a USB drive. The Drive link field on will records is unchanged.
5. **No Google Fonts request**: the app makes no network calls except the email codes you configure and links you click.
6. **New Family and roles page** (Family & Care): add people with a role, give or remove sign-ins, change roles, set a family member's password, pause and resume access (new status *Suspended*), approve people after a restore, emergency access, and a table of what each role can do. Rules are enforced in `store.py`/`bridge.py`, tested in `tests/test_family_roles.py`. A Co-owner cannot touch Owners or Co-owners; nobody can create a second Owner.
7. **Voice entry (mic buttons) uses the computer's own dictation.** The browser version used the Web Speech API, which streams audio to Google or Apple and does not work reliably inside an embedded window. The desktop app never starts it: the mic button focuses the box and, on Windows, presses Windows key + H for you (Mac: tell the person to press Fn twice). Tested in `tests/test_voice.py`; the real key press was not exercised on a Windows machine here.
8. **Family sign-ins are never restored from a backup.** People keep their role and relationship but must be approved again.

## 6. Not verified in this build environment
* The Windows `.exe` and macOS `.app` were **not built or launched** here: PyPI was blocked (no pywebview, PyInstaller) and PyInstaller cannot cross-compile. The spec, build script and CI workflow are provided and parse correctly. First run on each OS may need small fixes.
* The real pywebview window and native dialogs were not run; the UI was tested in headless Chromium against the real engine.
* The `.xlsx` was opened in **LibreOffice**, not Microsoft Excel.
* Sending real email (SMTP) was tested with a fake mailbox only.
