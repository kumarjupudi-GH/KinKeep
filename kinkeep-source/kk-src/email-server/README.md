# KinKeep email-code service

KinKeep is a static web app, so it cannot send email by itself. This small service sends the 6-digit codes
(registration, sign-in, password reset) and checks them, so the code never reaches the browser.

1. Install Node 18+ and run `npm install` in this folder.
2. Set `SMTP_URL` (for example `smtps://user:password@smtp.gmail.com:465`, using an app password), `MAIL_FROM`
   and `ALLOWED_ORIGIN` (the address where KinKeep is hosted).
3. `node otp-server.js`. Put it behind https (a reverse proxy, or a host such as Render, Railway or Fly).
4. In the KinKeep package edit `config.js` and set `mailEndpoint` to the service address, for example
   `window.KINKEEP_CONFIG = { mailEndpoint: "https://codes.example.com" };`

Local test without email: `DEV_LOG_CODES=1 node otp-server.js` prints each code in the terminal.

Limits built in: 6 digits, expires in 10 minutes, 5 tries per code, one code per 25 seconds and 6 per hour per address.
An https KinKeep page can only call an https service.
