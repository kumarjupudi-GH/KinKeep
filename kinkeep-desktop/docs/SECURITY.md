# Security design and trade-offs

## Design
* **Vault** (`kinkeep.vault.json`): a random 256-bit data key encrypts records with **AES-256-GCM**. The data key is wrapped once per *key slot*: the Owner's master password (**Argon2id**, 64 MiB, 3 passes, 4 lanes, random salt), the **recovery key** (160 random bits, HKDF), and one slot per family sign-in. Changing a password re-wraps the key; nothing else changes. The sequence number is bound into the ciphertext, so an old file cannot be passed off as a newer one, and any change to the file is detected.
* **Security answers**: normalised then **scrypt** (N=2^15) with a random salt. They are a *check*, never a key.
* **Second factor**: 6-digit email code, 10 minutes, single use, 5 tries, 25 s cooldown, 6 per hour, stored only as salted hashes in memory. The Owner can alternatively use the printed recovery key.
* **Sign-in errors are generic** ("login name or password is not correct"), failures are rate limited with growing delays.
* **Files**: every write is to a temporary file, flushed, then renamed. Before replacing anything, the new copy is decrypted again and compared; a mismatch aborts the save. A sequence number rejects saves from a stale screen.
* **The page is not trusted**: it never holds a key; the engine filters data by role before sending it and merges saves back, refusing anything the role may not change. A strict content-security policy allows no external requests. Only whitelisted `https` links are opened, in your browser.
* No credentials are in the code. The email app password is kept inside the encrypted vault (and, if the `keyring` package is present, in the OS credential store so reset emails can be sent while locked).

## The spreadsheet trade-off (please read)
You asked for a spreadsheet that opens in ordinary software if KinKeep disappears. That forces these compromises:
1. **Weaker key derivation.** Office password encryption (AES-256, SHA-512, 100,000 rounds) is much cheaper to brute-force than Argon2id. Anyone who copies `kinkeep.data.xlsx` can try passwords offline faster than against the vault. **The spreadsheet is the weakest link; the master password must be long** (four or more random words). A standard-compatibility mode (AES-128, SHA-1, 50,000 rounds) exists and is weaker still; leave it off unless needed.
2. **One password, two files.** The spreadsheet opens with the *master password*, not the recovery key. If the master password is lost, only the vault can be recovered (with the recovery key).
3. **Roles do not exist inside the spreadsheet.** It holds everything the Owner sees, including will notes and wishes that an Adult Family Member cannot read in KinKeep. Anyone with the master password and the file bypasses roles. Roles protect people *using KinKeep*, not people with the password.
4. **Spreadsheet edits are untrusted input.** Imports are rebuilt field by field, text is stored as text (no formulas run), and the FamilyAccess sheet cannot grant access.
5. **Copies multiply risk.** Extra-copy folders and backups hold the same data. They are encrypted, but they are as strong as your password.
6. **Not written for non-Owners.** Only the Owner's session knows the master password, so the spreadsheet is refreshed when the Owner signs in.

## Other limits
* **Demo mode is not 2FA.** If no email is configured the code appears on screen.
* **Email as a factor** is only as strong as your mailbox; use a strong mailbox password and 2-step verification there.
* **Unencrypted profile.** `account.json` holds name, email, date of birth, login, question text. Answers and passwords are not in it.
* **Malware on the computer** that can read memory or log keys defeats any local app. Keep the OS updated; use full-disk encryption (BitLocker, FileVault).
* **Removing a person** stops future access, but cannot unsee what they already viewed or copied.
* **Not independently audited.** The Office-format encryption is a from-scratch implementation checked against LibreOffice; have the code reviewed before storing real records. Packaged builds are unsigned unless you sign them.
* Roles for Teen/Viewer/Emergency Contact are enforced by the engine, but the family list is data entered by the Owner: review it.
