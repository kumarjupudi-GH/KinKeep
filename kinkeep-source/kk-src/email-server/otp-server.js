// KinKeep email-code service. Generates, emails and checks one-time codes so the code never reaches the browser.
// Run:  npm install && SMTP_URL="smtps://user:pass@smtp.example.com" MAIL_FROM="KinKeep <no-reply@yourdomain>" ALLOWED_ORIGIN="https://your-kinkeep-site" node otp-server.js
// Local test without email:  DEV_LOG_CODES=1 node otp-server.js   (codes are printed in this terminal instead of emailed)
const http = require('http'), crypto = require('crypto');
let nodemailer = null; try { nodemailer = require('nodemailer'); } catch (e) {}
const PORT = +process.env.PORT || 8787, ORIGIN = process.env.ALLOWED_ORIGIN || '*', FROM = process.env.MAIL_FROM || 'KinKeep <no-reply@localhost>', DEV = process.env.DEV_LOG_CODES === '1';
const transport = process.env.SMTP_URL && nodemailer ? nodemailer.createTransport(process.env.SMTP_URL) : null;
if (!transport && !DEV) { console.error('Set SMTP_URL (and run npm install) to send real email, or set DEV_LOG_CODES=1 to print codes here for testing.'); process.exit(1); }
const TTL = 10 * 60 * 1000, MAX_TRIES = 5, COOLDOWN = +process.env.OTP_COOLDOWN_MS >= 0 && process.env.OTP_COOLDOWN_MS !== undefined ? +process.env.OTP_COOLDOWN_MS : 25 * 1000, PER_HOUR = +process.env.OTP_PER_HOUR || 6;
const codes = new Map(), sends = new Map();   // id -> {email, hash, salt, exp, tries}; email -> [timestamps]
const hash = (code, salt) => crypto.createHash('sha256').update(salt + ':' + code).digest('hex');
setInterval(() => { const n = Date.now(); for (const [k, v] of codes) if (v.exp < n) codes.delete(k); for (const [k, v] of sends) { const f = v.filter(t => n - t < 3600e3); f.length ? sends.set(k, f) : sends.delete(k); } }, 60e3).unref();
const SUBJECT = { reg: 'Confirm your email for KinKeep', login: 'Your KinKeep sign-in code', reset: 'Your KinKeep password reset code' };
function send(res, status, obj) { res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': ORIGIN, 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(obj)); }
function body(req) { return new Promise((ok, no) => { let b = ''; req.on('data', c => { b += c; if (b.length > 2048) { req.destroy(); no(new Error('big')); } }); req.on('end', () => { try { ok(JSON.parse(b || '{}')); } catch (e) { no(e); } }); }); }
http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') return send(res, 204, {});
  if (req.method !== 'POST') return send(res, 404, { ok: false, error: 'not_found' });
  let j; try { j = await body(req); } catch (e) { return send(res, 400, { ok: false, error: 'bad_request' }); }
  if (req.url === '/otp/send') {
    const email = String(j.email || '').trim().toLowerCase(), purpose = SUBJECT[j.purpose] ? j.purpose : 'login';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email) || email.length > 120) return send(res, 400, { ok: false, error: 'bad_email' });
    const now = Date.now(), hist = (sends.get(email) || []).filter(t => now - t < 3600e3);
    if (hist.length >= PER_HOUR || (hist.length && now - hist[hist.length - 1] < COOLDOWN)) return send(res, 429, { ok: false, error: 'rate_limited' });
    const code = String(crypto.randomInt(100000, 1000000)), salt = crypto.randomBytes(8).toString('hex'), id = crypto.randomBytes(16).toString('hex');
    try {
      if (transport) await transport.sendMail({ from: FROM, to: email, subject: SUBJECT[purpose], text: 'Your KinKeep code is ' + code + '. It expires in 10 minutes. If you did not ask for it, ignore this email.' });
      else console.log('[DEV] code for ' + email + ' (' + purpose + '): ' + code);
    } catch (e) { console.error('mail failed:', e.message); return send(res, 502, { ok: false, error: 'send_failed' }); }
    hist.push(now); sends.set(email, hist); codes.set(id, { email, salt, hash: hash(code, salt), exp: now + TTL, tries: 0 });
    return send(res, 200, { ok: true, id, expiresIn: TTL / 1000 });
  }
  if (req.url === '/otp/verify') {
    const c = codes.get(String(j.id || '')); if (!c || c.exp < Date.now()) return send(res, 200, { ok: false, error: 'expired' });
    if (c.tries >= MAX_TRIES) return send(res, 200, { ok: false, error: 'locked' });
    c.tries++; const a = Buffer.from(hash(String(j.code || '').replace(/\s/g, ''), c.salt)), b = Buffer.from(c.hash);
    if (a.length === b.length && crypto.timingSafeEqual(a, b)) { codes.delete(String(j.id)); return send(res, 200, { ok: true }); }
    return send(res, 200, { ok: false, error: 'wrong', left: MAX_TRIES - c.tries });
  }
  send(res, 404, { ok: false, error: 'not_found' });
}).listen(PORT, () => console.log('KinKeep email-code service on port ' + PORT + (transport ? ' (sending real email)' : ' (DEV: codes printed here)')));
