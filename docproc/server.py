"""Weissenberg: zero-dependency local web server (stdlib only). Binds to 127.0.0.1 - your documents stay on your machine."""
from __future__ import annotations

import json
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .exporters import export_csv, export_excel
from .records import MIMES, public, to_json
from .store import Store

STATIC = Path(__file__).resolve().parent.parent / "static"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
MAX_UPLOAD = 60 * 1024 * 1024


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "docproc"

        def log_message(self, *a):      # quiet
            pass

        # ---- helpers
        def send(self, code, body=b"", ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                raise ValueError("File too large (60 MB max)")
            return self.rfile.read(n)

        def route(self, method):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = unquote(url.path)
            try:
                return self.dispatch(method, path, q)
            except KeyError:
                self.send(404, {"error": "not found"})
            except Exception as e:                       # report, never crash the server
                self.send(400, {"error": str(e)})

        do_GET = lambda self: self.route("GET")
        do_POST = lambda self: self.route("POST")
        do_PUT = lambda self: self.route("PUT")
        do_DELETE = lambda self: self.route("DELETE")

        # ---- routing
        def dispatch(self, method, path, q):
            if method == "GET" and not path.startswith("/api/"):
                name = "index.html" if path in ("/", "") else path.lstrip("/")
                f = (STATIC / name).resolve()
                if STATIC not in f.parents or not f.is_file():
                    raise KeyError
                return self.send(200, f.read_bytes(), STATIC_TYPES.get(f.suffix, "application/octet-stream"))

            if path == "/api/docs" and method == "GET":
                return self.send(200, [public(r) for r in store.all()])

            if path == "/api/process" and method == "POST":
                name = q.get("name", "document.txt")
                rec, dup = store.add(Path(name).name, self.body(), q.get("dayfirst", "1") == "1",
                                     q.get("type") or None)
                return self.send(200, {"doc": public(rec), "duplicate": dup})

            if path == "/api/clear" and method == "POST":
                store.clear()
                return self.send(200, {"ok": True})

            if path == "/api/export" and method == "GET":
                recs = store.all(q.get("verified") == "1")
                if not recs:
                    return self.send(400, {"error": "Nothing to export"})
                fmt = q.get("format", "xlsx")
                if fmt == "xlsx":
                    return self.send(200, export_excel(recs),
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                     {"Content-Disposition": 'attachment; filename="documents.xlsx"'})
                if fmt in ("csv", "line_items"):
                    kind = "line_items" if fmt == "line_items" else "documents"
                    return self.send(200, export_csv(recs, kind), "text/csv; charset=utf-8",
                                     {"Content-Disposition": f'attachment; filename="{kind}.csv"'})
                if fmt == "json":
                    return self.send(200, json.dumps([to_json(r) for r in recs], indent=2, ensure_ascii=False).encode(),
                                     "application/json", {"Content-Disposition": 'attachment; filename="documents.json"'})
                raise ValueError("unknown format")

            m = re.fullmatch(r"/api/doc/([0-9a-f]{10})(/file)?", path)
            if m:
                rid, is_file = m.group(1), m.group(2)
                if rid not in store.records:
                    raise KeyError
                if is_file and method == "GET":
                    f = store.file_path(rid)
                    if not f:
                        raise KeyError
                    return self.send(200, f.read_bytes(), MIMES.get(f.suffix, "application/octet-stream"),
                                     {"Content-Disposition": "inline"})
                if method == "PUT":
                    rec = store.update(rid, json.loads(self.body() or b"{}"))
                    return self.send(200, {"doc": public(rec),
                                           "all": [{"id": r["id"], "status": public(r)["status"],
                                                    "verified": r["verified"], "issues": r["issues"]}
                                                   for r in store.all()]})
                if method == "DELETE":
                    store.delete(rid)
                    return self.send(200, {"ok": True})
            raise KeyError

    return Handler


def serve(port=8000, data_dir="data", open_browser=True):
    store = Store(data_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    url = f"http://127.0.0.1:{port}"
    print(f"Weissenberg running at {url}  (Ctrl+C to stop)\nData folder: {Path(data_dir).resolve()}")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        httpd.server_close()
