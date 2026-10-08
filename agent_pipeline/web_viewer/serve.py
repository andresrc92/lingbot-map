#!/usr/bin/env python
"""Serve the three.js viewer and the exported assets.

    python agent_pipeline/web_viewer/serve.py [--port 8081]

Serves the repository root (the viewer reads data/blender/export/*) and opens at
http://localhost:<port>/  ->  agent_pipeline/web_viewer/index.html
"""
import argparse
import functools
import http.server
import mimetypes
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")
mimetypes.add_type("application/octet-stream", ".ply")
mimetypes.add_type("text/javascript", ".js")


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/agent_pipeline/web_viewer/" + ("?" + query if query else ""))
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "404" in (fmt % args):
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()
    os.chdir(REPO)
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), functools.partial(Handler, directory=str(REPO)))
    print(f"three.js viewer: http://localhost:{args.port}/  (Ctrl+C to stop)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
