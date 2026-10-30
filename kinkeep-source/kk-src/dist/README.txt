KinKeep, installable app package
=================================
What this is: a static website (no server code, no accounts). Put these files on any https host and open the address.
Start: double-click KinKeep.html (the app),. On Windows, double-click Create-KinKeep-Desktop-Shortcut.bat once to put a KinKeep shortcut with the KinKeep icon on your Desktop (a .html file itself cannot carry a custom icon). index.html only forwards to KinKeep.html and is there for web hosting. KinKeep-logo.png / .svg are the logo files.
Sign-in codes: KinKeep asks for an emailed 6-digit code at registration, sign-in and password reset. A static web app cannot send email, so out of the box it runs in DEMO MODE and shows the code on screen. For real email, run the small service in email-server/ (see its README) and put its address in config.js.
Install: in Chrome or Edge choose the install icon in the address bar (Install KinKeep). On Android Chrome use Add to Home screen / Install app. On iPhone Safari use Share, Add to Home Screen. Windows: Edge or Chrome, Install, and it appears in the Start menu.

Free hosting (pick one):
  GitHub Pages: create a repo, upload these files, Settings > Pages > deploy from branch.
  Netlify: drag this folder onto app.netlify.com/drop.
  Cloudflare Pages: Create project > Direct upload.
The address must be https (localhost also works for testing). Without https the browser refuses encryption and the app will not save.

How your data is kept
  Records are encrypted in the browser (AES-GCM, key from your passphrase via PBKDF2, 250,000 rounds). The passphrase is never stored. Forget it and the data cannot be recovered; keep a backup copy and remember its passphrase.
  Storage choices: on this device (always), a file you choose such as your Documents folder or your Google Drive folder (Chrome/Edge on a computer), and encrypted backup files.
  Google Drive sign-in through the claude.ai connector only works when the page is open inside claude.ai. In the installed app use a file in your Google Drive folder instead.

Honest limits
  This is a prototype. Do not enter real account numbers or upload real identity documents until the security has been independently reviewed. Voice input depends on the browser; typing always works. Reminders show inside the app only; there are no email or phone alerts yet. Microsoft Store or Google Play listings need extra packaging (PWABuilder can wrap this folder).
