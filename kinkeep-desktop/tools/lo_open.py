"""Independent check: open an encrypted .xlsx in LibreOffice (headless) with a password and print
the sheets and first cells as JSON. Used by the tests and by the disaster-recovery self-test.
Usage: python lo_open.py FILE PASSWORD
Exit code 0 = opened, 3 = could not open (wrong password or unreadable)."""
import json, os, subprocess, sys, tempfile, time


def open_with_lo(path, password, port=2111):
    import uno
    from com.sun.star.beans import PropertyValue
    prof = tempfile.mkdtemp(prefix="lo_prof_")
    p = subprocess.Popen(["soffice", "--headless", "--invisible", "--norestore", "-env:UserInstallation=file://" + prof,
                          "--accept=socket,host=localhost,port=%d;urp;" % port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ctx = None
        for _ in range(60):
            try:
                local = uno.getComponentContext()
                res = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
                ctx = res.resolve("uno:socket,host=localhost,port=%d;urp;StarOffice.ComponentContext" % port)
                break
            except Exception:
                time.sleep(0.5)
        if ctx is None:
            raise RuntimeError("LibreOffice did not start")
        desk = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)

        def pv(n, v):
            x = PropertyValue(); x.Name = n; x.Value = v; return x
        try:
            doc = desk.loadComponentFromURL("file://" + os.path.abspath(path), "_blank", 0, (pv("Hidden", True), pv("Password", password)))
        except Exception:
            doc = None  # LibreOffice aborts type detection when the password is wrong
        if doc is None:
            return None
        out = {}
        sheets = doc.Sheets
        for i in range(sheets.Count):
            sh = sheets.getByIndex(i)
            cur = sh.createCursor(); cur.gotoEndOfUsedArea(False)
            rows, cols = cur.RangeAddress.EndRow + 1, cur.RangeAddress.EndColumn + 1
            out[sh.Name] = [[sh.getCellByPosition(c, r).String for c in range(cols)] for r in range(rows)]
        doc.close(True)
        return out
    finally:
        try:
            desk.terminate()
        except Exception:
            pass
        try:
            p.wait(timeout=20)
        except Exception:
            p.kill()


if __name__ == "__main__":
    r = open_with_lo(sys.argv[1], sys.argv[2])
    if r is None:
        print("COULD NOT OPEN"); sys.exit(3)
    print(json.dumps(r))
