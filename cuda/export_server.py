"""Serve the repo and accept geometry uploads from cuda/export.html.

Usage:
    python cuda/export_server.py            # then open http://127.0.0.1:8765/cuda/export.html

The export page loads index.html in an iframe, waits for the car to build, and
POSTs each structural part's world-space triangles here so the CFD grid uses
exactly the geometry (and transform) the site renders.
"""
import http.server
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cuda" / "geom"
PORT = 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_POST(self):
        m = re.fullmatch(r"/__export/([A-Za-z0-9_.-]+)", self.path)
        if not m:
            self.send_error(404)
            return
        OUT.mkdir(parents=True, exist_ok=True)
        n = int(self.headers.get("Content-Length", 0))
        (OUT / m.group(1)).write_bytes(self.rfile.read(n))
        print(f"saved {m.group(1)} ({n} bytes)")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


if __name__ == "__main__":
    os.chdir(ROOT)
    print(f"serving {ROOT} on http://127.0.0.1:{PORT}/cuda/export.html")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
