const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1280, height: 850 }, acceptDownloads: true });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error' && !/fonts|ERR_|Failed to load/.test(m.text())) errs.push(m.text()); });
  const ok = (c, m) => console.log((c ? 'PASS ' : 'FAIL ') + m);
  await p.goto('http://localhost:8765/'); await p.waitForTimeout(800);
  ok(await p.isVisible('#gate'), 'setup gate shows on first run');
  // short pass rejected
  await p.fill('#g-pass', 'short'); await p.fill('#g-pass2', 'short'); await p.click('[data-g=create]');
  ok(/at least 10/.test(await p.textContent('#g-msg')), 'short passphrase rejected');
  await p.fill('#g-pass', 'correct horse battery'); await p.fill('#g-pass2', 'correct horse battery'); await p.click('[data-g=create]');
  ok(/confirm/.test(await p.textContent('#g-msg')), 'ack required');
  await p.check('#g-ack'); await p.check('input[name=g-start][value=sample]'); await p.click('[data-g=create]');
  await p.waitForTimeout(2500);
  ok(!(await p.isVisible('#gate')), 'gate closes after create');
  ok(/Encrypted|saved|vault/i.test(await p.textContent('#rail-vault')), 'rail status: ' + (await p.textContent('#rail-vault')));
  const raw = await p.evaluate(() => localStorage.getItem('kinkeep.vault.v1'));
  ok(raw && raw.includes('"ct"') && !/Nair|Arun|Priya/.test(raw), 'ciphertext only in localStorage (' + (raw||'').length + ' bytes)');
  // add a record, then reload and unlock
  await p.click('[data-nav=assets]'); await p.waitForTimeout(200);
  await p.fill('#f-assets-name', 'Zebra Test Asset'); await p.click('form[data-coll=assets] button[type=submit]'); await p.waitForTimeout(2500);
  const raw2 = await p.evaluate(() => localStorage.getItem('kinkeep.vault.v1'));
  ok(raw2 !== raw && !/Zebra/.test(raw2), 'save re-encrypted, no plaintext');
  await p.reload(); await p.waitForTimeout(800);
  ok(await p.isVisible('#gate') && /locked/i.test(await p.textContent('#gate')), 'locked after reload');
  await p.fill('#g-pass', 'wrong passphrase!!'); await p.click('[data-g=unlock]'); await p.waitForTimeout(1800);
  ok(/did not unlock/.test(await p.textContent('#g-msg')), 'wrong passphrase rejected');
  await p.fill('#g-pass', 'correct horse battery'); await p.press('#g-pass', 'Enter'); await p.waitForTimeout(2500);
  ok(!(await p.isVisible('#gate')), 'unlocked');
  await p.click('[data-nav=assets]'); ok((await p.textContent('#main')).includes('Zebra Test Asset'), 'record persisted across reload');
  // storage screen
  await p.click('[data-nav=drive]'); await p.waitForTimeout(200);
  const t = await p.textContent('#main'); ok(/Your vault/.test(t) && /Backup copies/.test(t) && /Where your document files/.test(t) && /Change passphrase/.test(t), 'storage screen panels');
  // export
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 5000 }).catch(() => null), p.click('[data-act=st-export]')]);
  ok(!!dl, 'backup downloads'); if (dl) { await dl.saveAs('/tmp/kk-backup.json'); const j = require('fs').readFileSync('/tmp/kk-backup.json', 'utf8'); ok(!/Zebra|Nair/.test(j) && /"ct"/.test(j), 'backup is encrypted'); }
  // doc pref
  await p.selectOption('#st-docs', 'drive'); await p.waitForTimeout(200); ok(/Google Drive/.test(await p.textContent('#main')), 'doc store preference');
  // change passphrase
  await p.fill('#pf-cur', 'correct horse battery'); await p.fill('#pf-new', 'new longer passphrase 42'); await p.fill('#pf-new2', 'new longer passphrase 42'); await p.click('#passForm button[type=submit]'); await p.waitForTimeout(3000);
  ok(/changed|Passphrase/i.test(await p.textContent('.logbox')), 'passphrase change logged: ' + (await p.textContent('.logbox')).slice(-80).replace(/\n/g, ' | '));
  // lock now, unlock with new
  await p.click('[data-act=st-lock]'); await p.waitForTimeout(600); ok(await p.isVisible('#gate'), 'lock now shows gate');
  await p.fill('#g-pass', 'correct horse battery'); await p.click('[data-g=unlock]'); await p.waitForTimeout(1800); ok(/did not unlock/.test(await p.textContent('#g-msg')), 'old passphrase rejected');
  await p.fill('#g-pass', 'new longer passphrase 42'); await p.click('[data-g=unlock]'); await p.waitForTimeout(2500); ok(!(await p.isVisible('#gate')), 'new passphrase unlocks');
  // restore backup (old pass) via storage screen
  await p.click('[data-nav=drive]'); await p.setInputFiles('#st-file', '/tmp/kk-backup.json'); await p.waitForTimeout(500);
  ok(/different passphrase|Open this backup/i.test(await p.textContent('#main')), 'restore asks for backup passphrase');
  await p.fill('#st-bpass', 'correct horse battery'); await p.click('[data-act=st-decrypt]'); await p.waitForTimeout(2500);
  ok(/Replace your data/.test(await p.textContent('#main')), 'backup decrypts to review'); await p.click('[data-act=drive-apply]'); await p.waitForTimeout(500);
  await p.click('[data-nav=assets]'); ok((await p.textContent('#main')).includes('Zebra Test Asset'), 'restored data present');
  // advisor intent
  await p.click('[data-nav=home]'); await p.click('#fab').catch(()=>{}); await p.fill('#q', 'change my passphrase'); await p.press('#q', 'Enter'); await p.waitForTimeout(700);
  ok(/Storage and security/.test(await p.textContent('#main')), 'advisor opens storage screen');
  // PWA
  await p.waitForTimeout(1500);
  const sw = await p.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration(); return !!r; }); ok(sw, 'service worker registered');
  const mf = await p.evaluate(async () => { const r = await fetch('manifest.webmanifest'); const j = await r.json(); return j.name + ' ' + j.icons.length; }); ok(/KinKeep 3/.test(mf), 'manifest ' + mf);
  // widths
  for (const w of [1280, 390]) { await p.setViewportSize({ width: w, height: 800 }); await p.waitForTimeout(200); const ov = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth); ok(ov <= 1, 'no horizontal overflow at ' + w + ' (' + ov + ')'); }
  // phone gate
  await p.reload(); await p.waitForTimeout(800); await p.screenshot({ path: 'gate-phone.png' });
  await p.setViewportSize({ width: 1280, height: 850 }); await p.fill('#g-pass', 'new longer passphrase 42'); await p.click('[data-g=unlock]'); await p.waitForTimeout(2500); await p.click('[data-nav=drive]'); await p.screenshot({ path: 'storage.png', fullPage: true });
  console.log('ERRORS', JSON.stringify(errs)); await b.close();
})();
