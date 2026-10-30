# KinKeep source

KinKeep is a single-file web app: all HTML, CSS and JavaScript live in `src/kinkeep.html`. There is no framework and no build step for the app itself.

- `src/kinkeep.html`  the whole app (edit this)
- `src/img/`          the three storyboard pictures shown on the Home page
- `build_pwa.py`      wraps the app into an installable package (`dist/`) and `kinkeep-app.zip`. Needs Python 3 and Pillow (`pip install pillow`). It embeds the pictures into index.html, writes manifest, service worker and icons.
- `dist/`             the last built package, ready to upload to any https host
- `tests/vault-test.js`  Playwright test of the passphrase vault (serve `dist/` on http://localhost:8765 first, then `node tests/vault-test.js`)

Build: `python3 build_pwa.py`
Try locally: `cd dist && python3 -m http.server 8765`, open http://localhost:8765

Notes
- Data is encrypted in the browser (AES-GCM, PBKDF2-SHA256 250,000 rounds). The passphrase is never stored.
- The Google Drive connector and the Claude-powered answers only work when the page runs inside claude.ai. Elsewhere the app uses its built-in local logic and linked-file storage.
- Prototype with fictional sample data. Have the security reviewed before storing real family records.

## Account, email codes and sign-in
- Registration (name, email, date of birth, login name, password, three favorite questions) -> email code -> storage choices.
- Sign-in = login name + password, then an emailed 6-digit code. After the app locks itself (10 minutes idle) only the password is asked again; Sign out or closing the app asks for a code again.
- Forgot password: the three questions (two tries, case and spacing ignored). A match lets you set a new password. Two mismatches send an emailed code instead; entering it lets you set a new password.
- A new password cannot open records encrypted with the old one. The old data is kept as an encrypted backup file you can restore with the old password.
- Email: a static page cannot send email. Without a service it runs in DEMO MODE (the code is shown on screen). For real email run `email-server/` (see its README) and set its address in `dist/config.js` or build with `KINKEEP_MAIL=https://your-service python3 build_pwa.py`.
- `tests/auth-test.js` runs the whole flow (serve dist on :8765; MODE=server SRVLOG=<log> for the real service in DEV_LOG_CODES mode).
