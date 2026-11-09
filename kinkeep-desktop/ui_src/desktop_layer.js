  /* ======================================================================================================
     KinKeep Desktop layer. This replaces the browser version's storage, encryption and sign-in code.
     No key, password hash or vault file ever exists in this page: every action is a call to the Python
     engine (kk('method', ...)), which does the encryption, writes the files and enforces family roles.
     ====================================================================================================== */
  var LOCK_MIN = 10, GD = 'Google Drive', PREFIX = 'KinKeep vault', IN_CLAUDE = false;
  var V = { on: false, timer: null, last: '', lastSaved: '', err: '', saving: false, again: false, seq: null };
  var P = null;                       /* {perms, user} from the engine once signed in */
  var ST = { presets: {}, questions: [], account: null };
  var SEC = { stale: true, loading: false, sec: null, sheet: null, members: null };
  var DR = { state: 'idle', busy: false, log: [], files: [], pending: null };
  var G = { step: '', draft: null, otp: null, purpose: '', tick: 0, resendAt: 0, quick: false, login: '', after: null, kept: null };
  var GROUPS_ALL = JSON.parse(JSON.stringify(GROUPS));

  /* ---- the one door to Python: pywebview in the installed app, a token-guarded localhost bridge in tests ---- */
  function kk(name) {
    var args = Array.prototype.slice.call(arguments, 1), fail = { ok: false, error: 'KinKeep could not reach its engine. Please restart the app.' };
    if (window.KK_DEV) {
      return fetch('/api/' + name, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-KK-Token': window.KK_DEV }, body: JSON.stringify(args) })
        .then(function (r) { return r.json(); }).catch(function () { return fail; });
    }
    return new Promise(function (res) {
      if (window.pywebview && window.pywebview.api) return res(window.pywebview.api);
      window.addEventListener('pywebviewready', function () { res(window.pywebview.api); });
    }).then(function (api) { return api[name].apply(api, args); }).catch(function () { return fail; });
  }
  function fileB64(f) { return new Promise(function (res, rej) { var r = new FileReader(); r.onload = function () { res(String(r.result).split(',')[1] || ''); }; r.onerror = function () { rej(new Error('read')); }; r.readAsDataURL(f); }); }

  function drLog(t) { DR.log.push(new Date().toLocaleTimeString('en-US') + '  ' + t); if (DR.log.length > 60) DR.log.shift(); }
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  function cfg() { if (!S.settings || typeof S.settings !== 'object') S.settings = { docStore: '', targets: { file: false, drive: false } }; return S.settings; }
  function emptyState() { return { rate: 85, rateDate: iso(0), view: 'home', assets: [], liabs: [], policies: [], docs: [], ids: [], wills: [], wishes: [], reminders: [], contacts: [], access: [], plan: { medical: '', instructions: '' }, check: {}, settings: { docStore: '', targets: { file: false, drive: false } } }; }
  function stateForSave() { var d = JSON.parse(JSON.stringify(S)); delete d.view; return d; }

  /* ---- who may see and change what (the engine enforces it; this only shapes the screen) ---- */
  function viewPerm(v) { return (!V.on || !P) ? 'rw' : (P.perms.views[v] || ''); }
  function myRole() { return P ? P.user.role : 'Owner'; }
  function isOwner() { return !V.on || myRole() === 'Owner'; }
  function isManager() { return !V.on || myRole() === 'Owner' || myRole() === 'Co-owner'; }
  function firstView() { for (var i = 0; i < NAV.length; i++) if (viewPerm(NAV[i][0])) return NAV[i][0]; return 'home'; }
  function applyPerms() {
    GROUPS = GROUPS_ALL.map(function (g) { return Object.assign({}, g, { items: g.items.filter(function (v) { return viewPerm(v); }) }); }).filter(function (g) { return g.items.length; });
    NAV = []; GROUPS.forEach(function (g) { g.items.forEach(function (v) { NAV.push([v, NAMES[v]]); }); });
  }
  function applyRO() {
    var ro = V.on && P && viewPerm(S.view) === 'r', m = $('#main');
    document.body.classList.toggle('ro', !!ro);
    if (!ro || !m) return;
    m.querySelectorAll('form[data-coll], .row-actions, #rateForm').forEach(function (el) { el.hidden = true; });
    m.querySelectorAll('.qa-input').forEach(function (el) { var p = el.closest('.panel'); if (p) p.hidden = true; });
    m.querySelectorAll('textarea, input[type=text], input[type=number], input[type=date], select').forEach(function (el) { if (!el.closest('#passForm') && !el.closest('[data-allow]')) { el.readOnly = true; if (el.tagName === 'SELECT') el.disabled = true; } });
    m.querySelectorAll('input[type=checkbox][data-act="toggle"]').forEach(function (el) { el.disabled = true; });
    var h = m.querySelector('h1, .head'); var note = '<div class="ro-note" role="note">You can look at this page, but your role cannot change it.</div>';
    if (h) h.insertAdjacentHTML('afterend', note); else m.insertAdjacentHTML('afterbegin', note);
  }
  function guardAct(act) {
    if (!V.on || !P) return true;
    if (['edit', 'del', 'toggle', 'qa-fill', 'qa-mic', 'qa-ex', 'will-up', 'will-share'].indexOf(act) >= 0 && viewPerm(S.view) !== 'rw') { drLog('Your role can view this page but not change it.'); return false; }
    if (act === 'reset') return false;                                        /* the fictional sample is for sample mode only */
    if (act === 'clear') return isOwner() && window.confirm('Erase every record in this vault? Your account, family sign-ins and recovery key stay. A backup copy is kept in the backups folder.');
    return true;
  }
  function guardSubmit(f) {
    if (!V.on || !P || f.id === 'passForm') return true;
    return viewPerm(S.view) === 'rw';
  }

  /* ---- vault status line and saving ---- */
  function vaultLine() {
    if (!V.on) return 'Sample data. Nothing is saved.';
    if (V.err) return V.err;
    return 'Encrypted vault, unlocked' + (V.lastSaved ? '. Saved ' + new Date(V.lastSaved).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '') + '.';
  }
  function updateStatus() { var a = $('#rail-vault'), b = $('#st-last'); if (a) a.textContent = vaultLine(); if (b) b.textContent = vaultLine(); }
  function queueSave() {
    if (!V.on) return;
    var snap = JSON.stringify(stateForSave()); if (snap === V.last) return; V.last = snap;
    clearTimeout(V.timer); V.timer = setTimeout(flushSave, 500);
  }
  async function flushSave() {
    if (!V.on) return; clearTimeout(V.timer);
    if (V.saving) { V.again = true; return; }
    V.saving = true; var r = await kk('save_state', stateForSave(), V.seq); V.saving = false;
    if (!r.ok) {
      V.err = r.error || 'Could not save. Your last saved data is unchanged.';
      if (r.denied || r.stale) { var l = await kk('load_state'); if (l.ok) { var v = S.view; applyPayload(l); S.view = v; render(); drLog(r.stale ? 'The records changed somewhere else, so your screen was refreshed.' : 'Some changes were not allowed for your role and were undone.'); } }
    } else { V.err = ''; if (r.seq != null) V.seq = r.seq; if (r.changed !== false) V.lastSaved = new Date().toISOString(); }
    updateStatus();
    if (V.again) { V.again = false; flushSave(); }
  }
  function applyPayload(r) {
    P = { perms: r.perms, user: r.user }; var keep = S && S.view;
    S = normalize(r.state); V.seq = r.seq; V.on = true; V.err = ''; V.lastSaved = new Date().toISOString(); LOCK_MIN = r.lockMinutes || 10;
    applyPerms(); S.view = viewPerm(keep || 'home') ? (keep || 'home') : firstView(); V.last = JSON.stringify(stateForSave()); SEC.stale = true; E = { coll: null, id: null };
  }

  /* ---- lock, unlock, idle timer ---- */
  var idleT = null;
  function bump() { if (!V.on) return; clearTimeout(idleT); idleT = setTimeout(function () { lockNow(); }, LOCK_MIN * 60000); }
  ['pointerdown', 'keydown', 'touchstart'].forEach(function (ev) { document.addEventListener(ev, bump, { passive: true }); });
  function resetChat() { try { log.innerHTML = ''; history = []; qEl.value = ''; intro(); } catch (e) {} }
  function wipeScreen() {
    V.on = false; P = null; V.last = ''; setShow(false); SEC = { stale: true, loading: false, sec: null, sheet: null, members: null };
    S = emptyState(); S.view = 'home'; E = { coll: null, id: null }; DR.pending = null; DR.log = []; applyPerms(); resetChat(); render();
  }
  async function lockNow() { if (!V.on) return; await flushSave(); clearTimeout(idleT); await kk('lock'); wipeScreen(); gLogin(true); }
  async function signOut() { if (V.on) await flushSave(); clearTimeout(idleT); await kk('signout'); wipeScreen(); gLogin(false); }

  /* ---- gate (full-screen sign-in boxes) helpers ---- */
  function gateOpen(html) { clearInterval(G.tick); var g = $('#gate'); g.innerHTML = html; g.hidden = false; var i = g.querySelector('input:not([disabled]):not([type=checkbox]):not([type=radio]),button'); if (i) setTimeout(function () { try { i.focus(); } catch (e) {} }, 30); }
  function hideGate() { clearInterval(G.tick); $('#gate').hidden = true; $('#gate').innerHTML = ''; }
  function gateMsg(t) { var m = $('#g-msg'); if (m) m.textContent = t; }
  function box2(title, inner) { return '<div class="dialog gate-box" role="dialog" aria-modal="true" aria-labelledby="gTitle"><h2 id="gTitle">' + title + '</h2>' + inner + '<div class="small g-msg" id="g-msg" role="alert"></div></div>'; }
  var fld = function (id, label, type, extra) { return '<div class="fld"><label for="' + id + '">' + label + '</label><input type="' + (type || 'text') + '" id="' + id + '" ' + (extra || '') + '></div>'; };
  var pwToggle = '<label class="opt small"><input type="checkbox" data-g="showpw"><span>Show passwords</span></label>';
  var val = function (id) { return (($('#' + id) || {}).value || '').trim(); };
  function maskEmail(e) { var p = String(e).split('@'); return p.length < 2 ? '***' : p[0].charAt(0) + '***@' + p[1]; }

  /* email provider choice (used at registration and later under Storage and security) */
  function smtpFields(pre, d) {
    d = d || {}; var pr = ST.presets || {}, cur = d.prov || 'gmail';
    var opts = Object.keys(pr).map(function (k) { return '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' + { gmail: 'Gmail', outlook: 'Outlook or Hotmail', yahoo: 'Yahoo', icloud: 'iCloud', custom: 'Other provider' }[k] + '</option>'; }).join('');
    return '<div class="fld"><label for="' + pre + '-prov">Email provider</label><select id="' + pre + '-prov" data-prov="' + pre + '">' + opts + '</select></div>' +
      fld(pre + '-spass', d.hasPass ? 'App password (leave blank to keep the saved one)' : 'App password for that mailbox', 'password', 'autocomplete="off"') +
      '<p class="small muted" id="' + pre + '-note">' + esc((pr[cur] || {}).note || '') + '</p>' +
      '<details><summary class="small">Other provider settings</summary><div class="g-grid">' + fld(pre + '-shost', 'SMTP server', 'text', 'value="' + esc(d.host || '') + '"') + fld(pre + '-sport', 'Port', 'number', 'value="' + esc(d.port || 465) + '"') +
      '<div class="fld"><label for="' + pre + '-ssec">Security</label><select id="' + pre + '-ssec"><option value="ssl"' + (d.security !== 'starttls' ? ' selected' : '') + '>SSL (port 465)</option><option value="starttls"' + (d.security === 'starttls' ? ' selected' : '') + '>STARTTLS (port 587)</option></select></div>' + fld(pre + '-suser', 'Mailbox user name (if not your email)', 'text', 'value="' + esc(d.user || '') + '"') + '</div></details>';
  }
  function smtpFrom(pre, email) {
    var pass = ($('#' + pre + '-spass') || {}).value || '', prov = val(pre + '-prov'), p = (ST.presets || {})[prov] || {};
    var c = { prov: prov, host: prov === 'custom' ? val(pre + '-shost') : p.host, port: prov === 'custom' ? (+val(pre + '-sport') || 465) : p.port, security: prov === 'custom' ? val(pre + '-ssec') : p.security, user: val(pre + '-suser') || email, password: pass, from: email };
    return c;
  }
  document.addEventListener('change', function (e) {
    var t = e.target; if (!t || !t.dataset || !t.dataset.prov) return; var pre = t.dataset.prov, p = (ST.presets || {})[t.value] || {};
    var n = $('#' + pre + '-note'); if (n) n.textContent = p.note || ''; if (p.host) { var h = $('#' + pre + '-shost'), o = $('#' + pre + '-sport'), s2 = $('#' + pre + '-ssec'); if (h) h.value = p.host; if (o) o.value = p.port; if (s2) s2.value = p.security; }
  });

  /* ---- 1. registration ---- */
  function gRegister() {
    G.step = 'reg'; var d = G.draft || {};
    var qsel = function (i) { return '<div class="fld"><label for="r-q' + i + '">Question ' + (i + 1) + '</label><select id="r-q' + i + '">' + ST.questions.map(function (q, k) { return '<option' + ((d.qi ? d.qi[i] : i) === k ? ' selected' : '') + ' value="' + k + '">' + esc(q) + '</option>'; }).join('') + '</select></div>' + fld('r-a' + i, 'Your answer', 'text', 'autocomplete="off" value="' + esc((d.ans || [])[i] || '') + '"'); };
    gateOpen(box2('Create your KinKeep account',
      '<p class="small muted">Your records stay on this computer, encrypted with your password. Every sign-in also needs a code sent to your email.</p>' +
      '<div class="g-grid">' + fld('r-first', 'First name', 'text', 'autocomplete="given-name" value="' + esc(d.first || '') + '"') + fld('r-last', 'Last name', 'text', 'autocomplete="family-name" value="' + esc(d.last || '') + '"') + '</div>' +
      '<div class="g-grid">' + fld('r-email', 'Email address', 'email', 'autocomplete="email" value="' + esc(d.email || '') + '"') + fld('r-dob', 'Date of birth', 'date', 'max="' + iso(0) + '" value="' + esc(d.dob || '') + '"') + '</div>' +
      '<h3>Your login</h3><div class="g-grid">' + fld('r-user', 'Choose a login name', 'text', 'autocomplete="username" value="' + esc(d.user || '') + '"') + fld('r-pass', 'Master password (10+ characters)', 'password', 'autocomplete="new-password"') + '</div>' +
      '<div class="g-grid">' + fld('r-pass2', 'Type the password again', 'password', 'autocomplete="new-password"') + '<div></div></div>' + pwToggle +
      '<p class="small muted">This password locks your vault and your backup spreadsheet. If you lose it, nobody can recover the spreadsheet, so choose something you will remember and keep a note of it in a safe place.</p>' +
      '<h3>Three favorite questions</h3><p class="small muted">If you forget your password, these help prove it is you. They are checked together with an emailed code and your recovery key, never on their own.</p>' + qsel(0) + qsel(1) + qsel(2) +
      '<h3>Email for sign-in codes</h3><p class="small muted">KinKeep sends the 6-digit code through your own mailbox, so nothing passes through a KinKeep server. Use an app password, not your normal email password.</p>' + smtpFields('r', d.smtp) +
      '<label class="opt"><input type="checkbox" id="r-demo"><span>Skip for now (demo mode). The code is then shown on screen, so it is <b>not</b> a real second factor. You can set up email later.</span></label>' +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="reg-next" data-enter>Continue</button></div>' +
      '<p class="small muted"><button class="link-btn" type="button" data-g="explore">Look around with fictional sample data (nothing is saved)</button></p>'));
  }
  async function gRegNext() {
    var d = { first: val('r-first'), last: val('r-last'), email: val('r-email'), dob: val('r-dob'), user: val('r-user'), qi: [0, 1, 2].map(function (i) { return +val('r-q' + i); }), ans: [0, 1, 2].map(function (i) { return val('r-a' + i); }) };
    var pass = ($('#r-pass') || {}).value || '', pass2 = ($('#r-pass2') || {}).value || '', demo = !!($('#r-demo') || {}).checked, sm = smtpFrom('r', d.email);
    d.smtp = { prov: sm.prov, host: sm.host, port: sm.port, security: sm.security, user: sm.user }; G.draft = d;
    if (!demo && !sm.password) return gateMsg('Enter the app password for your mailbox, or tick "Skip for now (demo mode)".');
    gateMsg('Checking…');
    var r = await kk('register_start', { first: d.first, last: d.last, email: d.email, dob: d.dob, login: d.user, password: pass, password2: pass2,
      questions: d.qi.map(function (q, i) { return { qi: q, answer: d.ans[i] }; }), smtp: demo ? {} : sm, demo: demo });
    if (!r.ok) return gateMsg(r.error);
    G.draft.smtp.hasPass = false; gVerify('reg', r.otp);
  }

  /* ---- 2. email code screen (registration, sign-in, reset) ---- */
  function gVerify(purpose, info) {
    G.step = 'otp'; G.purpose = purpose; G.otp = info;
    var why = { reg: 'Confirm your email', login: 'Check your email', reset: 'Check your email' }[purpose];
    gateOpen(box2(why, '<div id="g-otp-info" class="small muted"></div>' +
      '<div class="fld"><label for="g-otp">6-digit code</label><input type="text" id="g-otp" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code"></div>' +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="otp-go" data-enter>Verify</button><button class="btn" type="button" data-g="otp-resend" id="g-resend" disabled>Resend code</button></div>' +
      '<p class="small muted">' + (purpose === 'login' ? '<button class="link-btn" type="button" data-g="rk-login">No email right now? Use my recovery key instead</button> &nbsp; ' : '') + '<button class="link-btn" type="button" data-g="cancel">Cancel</button></p>'));
    showOtp(info);
  }
  function showOtp(info) {
    var el = $('#g-otp-info'); if (!el) return;
    el.innerHTML = info.demo ? '<div class="demo-box"><b>Demo mode.</b> Email is not set up, so your code is shown here: <span class="demo-code">' + esc(info.demo_code) + '</span><br>Because anyone at the screen can read it, this is <b>not</b> a real second factor. Set up email under Storage and security.</div>' :
      'We sent a 6-digit code to <b>' + esc(info.masked) + '</b>. It expires in 10 minutes.';
    startResend(30);
  }
  function startResend(sec) {
    G.resendAt = Date.now() + sec * 1000; clearInterval(G.tick);
    G.tick = setInterval(function () { var b = $('#g-resend'); if (!b) { clearInterval(G.tick); return; } var s = Math.ceil((G.resendAt - Date.now()) / 1000); if (s > 0) { b.disabled = true; b.textContent = 'Resend code (' + s + 's)'; } else { b.disabled = false; b.textContent = 'Resend code'; clearInterval(G.tick); } }, 500);
  }
  async function resendCode() {
    var el = $('#g-otp-info'); if (el) el.textContent = 'Sending a new code…';
    var r = await kk('otp_resend'); if (r.ok) { G.otp = r.otp; showOtp(r.otp); } else { if (el) el.textContent = r.error; startResend(30); }
  }
  async function gOtpGo() {
    var code = val('g-otp'); if (!/^\d{6}$/.test(code)) return gateMsg('Enter the 6-digit code.');
    gateMsg('Checking…'); var r = await kk('otp_verify', code);
    if (!r.ok) { await sleep(400); return gateMsg(r.error); }
    if (G.purpose === 'reg') return gStorage(); if (G.purpose === 'reset') return gNewPass();
    return finishPayload(r);
  }
  async function gRkLogin() {
    gateOpen(box2('Use your recovery key', '<p class="small muted">Instead of the emailed code you can type the recovery key printed when you created this account. Only the Owner can do this.</p>' +
      fld('rk-in', 'Recovery key', 'text', 'autocomplete="off" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"') + '<div class="form-actions"><button class="btn primary" type="button" data-g="rk-login-go" data-enter>Sign in</button><button class="btn" type="button" data-g="cancel">Back</button></div>'));
  }
  async function gRkLoginGo() { gateMsg('Checking…'); var r = await kk('login_with_recovery_key', G.login, val('rk-in')); if (!r.ok) { await sleep(400); return gateMsg(r.error); } finishPayload(r); }

  /* ---- 3. storage choices, then create the account and vault ---- */
  function gStorage() {
    G.step = 'store';
    gateOpen(box2('Almost there', '<p class="small muted">Your records are encrypted with your password before they are saved. KinKeep keeps two files in <b>' + esc(ST.dataDir) + '</b>: the encrypted vault and a password-protected spreadsheet copy you can open without KinKeep.</p>' +
      '<h3>Where do you keep document files, such as scans and PDFs?</h3><div class="fld"><label for="g-docs">Document files</label><select id="g-docs"><option value="drive">In Google Drive</option><option value="computer">On this computer</option><option value="other">Somewhere else</option></select></div>' +
      '<h3>Start with</h3><label class="opt"><input type="radio" name="g-start" value="empty" checked><span>An empty account</span></label><label class="opt"><input type="radio" name="g-start" value="sample"><span>The fictional sample family, so I can try things</span></label>' +
      '<label class="opt"><input type="radio" name="g-start" value="backup"><span>A backup I already have (KinKeep desktop vault, spreadsheet, or a backup from the browser version)</span></label>' +
      '<div id="g-bk" hidden><div class="fld"><label for="g-bkfile">Backup file</label><input type="file" id="g-bkfile" accept=".json,.kinkeep,.xlsx"></div>' + fld('g-bkpass', 'Password the backup was saved with', 'password', 'autocomplete="off"') + '<p class="small muted">Family sign-ins are never restored from a backup. People keep their roles but need your approval again.</p></div>' +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="create" data-enter>Create my account</button></div>'));
  }
  document.addEventListener('change', function (e) { if (e.target && e.target.name === 'g-start') { var b = $('#g-bk'); if (b) b.hidden = e.target.value !== 'backup'; } });
  async function gCreate() {
    var st = (document.querySelector('input[name="g-start"]:checked') || {}).value || 'empty', o = { start: st, docStore: val('g-docs') };
    if (st === 'sample') { var sm = seed(); delete sm.view; o.sample = sm; }
    if (st === 'backup') {
      var f = ($('#g-bkfile') || {}).files && $('#g-bkfile').files[0]; if (!f) return gateMsg('Choose the backup file.');
      try { o.backup_b64 = await fileB64(f); } catch (e) { return gateMsg('Could not read that file.'); } o.backup_password = ($('#g-bkpass') || {}).value || '';
    }
    gateMsg('Creating your encrypted vault…'); var r = await kk('register_finish', o);
    if (!r.ok) return gateMsg(r.error);
    G.draft = null; gRecovery(r);
  }
  function gRecovery(r) {
    G.kept = r;
    gateOpen(box2('Save your recovery key', '<p>' + (r.restoredFrom ? 'Your backup was restored (' + esc(r.restoredFrom) + '). ' : '') + 'This key is the only way to get your records back if you forget your password. <b>KinKeep cannot show it again.</b> Write it down and keep it with your important papers.</p>' +
      '<div class="rk" id="g-rk" tabindex="0">' + esc(r.recoveryKey) + '</div>' +
      '<div class="form-actions"><button class="btn" type="button" data-g="rk-copy">Copy</button><button class="btn" type="button" data-g="rk-save">Save a recovery sheet (.txt)</button></div>' +
      '<label class="opt"><input type="checkbox" id="g-rk-ack"><span>I have saved my recovery key somewhere safe.</span></label>' +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="rk-done" data-enter>Continue</button></div>'));
  }
  async function recoveryAct(a) {
    var r = G.kept; if (!r) return;
    if (a === 'rk-copy') { try { await navigator.clipboard.writeText(r.recoveryKey); gateMsg('Copied. Paste it somewhere safe, then clear your clipboard.'); } catch (e) { gateMsg('Could not copy. Select the key and copy it by hand.'); } }
    else if (a === 'rk-save') { var s = await kk('save_recovery_sheet', r.recoveryKey); gateMsg(s.ok ? (s.path ? 'Saved to ' + s.path : 'Save cancelled.') : s.error); }
    else if (a === 'rk-done') { if (!($('#g-rk-ack') || {}).checked) return gateMsg('Tick the box to confirm you saved the key.'); var k = G.kept; G.kept = null; if (G.after === 'drive') { G.after = null; hideGate(); render(); } else finishPayload(k); }
  }
  function finishPayload(r) {
    applyPayload(r); hideGate(); resetChat(); S.view = viewPerm('home') ? 'home' : firstView(); go(S.view); bump(); updateStatus();
    if (r.sync && r.sync.state && r.sync.state !== 'in_sync' && r.sync.why) drLog(r.sync.why);
    if (r.sync && (r.sync.state === 'external_edits' || r.sync.state === 'xlsx_newer')) go('drive');
  }

  /* ---- 4. sign in: password first, then the emailed code (or the password alone after an idle lock) ---- */
  function gLogin(quick) {
    G.step = 'login'; G.quick = !!quick; var q = G.quick, a = ST.account;
    gateOpen(box2(q ? 'Welcome back' + (a ? ', ' + esc(a.first) : '') : 'Sign in to KinKeep',
      '<p class="small muted">' + (q ? 'KinKeep locked itself. Enter your password to continue.' : 'Enter your login name and password. We then email you a 6-digit code to finish signing in.') + '</p>' +
      (q ? '' : fld('g-user', 'Login name or email', 'text', 'autocomplete="username"' + (a ? ' value="' + esc(G.login || a.login) + '"' : ''))) + fld('g-pass', 'Password', 'password', 'autocomplete="current-password"') + pwToggle +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="login-go" data-enter>' + (q ? 'Unlock' : 'Continue') + '</button></div>' +
      '<p class="small muted"><button class="link-btn" type="button" data-g="forgot">Forgot your password?</button>' + (q ? ' &nbsp; <button class="link-btn" type="button" data-g="signout">Sign out</button>' : '') + '</p>'));
  }
  async function gLoginGo() {
    var pass = ($('#g-pass') || {}).value || '', u = val('g-user');
    if (!pass || (!G.quick && !u)) return gateMsg(G.quick ? 'Enter your password.' : 'Enter your login name and password.');
    gateMsg('Checking…'); var r;
    if (G.quick) { r = await kk('unlock', pass); if (!r.ok) { await sleep(300); return gateMsg(r.error); } return finishPayload(r); }
    r = await kk('login', u, pass); if (!r.ok) { await sleep(300); return gateMsg(r.error); }
    G.login = u; gVerify('login', r.otp);
  }

  /* ---- 5. forgot password: three answers AND an emailed code, then (best) the recovery key ---- */
  async function gForgot() {
    var r = await kk('forgot_start'); if (!r.ok) { gLogin(false); return gateMsg(r.error); }
    G.step = 'forgot';
    gateOpen(box2('Reset your password', '<p class="small muted">Answer your three questions. We then email a code to ' + esc(r.emailMasked) + '. You need both, and your recovery key to keep your records.</p>' +
      r.questions.map(function (q, i) { return fld('f-a' + i, esc(q), 'text', 'autocomplete="off"'); }).join('') +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="forgot-go" data-enter>Check my answers</button><button class="btn" type="button" data-g="cancel">Back</button></div>'));
  }
  async function gForgotGo() {
    gateMsg('Checking…'); var r = await kk('forgot_answers', [0, 1, 2].map(function (i) { return ($('#f-a' + i) || {}).value || ''; }));
    if (!r.ok) { await sleep(500); return gateMsg(r.error); } gVerify('reset', r.otp);
  }
  function gNewPass() {
    G.step = 'newpass';
    gateOpen(box2('Choose a new password', '<p class="small muted">You are verified. To keep your records, enter your recovery key. Without it, your old vault is set aside as an encrypted backup and you start with an empty one.</p>' +
      fld('n-pass', 'New password (10+ characters)', 'password', 'autocomplete="new-password"') + fld('n-pass2', 'Type it again', 'password', 'autocomplete="new-password"') + pwToggle +
      fld('n-rk', 'Recovery key (recommended)', 'text', 'autocomplete="off" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"') +
      '<label class="opt"><input type="checkbox" id="n-ack"><span>I understand that without the recovery key I start with an empty vault.</span></label>' +
      '<div class="form-actions"><button class="btn primary" type="button" data-g="newpass-go" data-enter>Set password and enter</button><button class="btn" type="button" data-g="cancel">Cancel</button></div>'));
  }
  async function gNewPassGo() {
    var p1 = ($('#n-pass') || {}).value || '', p2 = ($('#n-pass2') || {}).value || '', rk = val('n-rk');
    if (p1.length < 10) return gateMsg('Your password needs at least 10 characters.'); if (p1 !== p2) return gateMsg('The two passwords do not match.');
    if (!rk && !($('#n-ack') || {}).checked) return gateMsg('Enter your recovery key, or tick the box to confirm you understand.');
    gateMsg('Saving…'); var r = await kk('reset_password', p1, rk); if (!r.ok) return gateMsg(r.error);
    if (r.recoveryKey) { gRecovery(r); drLog('Your old vault was archived to ' + r.archivedTo); } else finishPayload(r);
  }

  /* ---- gate events ---- */
  $('#gate').addEventListener('click', function (e) {
    var b = e.target.closest('[data-g]'); if (!b || b.type === 'checkbox') return; var a = b.dataset.g;
    if (a === 'reg-next') gRegNext(); else if (a === 'otp-go') gOtpGo(); else if (a === 'create') gCreate();
    else if (a === 'otp-resend') { if (Date.now() >= G.resendAt) resendCode(); }
    else if (a === 'login-go') gLoginGo(); else if (a === 'forgot') gForgot(); else if (a === 'forgot-go') gForgotGo();
    else if (a === 'newpass-go') gNewPassGo(); else if (a === 'rk-login') gRkLogin(); else if (a === 'rk-login-go') gRkLoginGo();
    else if (a === 'rk-copy' || a === 'rk-save' || a === 'rk-done') recoveryAct(a);
    else if (a === 'explore') { V.on = false; hideGate(); S = seed(); S.view = 'home'; applyPerms(); render(); }
    else if (a === 'signout') { signOut(); }
    else if (a === 'cancel') { kk('signout'); ST.account ? gLogin(false) : gRegister(); }
  });
  $('#gate').addEventListener('change', function (e) { if (e.target.dataset && e.target.dataset.g === 'showpw') document.querySelectorAll('#gate input[type=password], #gate input[data-pw]').forEach(function (i) { i.type = e.target.checked ? 'text' : 'password'; i.dataset.pw = '1'; }); });
  $('#gate').addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || e.target.tagName === 'BUTTON' || e.target.tagName === 'SELECT' || e.target.type === 'checkbox' || e.target.type === 'radio') return; e.preventDefault();
    var p = $('#gate [data-enter]'); if (p) p.click();
  });

  /* ---- storage and security screen: engine-backed panels ---- */
  async function refreshSec() {
    if (SEC.loading || !V.on) return; SEC.loading = true; SEC.stale = false;
    var a = await kk('security_status'), b = await kk('spreadsheet_info'), m = isManager() ? await kk('members') : { ok: true, members: [] };
    SEC.sec = a.ok ? a : null; SEC.sheet = b.ok ? b : null; SEC.members = m.ok ? m.members : []; SEC.loading = false;
    if (S.view === 'drive') render();
  }
  async function changePass() {
    var cur = ($('#pf-cur') || {}).value || '', n1 = ($('#pf-new') || {}).value || '', n2 = ($('#pf-new2') || {}).value || '';
    if (n1 !== n2) { drLog('The new passwords do not match.'); render(); return; }
    var r = await kk('change_password', cur, n1); drLog(r.ok ? r.message : r.error); SEC.stale = true; render();
  }
  function passForm() {
    return '<form class="entry" id="passForm" autocomplete="off"><div class="fld"><label for="pf-cur">Current password</label><input type="password" id="pf-cur" autocomplete="current-password"></div><div class="fld"><label for="pf-new">New password (10+ characters)</label><input type="password" id="pf-new" autocomplete="new-password"></div><div class="fld"><label for="pf-new2">Repeat the new password</label><input type="password" id="pf-new2" autocomplete="new-password"></div><div class="fld"><button class="btn" type="submit">Change password</button></div></form>';
  }
  function pendingPanel() {
    var p = DR.pending; if (!p) return '';
    if (!p.counts) return panel('Open this backup', '<p><b>' + esc(p.name) + '</b></p><p class="small muted" style="margin:6px 0 12px">Enter the password this backup was saved with. For a KinKeep vault backup that is your master password at the time, or its recovery key.</p><div class="entry"><div class="fld"><label for="st-bpass">Password for this backup</label><input type="password" id="st-bpass" autocomplete="off"></div><div class="fld"><button class="btn primary" type="button" data-act="st-decrypt">Open backup</button> <button class="btn" type="button" data-act="drive-cancel">Cancel</button></div></div>');
    var c = p.counts;
    return panel('Replace your data with this backup?', '<p><b>' + esc(p.name) + '</b> <span class="muted">(' + esc(p.kind) + (p.savedAt ? ', saved ' + esc(fdt(p.savedAt)) : '') + ')</span></p><p class="small muted" style="margin:6px 0 12px">Contains ' + c.assets + ' assets, ' + c.liabs + ' liabilities, ' + c.policies + ' policies, ' + c.docs + ' documents, ' + c.ids + ' identity records, ' + c.wills + ' will or trust records, ' + c.wishes + ' wish notes, ' + c.reminders + ' reminders, ' + c.contacts + ' contacts and ' + c.access + ' family members. Your current data will be replaced (a copy is kept in backups). Family members keep their roles, but every family sign-in is removed and each person needs your approval again.</p><div class="form-actions"><button class="btn primary" type="button" data-act="drive-apply">Replace my data</button><button class="btn" type="button" data-act="drive-cancel">Cancel</button></div>');
  }
  function railTools() {
    if (!V.on) return '<button class="btn sm" data-act="reset" type="button">Reset sample data</button>';
    return isOwner() ? '<button class="btn sm danger" data-act="clear" type="button">Clear everything</button>' : '';
  }
  function memberRows() {
    var logins = {}; (SEC.members || []).forEach(function (m) { logins[m.access_id] = m; });
    var rows = (S.access || []).filter(function (r) { return r.role !== 'Owner'; });
    if (!rows.length) return '<p class="small muted">Add the people in your family under Continuity first (name and role). Then give each one a sign-in here.</p>';
    return '<ul class="files">' + rows.map(function (r) {
      var m = logins[r.id], forbid = myRole() === 'Co-owner' && (r.role === 'Owner' || r.role === 'Co-owner');
      var act = forbid ? '<span class="small muted">Only the Owner can manage this role.</span>' : m ?
        '<div class="small muted">Signs in as <b>' + esc(m.login) + '</b> (' + esc(maskEmail(m.email)) + ')</div><button class="btn sm" type="button" data-act="st-mem-del" data-id="' + esc(r.id) + '">Remove sign-in</button>' :
        '<details><summary class="small">Give a sign-in</summary><div class="entry" style="margin-top:8px"><div class="fld"><label for="mf-l-' + esc(r.id) + '">Login name</label><input type="text" id="mf-l-' + esc(r.id) + '" autocomplete="off"></div><div class="fld"><label for="mf-e-' + esc(r.id) + '">Their email (codes go here)</label><input type="email" id="mf-e-' + esc(r.id) + '" autocomplete="off"></div><div class="fld"><label for="mf-p-' + esc(r.id) + '">Starting password (10+ characters)</label><input type="password" id="mf-p-' + esc(r.id) + '" autocomplete="new-password"></div><div class="fld"><button class="btn primary" type="button" data-act="st-mem-add" data-id="' + esc(r.id) + '">Create sign-in</button></div></div></details>';
      return '<li><div><div class="t">' + esc(r.name) + ' <span class="chip">' + esc(r.role) + '</span> <span class="chip' + (r.status === 'Active' ? ' ok' : ' warn') + '">' + esc(r.status) + '</span></div></div><div>' + act + '</div></li>';
    }).join('') + '</ul>';
  }
  function vDrive() {
    if (V.on && SEC.stale) refreshSec();
    var dis = DR.busy ? ' disabled' : '', sec = SEC.sec || {}, sh = SEC.sheet || {}, a = ST.account || {}, out = BANNER + head('Storage and security', V.on ? 'Everything is locked with your own password before it is saved. Nothing leaves this computer unless you choose it.' : 'Sample mode.');
    if (!V.on) return out + panel('Sample mode', '<p>You are looking at fictional sample data. Nothing you enter is saved.</p><div class="form-actions" style="margin-top:12px"><button class="btn primary" type="button" data-act="st-signout">Go to sign in</button></div>', '<span class="chip warn">Not saved</span>');
    var role = myRole(), who = P.user;
    out += panel('You', '<p><b>' + esc(who.name) + '</b> &middot; ' + esc(role) + ' &middot; login <b>' + esc(who.login) + '</b></p><p class="small muted" id="st-last" style="margin-top:6px">' + esc(vaultLine()) + '</p><div class="form-actions" style="margin-top:12px"><button class="btn" type="button" data-act="st-lock"' + dis + '>Lock now</button> <button class="btn" type="button" data-act="st-signout"' + dis + '>Sign out</button></div><p class="small muted" style="margin-top:8px">KinKeep locks itself after ' + LOCK_MIN + ' minutes without activity.</p>', '<span class="chip ok">Encrypted</span>');
    var st = (P.sync || {}), alert = '';
    var sync = SEC.sheet && SEC.sheet.sync;
    if (isOwner() && (sync === 'external_edits' || sync === 'xlsx_newer' || (SEC.sec && SEC.sec.xlsxStale))) {
      alert = panel('The spreadsheet was changed outside KinKeep', '<p class="small muted" style="margin-bottom:10px">The spreadsheet copy does not match your vault. Nothing was overwritten. Choose which one is right. Importing never grants anyone new access: people added in the spreadsheet need your approval, and nobody can be made Owner that way.</p><div class="form-actions"><button class="btn primary" type="button" data-act="st-sync-import"' + dis + '>Use the spreadsheet\'s changes</button><button class="btn" type="button" data-act="st-sync-keep"' + dis + '>Keep my KinKeep data</button></div>', '<span class="chip warn">Needs a choice</span>');
    }
    out += alert + panel('Change my password', passForm() + '<p class="small muted" style="margin-top:6px">Older backups still need the password they were saved with.</p>');
    if (isOwner()) {
      out += panel('Recovery key', '<p class="small muted" style="margin-bottom:10px">The recovery key lets you reset a forgotten password without losing your records. Make a new one if the old one was lost or seen by someone else. The old key stops working.</p><div class="entry"><div class="fld"><label for="rk-pw">Your password</label><input type="password" id="rk-pw" autocomplete="current-password"></div><div class="fld"><button class="btn" type="button" data-act="st-rk"' + dis + '>Make a new recovery key</button></div></div>');
      out += panel('Spreadsheet copy (open it without KinKeep)', '<p class="small muted" style="margin-bottom:10px">After every change KinKeep also writes <b>kinkeep.data.xlsx</b>, one sheet per module, encrypted with your master password. Microsoft Excel, LibreOffice and similar programs ask for that password and open it, even if KinKeep stops working.</p><p style="margin-bottom:10px"><b>' + esc(sh.path || '') + '</b><br><span class="small muted">' + (sh.exists ? 'Up to date with your vault' + (sh.sync === 'in_sync' || !sh.sync ? '' : ' (' + esc(sh.sync) + ')') : 'Not written yet') + '. Encryption: ' + esc(sec.xlsx || '') + '.</span></p><div class="form-actions"><button class="btn" type="button" data-act="st-folder"' + dis + '>Open the data folder</button> <button class="btn" type="button" data-act="st-mode"' + dis + '>' + (sh.mode === 'standard' ? 'Switch to stronger encryption (AES-256)' : 'Use older-compatible encryption (AES-128)') + '</button></div><p class="small muted" style="margin-top:8px">The older mode opens in very old Excel versions but is weaker. Keep the default unless a program cannot open the file.</p>', '<span class="chip ok">Encrypted</span>');
    }
    if (isManager()) {
      var win = sec.emergencyUntil ? new Date(sec.emergencyUntil) : null, live = win && win > new Date();
      out += panel('Family sign-ins', '<p class="small muted" style="margin-bottom:10px">A sign-in gives a person their own login and password. What they can see and change depends on their role. Everyone also needs an emailed code.</p>' + memberRows(), '<span class="chip">' + (SEC.members || []).length + ' sign-in(s)</span>');
    }
    if (isOwner()) {
      var win2 = sec.emergencyUntil ? new Date(sec.emergencyUntil) : null, live2 = win2 && win2 > new Date();
      out += panel('Emergency access', '<p class="small muted" style="margin-bottom:10px">People with the Emergency Contact role can only sign in while you have allowed it. They then see the emergency essentials only (contacts, health insurance, the continuity plan) and cannot change anything.</p><p style="margin-bottom:10px"><b>' + (live2 ? 'Allowed until ' + esc(win2.toLocaleString()) : 'Not allowed right now') + '</b></p><div class="form-actions"><select id="em-h"><option value="2">for 2 hours</option><option value="24" selected>for 24 hours</option><option value="72">for 3 days</option><option value="168">for 7 days</option></select> <button class="btn primary" type="button" data-act="st-em-on"' + dis + '>Allow emergency access</button> <button class="btn" type="button" data-act="st-em-off"' + dis + '>Stop emergency access</button></div>', live2 ? '<span class="chip warn">Open</span>' : '<span class="chip ok">Closed</span>');
      var mail = sec.secondFactor === 'email';
      out += panel('Email for sign-in codes', '<p class="small muted" style="margin-bottom:10px">' + (mail ? 'Real email codes are on. They are sent from your own mailbox.' : '<b>Demo mode:</b> codes are shown on screen, so they are not a real second factor. Set up your mailbox to turn real codes on.') + ' The mailbox password is stored inside your encrypted vault' + '.</p><div class="entry">' + smtpFields('sm', { prov: 'gmail', hasPass: mail }) + '<div class="fld"><button class="btn primary" type="button" data-act="st-smtp"' + dis + '>Save email settings</button> <button class="btn" type="button" data-act="st-smtp-test"' + dis + '>Send a test email</button></div></div>', mail ? '<span class="chip ok">Email</span>' : '<span class="chip warn">Demo</span>');
      var mir = (sec.mirrors || []);
      out += panel('Extra encrypted copies (Google Drive, OneDrive, USB)', '<p class="small muted" style="margin-bottom:10px">Choose a folder, such as one inside Google Drive for desktop, OneDrive or on a USB drive. After every change KinKeep copies the encrypted vault and the password-protected spreadsheet there. Those services only ever hold scrambled data.</p>' + (mir.length ? '<ul class="files">' + mir.map(function (f, i) { return '<li><div class="t">' + esc(f) + '</div><button class="btn sm" type="button" data-act="st-mir-del" data-i="' + i + '">Stop</button></li>'; }).join('') + '</ul>' : '<p class="small muted">No extra folders yet.</p>') + '<div class="form-actions" style="margin-top:10px"><button class="btn primary" type="button" data-act="st-mir-add"' + dis + '>Add a folder</button></div>', '<span class="chip' + (mir.length ? ' ok' : '') + '">' + (mir.length ? 'On' : 'Off') + '</span>');
    }
    if (isManager()) {
      out += panel('Backup copies', '<div class="form-actions" style="margin-bottom:12px"><button class="btn primary" type="button" data-act="st-export"' + dis + '>Save an encrypted vault backup (.json)</button>' + (isOwner() ? ' <button class="btn" type="button" data-act="st-export-x"' + dis + '>Save a spreadsheet backup (.xlsx)</button>' : '') + '</div>' +
        (isOwner() ? '<div class="fld" style="max-width:460px"><label for="st-file">Restore from a backup (vault, spreadsheet, or browser-version backup)</label><input type="file" id="st-file" accept=".json,.kinkeep,.xlsx"></div>' : '') +
        '<p class="small muted" style="margin-top:8px">Backups are always encrypted. A vault backup opens with your master password (or recovery key). A spreadsheet backup opens with your master password in Excel or LibreOffice. To restore on a new computer, choose "A backup I already have" when creating the account. Backups work the same on Windows and Mac.</p>');
    }
    if (viewPerm('drive') === 'rw' || isOwner()) out += panel('Where your document files are kept', docPrefHtml());
    if (a.login && isOwner()) out += panel('Your account', '<p><b>' + esc(a.first || '') + '</b> &middot; login name <b>' + esc(a.login) + '</b></p><p class="small muted" style="margin-top:6px">Codes are sent to ' + esc(a.emailMasked || '') + '. Your name, email, date of birth, login name and the text of your three questions are stored on this computer without encryption so the sign-in screen can use them. Answers are stored only as salted hashes, and your password is never stored. Data folder: ' + esc(ST.dataDir) + '</p>');
    out += panel('Good to know', '<ul class="plain small"><li>Reminders appear inside the app only. There are no email or text alerts for them yet.</li><li>KinKeep does not connect to banks, so amounts are what you type in.</li><li>The advisor answers from your records on this computer. It is not a substitute for emergency services, a lawyer, doctor, tax or financial professional.</li><li>The spreadsheet is opened with your master password, so anyone who has the password and the file can read it. Roles protect you inside KinKeep, not outside it. Choose a long password.</li></ul>');
    return out + pendingPanel() + panel('Activity', '<div class="logbox" role="log">' + (DR.log.length ? esc(DR.log.join('\n')) : 'Nothing yet.') + '</div>');
  }
  async function pickBackup(f) {
    try { DR.pending = { name: f.name, b64: await fileB64(f), counts: null }; drLog('Opened "' + f.name + '". Enter its password below.'); } catch (e) { drLog('Could not read that file.'); }
    render();
  }
  async function storageAct(act, b) {
    if (act === 'drive-cancel') { DR.pending = null; await kk('backup_cancel'); render(); return; }
    if (DR.busy) return; DR.busy = true; var again = true;
    try {
      if (act === 'st-lock') { DR.busy = false; await lockNow(); return; }
      if (act === 'st-signout') { DR.busy = false; await signOut(); return; }
      if (act === 'st-folder') { await kk('open_data_folder'); drLog('Opened the data folder.'); }
      else if (act === 'st-mode') { var m = await kk('set_xlsx_mode', (SEC.sheet && SEC.sheet.mode === 'standard') ? 'agile' : 'standard'); drLog(m.ok ? 'Spreadsheet encryption is now ' + (m.mode === 'agile' ? 'AES-256' : 'AES-128 (compatibility)') + '.' : m.error); SEC.stale = true; }
      else if (act === 'st-sync-import' || act === 'st-sync-keep') {
        var r = await kk('sync_resolve', act === 'st-sync-import' ? 'import' : 'keep'); if (r.ok) { var v = S.view; applyPayload(r); S.view = v; drLog(act === 'st-sync-import' ? 'The spreadsheet\'s changes were imported. New people need your approval.' : 'Kept your KinKeep data; the spreadsheet was rewritten.'); } else drLog(r.error);
      }
      else if (act === 'st-rk') { var k = await kk('rotate_recovery_key', ($('#rk-pw') || {}).value || ''); if (k.ok) { DR.busy = false; G.after = 'drive'; gRecovery({ recoveryKey: k.recoveryKey }); return; } drLog(k.error); }
      else if (act === 'st-export' || act === 'st-export-x') { var x = await kk('export_backup', act === 'st-export' ? 'vault' : 'xlsx'); drLog(x.ok ? (x.path ? 'Saved ' + x.path : 'Save cancelled.') : x.error); }
      else if (act === 'st-decrypt') {
        var p = DR.pending, pw = ($('#st-bpass') || {}).value || ''; var i = await kk('backup_inspect', p.b64, pw, p.name);
        if (i.ok) { p.counts = i.counts; p.kind = i.kind === 'vault' ? 'KinKeep vault backup' : i.kind === 'spreadsheet' ? 'KinKeep spreadsheet' : 'backup from the browser version'; p.savedAt = i.savedAt; drLog('Backup opened. Review it below.'); } else drLog(i.error);
      }
      else if (act === 'drive-apply') { var ap = await kk('backup_apply'); if (ap.ok) { applyPayload(ap); drLog('Restored "' + DR.pending.name + '". Family sign-ins were removed; people need your approval again.'); DR.pending = null; } else drLog(ap.error); }
      else if (act === 'st-mem-add') { var id = b.dataset.id, ad = await kk('member_add', id, val('mf-l-' + id), val('mf-e-' + id), ($('#mf-p-' + id) || {}).value || ''); if (ad.ok) { var v2 = S.view; applyPayload(ad); S.view = v2; drLog('Sign-in created. Give them their login name and password in person.'); } else drLog(ad.error); }
      else if (act === 'st-mem-del') { var rm = await kk('member_remove', b.dataset.id); if (rm.ok) { var v3 = S.view; applyPayload(rm); S.view = v3; drLog('Sign-in removed.'); } else drLog(rm.error); }
      else if (act === 'st-em-on') { var em = await kk('emergency_grant', +(($('#em-h') || {}).value || 24)); drLog(em.ok ? 'Emergency access is allowed until ' + new Date(em.until).toLocaleString() + '.' : em.error); SEC.stale = true; }
      else if (act === 'st-em-off') { var eo = await kk('emergency_revoke'); drLog(eo.ok ? 'Emergency access stopped.' : eo.error); SEC.stale = true; }
      else if (act === 'st-smtp') {
        var acct = ST.account || {}, sm = smtpFrom('sm', acct.email || ''); var cfgd = { host: sm.host, port: sm.port, security: sm.security, user: sm.user, password: sm.password, from: acct.email || '' };
        var sv = await kk('smtp_save', cfgd, false); drLog(sv.ok ? (sv.configured ? 'Email settings saved. Real codes are on.' : 'Email settings incomplete; demo mode stays on.') : sv.error); SEC.stale = true;
      }
      else if (act === 'st-smtp-test') { var ts = await kk('smtp_test'); drLog(ts.ok ? ts.message : ts.error); }
      else if (act === 'st-mir-add') { var pf = await kk('pick_folder'); if (pf.ok && pf.folder) { var ma = await kk('add_mirror', pf.folder); drLog(ma.ok ? 'Extra copies will be kept in ' + pf.folder : ma.error); } else drLog(pf.ok ? 'No folder chosen.' : pf.error); SEC.stale = true; }
      else if (act === 'st-mir-del') { var mi = (SEC.sec && SEC.sec.mirrors || [])[+b.dataset.i]; if (mi) { var md = await kk('remove_mirror', mi); drLog(md.ok ? 'Stopped copying to ' + mi : md.error); } SEC.stale = true; }
    } catch (e) { drLog('Something went wrong. Nothing was lost.'); }
    DR.busy = false; render();
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="http"]'); if (!a) return;
    e.preventDefault(); kk('open_url', a.href).then(function (r) { if (!r.ok) drLog(r.error); });
  }, true);
  async function boot() {
    S = emptyState(); S.view = 'home'; applyPerms(); render(); intro();
    var r = await kk('status');
    if (!r.ok) { gateOpen('<div class="dialog gate-box" role="alert"><h2>KinKeep could not start</h2><p>' + esc(r.error) + '</p></div>'); return; }
    ST = r; if (r.signedIn) { var l = await kk('load_state'); if (l.ok) { finishPayload(l); return; } }
    if (r.account && r.hasVault) gLogin(false); else if (r.hasVault) gLogin(false); else gRegister();
  }

  /* ======================================================================================================
     Family and roles page (Owner and Co-owner). Every rule is enforced by the Python engine; this page
     only shows the choices and reports what the engine said.
     ====================================================================================================== */
  var FAM = { stale: true, loading: false, data: null, msg: null, busy: false };
  NAMES.family = 'Family and roles';
  [GROUPS, GROUPS_ALL].forEach(function (L) { L.forEach(function (g) { if (g.id === 'fam' && g.items.indexOf('family') < 0) g.items.push('family'); }); });

  async function loadFamily() {
    if (FAM.loading || !V.on || !isManager()) return;
    FAM.loading = true; FAM.stale = false;
    var r = await kk('family_overview');
    FAM.loading = false;
    if (r.ok) FAM.data = r; else FAM.msg = { ok: false, text: r.error };
    if (S.view === 'family') render();
  }
  function famStatus(st) { return '<span class="chip' + (st === 'Active' ? ' ok' : st === 'Suspended' ? ' crit' : ' warn') + '">' + esc(st || '') + '</span>'; }
  function famRoleSelect(id, cur, list) {
    var o = list.slice(); if (cur && o.indexOf(cur) < 0) o.unshift(cur);
    return '<select id="' + id + '">' + o.map(function (r) { return '<option' + (r === cur ? ' selected' : '') + '>' + esc(r) + '</option>'; }).join('') + '</select>';
  }
  function famField(id, label, inner, hint) { return '<div class="fld"><label for="' + id + '">' + label + '</label>' + inner + (hint ? '<div class="small muted">' + hint + '</div>' : '') + '</div>'; }
  function famInput(id, type, val, extra) { return '<input type="' + type + '" id="' + id + '" value="' + esc(val || '') + '" autocomplete="' + (type === 'password' ? 'new-password' : 'off') + '" ' + (extra || '') + '>'; }
  function famSignInFields(id) {
    return famField('fa-l-' + id, 'Login name', famInput('fa-l-' + id, 'text', '', 'maxlength="30"'), '3 to 30 letters or numbers, for example <i>ravi</i>') +
      famField('fa-e-' + id, 'Their email address', famInput('fa-e-' + id, 'email', ''), 'Their sign-in codes are emailed here.') +
      famField('fa-p-' + id, 'Starting password', famInput('fa-p-' + id, 'password', '') + ' <button class="btn sm" type="button" data-act="fam-suggest" data-target="fa-p-' + id + '">Suggest one</button>', 'At least 10 characters. Tell them in person, not by email or text.');
  }
  function famPerson(p, D) {
    var id = esc(p.id), body, summary;
    summary = '<b>' + esc(p.name) + '</b> <span class="chip info">' + esc(p.role) + '</span> ' + famStatus(p.status) +
      ' <span class="small muted">' + (p.login ? 'Signs in as <b>' + esc(p.login) + '</b>' : 'No sign-in yet') + '</span>';
    if (!p.canManage) {
      body = '<p class="small muted">' + (p.role === 'Owner' ? 'The Owner is the person who created this vault and cannot be changed here.' : 'Only the Owner can change a Co-owner.') + '</p>';
    } else {
      body = '<div class="entry">' + famField('fe-n-' + id, 'Name', famInput('fe-n-' + p.id, 'text', p.name, 'maxlength="80"')) +
        famField('fe-r-' + id, 'Role', famRoleSelect('fe-r-' + p.id, p.role, D.assignable), 'See "What each role can do" below.') +
        famField('fe-s-' + id, 'Note: what they can see', famInput('fe-s-' + p.id, 'text', p.scope, 'maxlength="200"')) +
        '<div class="form-actions"><button class="btn primary" type="button" data-act="fam-save" data-id="' + id + '">Save changes</button></div></div>';
      if (p.login) {
        body += '<h3 class="small" style="margin:14px 0 6px">Sign-in</h3><p class="small muted">Login <b>' + esc(p.login) + '</b> &middot; codes go to <b>' + esc(maskEmail(p.email)) + '</b></p>' +
          '<div class="entry">' + famField('fa-rp-' + id, 'Set a new password for them', famInput('fa-rp-' + p.id, 'password', '') + ' <button class="btn sm" type="button" data-act="fam-suggest" data-target="fa-rp-' + id + '">Suggest one</button>', 'Use this if they forgot their password. At least 10 characters.') +
          '<div class="form-actions"><button class="btn" type="button" data-act="fam-reset" data-id="' + id + '">Set new password</button> ' +
          (p.status === 'Suspended' ? '<button class="btn" type="button" data-act="fam-resume" data-id="' + id + '">Turn sign-in back on</button>' : '<button class="btn" type="button" data-act="fam-pause" data-id="' + id + '">Pause sign-in</button>') +
          ' <button class="btn" type="button" data-act="st-mem-del-fam" data-id="' + id + '">Remove sign-in</button></div></div>';
      } else {
        body += '<details style="margin-top:12px"><summary class="small">Give ' + esc(p.name) + ' a sign-in</summary><div class="entry" style="margin-top:8px">' + famSignInFields(id) +
          '<div class="form-actions"><button class="btn primary" type="button" data-act="fam-signin" data-id="' + id + '">Create sign-in</button></div></div></details>';
        if (p.status === 'Suspended') body += '<div class="form-actions" style="margin-top:10px"><button class="btn" type="button" data-act="fam-resume" data-id="' + id + '">Approve again</button></div>';
      }
      body += '<div class="form-actions" style="margin-top:14px"><button class="btn danger" type="button" data-act="fam-del" data-id="' + id + '">Remove ' + esc(p.name) + ' from the family list</button></div>';
    }
    return '<li style="display:block"><details class="fam-person"><summary>' + summary + '</summary><div style="margin-top:10px">' + body + '</div></details></li>';
  }
  function famMatrix(D) {
    var views = Object.keys(D.matrix[0].views), roles = D.matrix;
    function cell(v) { return v === 'rw' ? '<td class="perm-full">Change</td>' : v === 'r' ? '<td class="perm-view">View</td>' : '<td class="perm-none">&ndash;</td>'; }
    var head = '<tr><th scope="col">Screen</th>' + roles.map(function (m) { return '<th scope="col">' + esc(m.role) + '</th>'; }).join('') + '</tr>';
    var rows = views.map(function (v) { return '<tr><th scope="row">' + esc(D.labels[v] || v) + '</th>' + roles.map(function (m) { return cell(m.views[v]); }).join('') + '</tr>'; }).join('');
    rows += '<tr><th scope="row">' + esc(D.labels.family) + '</th>' + roles.map(function (m) { return cell(m.family); }).join('') + '</tr>';
    return '<ul class="plain small" style="margin-bottom:12px">' + roles.map(function (m) { return '<li><b>' + esc(m.role) + ':</b> ' + esc(m.info) + '</li>'; }).join('') + '</ul>' +
      '<div class="tablewrap"><table class="perm-table"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>' +
      '<p class="small muted" style="margin-top:8px">Teens also see only their own documents and identity records. Adult Family Members see will and wish records without the private notes. The Emergency Contact role works only while the Owner allows emergency access.</p>';
  }
  function vFamily() {
    var out = head('Family and roles', 'Decide who in your family can open KinKeep and what each person can see or change.');
    if (!V.on) return out + panel('Sign in first', '<p>Family and roles work in your own vault. Sign in or create your account to use them. The sample data has no real sign-ins.</p><div class="form-actions" style="margin-top:12px"><button class="btn primary" type="button" data-act="st-signout">Go to sign in</button></div>');
    if (!isManager()) return out + panel('Owner and Co-owner only', '<p>Only the Owner or a Co-owner can manage family members. Ask them if you need a change.</p>');
    if (FAM.stale && !FAM.loading) loadFamily();
    var D = FAM.data;
    if (FAM.msg) out += '<div class="' + (FAM.msg.ok ? 'ro-note' : 'warn-note') + '" role="status" style="' + (FAM.msg.ok ? '' : 'background:var(--crit-soft);color:var(--crit);border-radius:8px;padding:8px 12px;margin:8px 0 12px;font-size:14px') + '">' + esc(FAM.msg.text) + '</div>';
    if (!D) return out + panel('Loading', '<p class="muted">Loading your family list&hellip;</p>');
    var pending = D.people.filter(function (p) { return p.status === 'Needs re-approval'; });
    if (pending.length) out += panel('Waiting for your approval', '<p class="small muted" style="margin-bottom:8px">These people came back from a backup. They keep their role, but nobody gets access until you approve them again and give them a sign-in.</p><p>' + pending.map(function (p) { return '<b>' + esc(p.name) + '</b> (' + esc(p.role) + ')'; }).join(', ') + '</p>', '<span class="chip warn">' + pending.length + ' to review</span>');
    out += panel('Family members', '<p class="small muted" style="margin-bottom:10px">Open a person to change their role, give them a sign-in, set a new password, pause their access or remove them. A sign-in gives a person their own login and password. They also need the six-digit code that is emailed to them.</p><ul class="files">' + D.people.map(function (p) { return famPerson(p, D); }).join('') + '</ul>', '<span class="chip">' + D.people.length + ' people</span>');
    out += panel('Add a family member', '<div class="entry">' + famField('fa-name', 'Name', famInput('fa-name', 'text', '', 'maxlength="80"')) +
      famField('fa-role', 'Role', famRoleSelect('fa-role', 'Adult Family Member', D.assignable), 'Not sure? Read "What each role can do" below. You can change it later.') +
      famField('fa-scope', 'Note: what they can see (optional)', famInput('fa-scope', 'text', '', 'maxlength="200"')) +
      '<details><summary class="small">Give them a sign-in now (optional)</summary><div class="entry" style="margin-top:8px">' + famSignInFields('new') + '</div></details>' +
      '<div class="form-actions" style="margin-top:12px"><button class="btn primary" type="button" data-act="fam-add">Add to family</button></div></div>');
    out += panel('What each role can do', famMatrix(D));
    if (D.emergency.canChange) {
      out += panel('Emergency access', '<p class="small muted" style="margin-bottom:10px">People with the Emergency Contact role can sign in only while you allow it, and then see the emergency essentials only. Allow it when it is needed and switch it off afterwards.</p><p style="margin-bottom:10px"><b>' + (D.emergency.active ? 'Allowed until ' + esc(new Date(D.emergency.until).toLocaleString()) : 'Not allowed right now') + '</b></p><div class="form-actions"><select id="fa-em-h" aria-label="How long"><option value="2">for 2 hours</option><option value="24" selected>for 24 hours</option><option value="72">for 3 days</option><option value="168">for 7 days</option></select> <button class="btn primary" type="button" data-act="fam-em-on">Allow emergency access</button> <button class="btn" type="button" data-act="fam-em-off">Switch it off</button></div>');
    }
    return out;
  }
  function famSuggest() {
    var a = 'abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRTUVWXYZ2346789', b = new Uint32Array(14), o = '';
    window.crypto.getRandomValues(b); for (var i = 0; i < b.length; i++) o += a.charAt(b[i] % a.length); return o;
  }
  async function familyAct(act, b) {
    if (act === 'fam-open') { go('family'); return; }
    if (act === 'fam-suggest') { var t = $('#' + b.dataset.target); if (t) { t.type = 'text'; t.value = famSuggest(); } return; }
    if (!V.on || !isManager() || FAM.busy) return;
    var id = b.dataset.id, r, ok = '';
    FAM.busy = true;
    try {
      if (act === 'fam-add') { r = await kk('family_add', val('fa-name'), val('fa-role'), val('fa-scope'), val('fa-l-new'), val('fa-e-new'), ($('#fa-p-new') || {}).value || ''); ok = 'Added ' + val('fa-name') + '.'; }
      else if (act === 'fam-save') { r = await kk('family_update', id, val('fe-r-' + id), val('fe-s-' + id), val('fe-n-' + id)); ok = 'Saved.'; }
      else if (act === 'fam-signin') { r = await kk('member_add', id, val('fa-l-' + id), val('fa-e-' + id), ($('#fa-p-' + id) || {}).value || ''); ok = 'Sign-in created. Give them the login name and password in person.'; }
      else if (act === 'fam-reset') { r = await kk('member_reset_password', id, ($('#fa-rp-' + id) || {}).value || ''); ok = 'New password set. Tell them in person.'; }
      else if (act === 'fam-pause') { r = await kk('family_pause', id, true); ok = 'Sign-in paused. They cannot open KinKeep until you turn it back on.'; }
      else if (act === 'fam-resume') { r = await kk('family_pause', id, false); ok = 'Access is back on.'; }
      else if (act === 'st-mem-del-fam') { r = await kk('member_remove', id); ok = 'Sign-in removed. They stay in the family list.'; }
      else if (act === 'fam-del') { if (!window.confirm('Remove this person from the family list? Their sign-in is deleted too.')) { FAM.busy = false; return; } r = await kk('family_delete', id); ok = 'Removed.'; }
      else if (act === 'fam-em-on') { r = await kk('emergency_grant', +(($('#fa-em-h') || {}).value || 24)); ok = 'Emergency access is allowed.'; }
      else if (act === 'fam-em-off') { r = await kk('emergency_revoke'); ok = 'Emergency access is switched off.'; }
      else { FAM.busy = false; return; }
    } catch (e) { r = { ok: false, error: 'Something went wrong. Nothing was changed.' }; }
    FAM.busy = false; FAM.msg = { ok: !!(r && r.ok), text: r && r.ok ? ok : (r && r.error) || 'That did not work.' }; FAM.stale = true;
    if (r && r.ok && r.state) { var v = S.view; applyPayload(r); S.view = v; }
    render();
  }
