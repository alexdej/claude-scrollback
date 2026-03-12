#!/usr/bin/env python3
"""HTTP server for claude-scrollback. Generates HTML on each request."""

import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote

try:
    from .generator import generate_html, generate_index_html, extract_meta
except ImportError:
    from generator import generate_html, generate_index_html, extract_meta


class SessionHandler(BaseHTTPRequestHandler):
    sessions_dir: Path = None

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def send_html(self, content: str, status: int = 200):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_404(self):
        self.send_html("<h1>404 Not Found</h1>", status=404)

    def do_GET(self):
        path = unquote(urlparse(self.path).path).lstrip("/")

        if path in ("", "index.html"):
            self.serve_index()
        elif path.endswith(".html"):
            jsonl_path = self.sessions_dir / (path[:-5] + ".jsonl")
            if jsonl_path.exists():
                self.send_html(generate_html(jsonl_path))
            else:
                self.send_404()
        else:
            self.send_404()

    def serve_index(self):
        sessions = []
        for f in sorted(self.sessions_dir.rglob("*.jsonl")):
            meta = extract_meta(f)
            if meta:
                rel = f.relative_to(self.sessions_dir)
                meta["project"] = rel.parts[0] if len(rel.parts) > 1 else ""
                meta["html_filename"] = rel.with_suffix(".html").as_posix()
                sessions.append(meta)
        self.send_html(generate_index_html(sessions))


def run(sessions_dir: Path, port: int):
    SessionHandler.sessions_dir = sessions_dir
    server = HTTPServer(("", port), SessionHandler)
    server.timeout = 0.5
    print(f"Serving {sessions_dir.resolve()}")
    print(f"Open http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nStopped.")
