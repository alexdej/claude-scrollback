#!/usr/bin/env python3
"""
Claude JSONL Session Viewer — HTTP Server

Serves the session index and individual session pages dynamically from a
directory of .jsonl files. HTML is generated on each request so new or
updated session files are picked up immediately without re-running anything.

Usage:
  python server.py <directory/> [port]

  port defaults to 8080.

Open http://localhost:8080 in your browser.
"""

import sys
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote

# Import rendering functions from viewer.py (must be in the same directory)
from viewer import generate_html, generate_index_html, extract_meta


class SessionHandler(BaseHTTPRequestHandler):
    # Set by the server before starting
    sessions_dir: Path = None

    def log_message(self, fmt, *args):
        # Cleaner log output
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
        parsed = urlparse(self.path)
        path = unquote(parsed.path).lstrip("/")

        # Index
        if path in ("", "index.html"):
            self.serve_index()

        # Individual session page — path may include subdirectory, e.g. "projectA/abc.html"
        elif path.endswith(".html"):
            jsonl_path = self.sessions_dir / (path[:-5] + ".jsonl")
            if jsonl_path.exists():
                self.serve_session(jsonl_path)
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
        html = generate_index_html(sessions)
        self.send_html(html)

    def serve_session(self, jsonl_path: Path):
        html = generate_html(jsonl_path)
        self.send_html(html)


def run(sessions_dir: Path, port: int):
    SessionHandler.sessions_dir = sessions_dir

    server = HTTPServer(("", port), SessionHandler)
    server.timeout = 0.5  # handle_request() returns every 0.5s so Ctrl+C is caught promptly

    print(f"Serving {sessions_dir.resolve()}")
    print(f"Open http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python server.py <directory/> [port]")
        sys.exit(1)

    sessions_dir = Path(sys.argv[1])
    if not sessions_dir.is_dir():
        print(f"Error: {sessions_dir} is not a directory")
        sys.exit(1)

    port = 8080
    if len(sys.argv) >= 3:
        try:
            port = int(sys.argv[2])
        except ValueError:
            print(f"Error: invalid port {sys.argv[2]}")
            sys.exit(1)

    run(sessions_dir, port)


if __name__ == "__main__":
    main()
