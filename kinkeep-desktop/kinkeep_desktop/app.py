"""Desktop launcher: opens the KinKeep window (pywebview) and wires the page to the Python engine.

  python -m kinkeep_desktop                  normal start
  python -m kinkeep_desktop --data-dir DIR   keep the data somewhere else (default: Documents/KinKeep Data)
  python -m kinkeep_desktop --dev            serve the page on 127.0.0.1 for automated UI tests (no window)

The page can only call methods that exist on KinkeepApi, and that class holds the engine in a private
attribute, so nothing but the vetted, role-checked API is reachable from the web view.
"""
from __future__ import annotations
import argparse
import json
import logging
import logging.handlers
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .bridge import Bridge, Host, default_data_dir
from .store import Locked, atomic_write


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)  # set by PyInstaller
    return Path(base) / "kinkeep_desktop" if base else Path(__file__).resolve().parent


def make_js_api(bridge: Bridge):
    """Expose exactly the @api methods of Bridge, and nothing else (no attributes, no store, no keys)."""
    ns = {"__init__": lambda self, b: setattr(self, "_b", b)}
    for name in dir(Bridge):
        if getattr(getattr(Bridge, name), "is_api", False):
            def mk(n):
                def call(self, *a):
                    return getattr(self._b, n)(*a)
                call.__name__ = n
                return call
            ns[name] = mk(name)
    return type("KinkeepApi", (), ns)(bridge)


def api_names() -> set[str]:
    return {n for n in dir(Bridge) if getattr(getattr(Bridge, n), "is_api", False)}


def alert(msg: str) -> None:
    """A message that works before any window exists."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "KinKeep", 0x40)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'display dialog %s with title "KinKeep" buttons {"OK"}' % json.dumps(msg)], check=False)
        else:
            print(msg, file=sys.stderr)
    except Exception:
        print(msg, file=sys.stderr)


class DesktopHost(Host):
    """Native dialogs and OS hand-offs."""
    def __init__(self, export_dir: Path):
        super().__init__(export_dir)
        self.window = None

    def save_file(self, suggested: str, data: bytes) -> str | None:
        import webview
        r = self.window.create_file_dialog(webview.SAVE_DIALOG, directory=str(Path.home() / "Documents"), save_filename=suggested)
        if not r:
            return None
        path = Path(r[0] if isinstance(r, (list, tuple)) else r)
        atomic_write(path, data)
        return str(path)

    def choose_folder(self) -> str | None:
        import webview
        r = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return str(r[0]) if r else None

    def open_folder(self, path: str) -> None:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 (a folder we created)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def open_dictation(self) -> bool:
        """Windows: press Windows key + H for the person (opens Windows voice typing in the focused box).
        macOS has no safe way to start Dictation from an app, so the screen tells the person to press Fn twice."""
        if sys.platform != "win32":
            return False
        import ctypes
        k, VK_LWIN, VK_H, UP = ctypes.windll.user32.keybd_event, 0x5B, 0x48, 0x2
        k(VK_LWIN, 0, 0, 0); k(VK_H, 0, 0, 0); k(VK_H, 0, UP, 0); k(VK_LWIN, 0, UP, 0)
        return True

    def open_url(self, url: str) -> None:
        webbrowser.open(url)  # the bridge has already checked the address against its allow-list


def setup_logging(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(data_dir / "kinkeep.log", maxBytes=200_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("kinkeep").addHandler(h)
    logging.getLogger("kinkeep").setLevel(logging.WARNING)  # warnings and errors only; never request data


# ----------------------------------------------------------------------------- dev / test server
def serve_dev(bridge: Bridge, port: int = 0, ready=None) -> tuple[ThreadingHTTPServer, str]:
    token = secrets.token_urlsafe(24)
    names, lock = api_names(), threading.Lock()
    page = (resource_dir() / "ui" / "index.html").read_text("utf-8").replace("<title>KinKeep</title>", '<title>KinKeep</title>\n<script>window.KK_DEV=%s;</script>' % json.dumps(token), 1)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8") if self.path in ("/", "/index.html") else self._send(404, b"{}")

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            if self.headers.get("X-KK-Token") != token or name not in names:
                return self._send(403, b'{"ok":false,"error":"forbidden"}')
            n = int(self.headers.get("Content-Length") or 0)
            try:
                args = json.loads(self.rfile.read(n) or b"[]")
            except ValueError:
                return self._send(400, b"{}")
            with lock:
                res = getattr(bridge, name)(*args)
            self._send(200, json.dumps(res).encode("utf-8"))

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


# ----------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kinkeep", description="KinKeep Desktop")
    ap.add_argument("--data-dir", help="folder for the encrypted vault and spreadsheet")
    ap.add_argument("--dev", action="store_true", help="serve the page on localhost for automated tests (no window)")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        print("KinKeep Desktop", __version__)
        return 0
    data_dir = Path(a.data_dir) if a.data_dir else default_data_dir()
    setup_logging(data_dir)
    host = DesktopHost(data_dir / "exports")
    bridge = Bridge(data_dir, host=host)
    try:
        bridge.store.acquire_lock()
    except Locked as e:
        alert(str(e) + " Close the other window first.")
        return 1
    try:
        if a.dev:
            srv, url = serve_dev(bridge)
            print("KinKeep dev server:", url, flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            return 0
        try:
            import webview
        except ImportError:
            alert("KinKeep needs the 'pywebview' package. Install it with:  pip install pywebview")
            return 2
        win = webview.create_window("KinKeep", url=str(resource_dir() / "ui" / "index.html"), js_api=make_js_api(bridge),
                                    width=1280, height=860, min_size=(900, 600), text_select=True)
        host.window = win
        win.events.closed += lambda: bridge.signout()
        webview.settings["ALLOW_DOWNLOADS"] = False   # saving goes through our own dialog
        webview.start(private_mode=True)               # nothing is kept by the web view itself (no cache, no storage)
        return 0
    finally:
        bridge.signout()
        bridge.store.release_lock()


if __name__ == "__main__":
    sys.exit(main())
