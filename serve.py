"""Dependency-free dev server: python3 serve.py  ->  http://127.0.0.1:8000 (API + web UI)."""
import json, os, mimetypes, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import engine as E, handlers
ROOT = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {".html", ".js", ".css", ".ico", ".svg", ".png"}   # never serve .py or .db files

def find_web():
    """Use web/ if present; otherwise the folder next to serve.py (when the files were saved flat)."""
    for d in (os.path.join(ROOT, "web"), ROOT):
        if os.path.isfile(os.path.join(d, "index.html")): return d
    return None

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}

def make_server(db, port=8000, web=None, quiet=True):
    WEB = os.path.realpath(web or find_web() or ROOT)
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            if not quiet: print("  request:", fmt % a, flush=True)
        def _json(self, code, obj):
            b = json.dumps(obj).encode(); self.send_response(code)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def _api(self, method):
            u = urlparse(self.path); n = int(self.headers.get("Content-Length") or 0)
            if n > 20000: return self._json(413, {"error": "Request too large"})
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError: return self._json(400, {"error": "Invalid JSON"})
            code, obj = handlers.handle(db, method, u.path, self.headers.get("X-Session"), body, {k: v[0] for k, v in parse_qs(u.query).items()})
            self._json(code, obj)
        def do_POST(self): self._api("POST") if self.path.startswith("/api/") else self._json(404, {"error": "Not found"})
        def do_GET(self):
            p = urlparse(self.path).path
            if p.startswith("/api/"): return self._api("GET")
            f = os.path.realpath(os.path.join(WEB, "index.html" if p == "/" else p.lstrip("/")))
            if not f.startswith(WEB + os.sep) or not os.path.isfile(f) or os.path.splitext(f)[1] not in ALLOWED:
                msg = ("<h1>SmartClaim: page not found</h1><p>You asked for: <code>%s</code></p><p>index.html, app.js and style.css must be in a <code>web</code> folder next to serve.py "
                       "(or directly next to it). Looked in: %s</p>" % (p, WEB)).encode()
                self.send_response(404); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(msg))); self.end_headers(); return self.wfile.write(msg)
            b = open(f, "rb").read(); self.send_response(200)
            self.send_header("Content-Type", TYPES[os.path.splitext(f)[1]]); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    return ThreadingHTTPServer(("127.0.0.1", port), H)

if __name__ == "__main__":
    db = E.connect(os.getenv("SMARTCLAIM_DB", "smartclaim.db"))
    if not db.execute("SELECT 1 FROM customers").fetchone(): E.seed(db)
    w = find_web()
    if not w: sys.exit("index.html not found. Put index.html, app.js and style.css in a 'web' folder next to serve.py.")
    s = make_server(db, int(os.getenv("PORT", 8765)), w, quiet=False); print("Serving UI from", w); port = s.server_port
    import threading, urllib.request
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try: print("Self-check GET / ->", urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5).status)
    except Exception as ex: print("Self-check FAILED:", ex)
    print("\nOpen exactly this address in your browser:  http://127.0.0.1:%d/\nPress Ctrl+C to stop. Requests will be listed below.\n" % port)
    try:
        while True: threading.Event().wait(3600)
    except KeyboardInterrupt: pass
