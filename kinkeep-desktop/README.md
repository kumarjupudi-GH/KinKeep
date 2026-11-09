# KinKeep Desktop

Secure, offline-first, family-owned records for Windows and macOS. Python engine, native window, encrypted vault, and a password-protected spreadsheet you can open without KinKeep.

* Plan and parity record: `docs/MIGRATION_PLAN.md`
* Beginner install guide (step by step): `docs/INSTALL_STEP_BY_STEP.md`
* Install and set up (short): `docs/INSTALL.md`
* Backup and disaster recovery: `docs/RECOVERY.md`
* Security and trade-offs: `docs/SECURITY.md`

## Develop
```
pip install -r requirements-dev.txt && python -m playwright install chromium
python tools/build_ui.py          # rebuild kinkeep_desktop/ui/index.html from ui_src/
python -m pytest                  # functional, security, data-integrity, parity, UI end-to-end
python -m kinkeep_desktop         # run (add --data-dir FOLDER to keep data elsewhere)
python packaging/build.py         # build .exe / .app on the OS you are on
```
The UI tests need `node` (parity) and Chromium; LibreOffice with python-uno enables the "opens without KinKeep" test, otherwise it is skipped.
