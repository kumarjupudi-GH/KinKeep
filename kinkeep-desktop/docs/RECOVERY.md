# Backup and disaster recovery

## What to back up
Copy the whole `KinKeep Data` folder, or use **Storage and Security > Backup copies**:
* **Vault backup (.json)**: encrypted; opens with your master password or recovery key. Contains your family list but **no family logins**.
* **Spreadsheet backup (.xlsx)**: opens with your master password in Excel/LibreOffice (Owner only).
Backups from Windows restore on macOS and the other way round. To restore on a new computer choose *A backup I already have* when creating the account (you may choose a new master password). To restore into a running vault: Storage and Security > *Restore from a backup* (Owner only). After any restore, everyone except the Owner has the status **Needs re-approval** and must be given a sign-in again.

## If KinKeep will not open or no longer exists
You only need the file **`kinkeep.data.xlsx`** (from the data folder, an extra-copies folder, a USB drive or a spreadsheet backup) and your **master password**.
1. Double-click it in Microsoft Excel, or LibreOffice Calc (*File > Open*).
2. Enter your master password when asked.
3. Each KinKeep module is a sheet: Assets, Liabilities, Insurance, Documents, Identity, WillAndTrust, MedicalAndWishes, Reminders, Contacts, FamilyAccess, plus Settings (continuity notes, exchange rate) and Checklists. Start at the README sheet.
4. Save a copy elsewhere if you want to keep editing it.
Other programs: anything that opens password-protected `.xlsx` (Office 2010+ "Encrypt with password") works, for example `msoffcrypto-tool in.xlsx out.xlsx -p PASSWORD` on the command line.
No Office program? `python tools/kk_recover.py kinkeep.data.xlsx --csv` (needs `pip install cryptography openpyxl`) writes one CSV per sheet. The same tool opens `kinkeep.vault.json` with your password **or recovery key**.
**The spreadsheet opens only with the master password.** The recovery key opens the vault, not the spreadsheet. If you change your password, the spreadsheet is rewritten with the new one; older spreadsheet backups keep the password they were saved with.

## Common situations
| Situation | What to do |
|---|---|
| Forgot password | Sign-in screen > Forgot your password: 3 answers + emailed code + **recovery key** keeps all records. Without the recovery key the old vault is archived under `backups/old-vault-...` and you start empty (restore it with the old password) |
| No email access at sign-in | Owner: *Use my recovery key instead* on the code screen |
| Vault file damaged | Open KinKeep normally: it falls back to `kinkeep.vault.json.bak`, then the newest file in `backups/`, and rewrites the main file |
| Spreadsheet damaged/missing | KinKeep recreates it at the Owner's next sign-in; damaged files are kept in `backups/` |
| Spreadsheet edited in Excel | KinKeep offers to import the changes or keep its data. Importing never grants access: new people need re-approval and nobody becomes Owner |
| Spreadsheet looks old | When a family member (not the Owner) saves, the spreadsheet is refreshed at the Owner's next sign-in. For the freshest copy, sign in as Owner |
| Lost computer | New computer, install, *A backup I already have*. Rotate your recovery key afterwards |
| Lost master password **and** recovery key | Not recoverable by anyone. This is by design |

## Routine
Monthly: *Save a spreadsheet backup* to a USB drive or an extra-copies folder. Yearly: open the spreadsheet in Excel/LibreOffice with your password to prove it works, and re-read your recovery sheet.
