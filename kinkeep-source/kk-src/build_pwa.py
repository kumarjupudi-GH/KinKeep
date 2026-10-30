import os, shutil, json, zipfile
from PIL import Image, ImageDraw
src=open('src/kinkeep.html').read()
import base64
for i in (1,2,3):
    b=base64.b64encode(open('src/img/storyboard-%d.jpg'%i,'rb').read()).decode()
    src=src.replace("'img/storyboard-%d.jpg'"%i, "'data:image/jpeg;base64,"+b+"'")
out='dist'
shutil.rmtree(out, ignore_errors=True); os.makedirs(out+'/icons')
if os.path.isdir('src/img'): shutil.copytree('src/img', out+'/img')
# icons
def icon(n, pad):
    im=Image.new('RGBA',(n,n),(46,138,104,255)); d=ImageDraw.Draw(im)
    s=n*(1-2*pad); x0=n*pad; y0=n*pad
    pts=[(x0, y0+s*0.48),(x0+s*0.5, y0+s*0.05),(x0+s, y0+s*0.48),(x0+s, y0+s*0.95),(x0, y0+s*0.95)]
    d.polygon(pts, fill=(255,255,255,255))
    cx, cy, r = x0+s*0.5, y0+s*0.64, s*0.17
    d.ellipse((cx-r*1.0-r*0.2, cy-r*1.1, cx-r*0.0+0.0, cy+r*0.2), fill=(232,137,43,255))
    d.ellipse((cx, cy-r*1.1, cx+r*1.2, cy+r*0.2), fill=(232,137,43,255))
    d.polygon([(cx-r*1.2, cy-r*0.4),(cx+r*1.2, cy-r*0.4),(cx, cy+r*1.5)], fill=(232,137,43,255))
    return im
icon(192,0.2).save(out+'/icons/icon-192.png'); icon(512,0.2).save(out+'/icons/icon-512.png'); icon(512,0.28).save(out+'/icons/icon-maskable-512.png')
manifest={"name":"KinKeep","short_name":"KinKeep","description":"Protect what matters: family records, renewals, wills and emergency plans, locked with your own passphrase.","start_url":"KinKeep.html","scope":"./","display":"standalone","orientation":"any","background_color":"#edf0f3","theme_color":"#2e8a68","icons":[{"src":"icons/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any"},{"src":"icons/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any"},{"src":"icons/icon-maskable-512.png","sizes":"512x512","type":"image/png","purpose":"maskable"}]}
json.dump(manifest, open(out+'/manifest.webmanifest','w'), indent=2)
head='<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n<meta name="theme-color" content="#2e8a68">\n<link rel="manifest" href="manifest.webmanifest">\n<script src="config.js"></script>\n<link rel="icon" href="icons/icon-192.png">\n<link rel="apple-touch-icon" href="icons/icon-192.png">\n<meta name="apple-mobile-web-app-capable" content="yes">\n<style>*,*::before,*::after{box-sizing:border-box}[hidden]{display:none!important}html,body{margin:0}</style>\n'
reg="\n<script>if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('sw.js').catch(function(){});});}</script>\n"
open(out+'/KinKeep.html','w').write(head+src+reg+'</body>\n</html>\n')
LOGO='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#2e8a68"/><g transform="translate(8 8) scale(2)" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-7.5 9 7.5v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5z"/><path d="M12 17.6s-3.4-2.1-3.4-4.4a1.9 1.9 0 0 1 3.4-1.1 1.9 1.9 0 0 1 3.4 1.1c0 2.3-3.4 4.4-3.4 4.4z" fill="#f0a04b" stroke="#f0a04b" stroke-width="1"/></g></svg>'
open(out+'/KinKeep-logo.svg','w').write(LOGO)
icon(512,0.12).save(out+'/KinKeep-logo.png')
import base64 as _b
fav='data:image/svg+xml;base64,'+_b.b64encode(LOGO.encode()).decode()
idx=open(out+'/KinKeep.html').read().replace('<link rel="icon" href="icons/icon-192.png">','<link rel="icon" type="image/svg+xml" href="'+fav+'">',1)
open(out+'/KinKeep.html','w').write(idx)
open(out+'/index.html','w').write('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>KinKeep</title><link rel="icon" type="image/svg+xml" href="'+fav+'"><meta http-equiv="refresh" content="0;url=KinKeep.html"></head><body><script>location.replace("KinKeep.html")</script><a href="KinKeep.html">Open KinKeep</a></body></html>')
ic=icon(256,0.1); ic.save(out+'/KinKeep.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
open(out+'/Create-KinKeep-Desktop-Shortcut.bat','w',newline='\r\n').write(r'''@echo off
rem Creates a KinKeep shortcut with the KinKeep icon on your Desktop (Windows).
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\KinKeep.lnk'); $s.TargetPath='%HERE%KinKeep.html'; $s.IconLocation='%HERE%KinKeep.ico'; $s.Description='KinKeep - Protect What Matters'; $s.Save()"
echo KinKeep shortcut created on your Desktop.
pause
''')
open(out+'/config.js','w').write('// KinKeep settings. Set mailEndpoint to your email-code service address (see email-server/README.md).\n// Leave it empty to run in demo mode, where sign-in codes are shown on screen instead of emailed.\nwindow.KINKEEP_CONFIG = { mailEndpoint: %s };\n' % json.dumps(os.environ.get('KINKEEP_MAIL','')))
if os.path.isdir('email-server'):
    shutil.copytree('email-server', out+'/email-server', ignore=shutil.ignore_patterns('node_modules','package-lock.json'))
assets=['./','index.html','config.js','KinKeep.html','KinKeep.ico','KinKeep-logo.svg','KinKeep-logo.png','manifest.webmanifest','icons/icon-192.png','icons/icon-512.png','icons/icon-maskable-512.png']+['img/'+f for f in sorted(os.listdir(out+'/img'))] if os.path.isdir(out+'/img') else []
sw="""var CACHE='kinkeep-v1';
var ASSETS=%s;
self.addEventListener('install',function(e){e.waitUntil(caches.open(CACHE).then(function(c){return c.addAll(ASSETS);}).then(function(){return self.skipWaiting();}));});
self.addEventListener('activate',function(e){e.waitUntil(caches.keys().then(function(ks){return Promise.all(ks.filter(function(k){return k!==CACHE;}).map(function(k){return caches.delete(k);}));}).then(function(){return self.clients.claim();}));});
self.addEventListener('fetch',function(e){
  var r=e.request; if(r.method!=='GET') return;
  var u=new URL(r.url); if(u.origin!==location.origin) return;
  e.respondWith(fetch(r).then(function(res){var cp=res.clone();caches.open(CACHE).then(function(c){c.put(r,cp);});return res;}).catch(function(){return caches.match(r).then(function(m){return m||caches.match('KinKeep.html');});}));
});
"""%json.dumps(assets)
open(out+'/sw.js','w').write(sw)
open(out+'/README.txt','w').write("""KinKeep, installable app package
=================================
What this is: a static website (no server code, no accounts). Put these files on any https host and open the address.
Start: double-click KinKeep.html (the app),. On Windows, double-click Create-KinKeep-Desktop-Shortcut.bat once to put a KinKeep shortcut with the KinKeep icon on your Desktop (a .html file itself cannot carry a custom icon). index.html only forwards to KinKeep.html and is there for web hosting. KinKeep-logo.png / .svg are the logo files.
Sign-in codes: KinKeep asks for an emailed 6-digit code at registration, sign-in and password reset. A static web app cannot send email, so out of the box it runs in DEMO MODE and shows the code on screen. For real email, run the small service in email-server/ (see its README) and put its address in config.js.\nInstall: in Chrome or Edge choose the install icon in the address bar (Install KinKeep). On Android Chrome use Add to Home screen / Install app. On iPhone Safari use Share, Add to Home Screen. Windows: Edge or Chrome, Install, and it appears in the Start menu.

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
""")
with zipfile.ZipFile('kinkeep-app.zip','w',zipfile.ZIP_DEFLATED) as z:
    for root,_,fs in os.walk(out):
        for f in fs:
            p=os.path.join(root,f); z.write(p, os.path.relpath(p,out))
print('built', os.path.getsize('kinkeep-app.zip'))
