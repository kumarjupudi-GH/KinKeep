# Install and configure KinKeep Desktop

## Install
**Windows 10/11:** unzip `KinKeep-windows.zip`, run `KinKeep\KinKeep.exe` (or build the optional installer with Inno Setup, `packaging/installer.iss`). Needs the Microsoft Edge WebView2 runtime (already on Windows 11 and most Windows 10).
**macOS 11+:** unzip `KinKeep-macos.zip`, drag `KinKeep.app` to Applications. Unsigned builds: right-click, Open, the first time.
**From source (any OS, Python 3.10+):**
```
pip install -r requirements.txt
python tools/build_ui.py
python -m kinkeep_desktop
```
Build the apps yourself: `python packaging/build.py` on each OS (see README).

## Where your data lives
`Documents/KinKeep Data` (change with `--data-dir FOLDER` or the `KINKEEP_DATA` variable):
| File | What |
|---|---|
| `kinkeep.vault.json` | The encrypted vault (authoritative) |
| `kinkeep.data.xlsx` | Password-protected spreadsheet copy |
| `account.json` | Name, email, login, question *text*, and **hashed** answers (not encrypted, so the sign-in screen can use it) |
| `backups/` | Last 15 earlier vaults and spreadsheets |
| `exports/` | Where backups go if no dialog is available |
Uninstalling the app never deletes this folder.

## First run
1. Create your account: name, email, date of birth, login, master password (10+ characters), three questions.
2. **Email codes.** Pick your provider and paste an **app password** (not your normal password):
   Gmail: Google Account > Security > App passwords. Outlook: enable SMTP AUTH, then an app password. Yahoo / iCloud: app-specific password. Other providers: open *Other provider settings* and enter server, port, security.
   KinKeep sends the code from *your* mailbox to yourself; no KinKeep server exists. Skipping this enables **demo mode**, where the code is shown on screen and is *not* a second factor.
3. Save the **recovery key** shown once. Print or save the recovery sheet and keep it away from the computer.
4. Optional: start from a backup (desktop vault, spreadsheet, or a backup from the browser version).

## Family sign-ins
Add a person under **Continuity** (name, role), then **Storage and Security > Family sign-ins > Give a sign-in** (login, their email, a starting password). They also get emailed codes.
Roles: *Owner* everything; *Co-owner* everything except changing Owners/Co-owners and owner-only actions; *Adult Family Member* everything except sealed will/wish notes, read-only will and wish screens; *Teen* own documents and IDs, read-only; *Viewer* read-only overview; *Emergency Contact* emergency essentials only, and only while the Owner has allowed emergency access.

## Extra encrypted copies
Storage and Security > *Extra encrypted copies*: choose a folder (inside Google Drive for desktop, OneDrive, or a USB drive). Both files are copied there after each change. They stay encrypted.

## Settings
Idle lock: 10 minutes. Spreadsheet encryption: AES-256 by default; an AES-128 compatibility mode exists for very old Excel.
