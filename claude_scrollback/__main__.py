#!/usr/bin/env python3
"""
claude-scrollback CLI
Usage: claude-scrollback <command> [path] [options]
       python -m claude_scrollback <command> [path] [options]
"""

import re
import sys
import argparse
import tempfile
import webbrowser
import threading
import time
from pathlib import Path

from .generator import generate_html, process_directory
from .server import run as run_server


# ── Path resolution ────────────────────────────────────────────────────────

def map_project_to_sessions(project_path: Path) -> Path:
    """
    Map a project directory to its ~/.claude/projects/ entry.
    Claude Code encodes the path by replacing : / \\ with -.
    e.g. C:\\Users\\alex\\Projects\\myapp -> C--Users-alex-Projects-myapp
    """
    path_str = str(project_path.resolve())
    mapped = path_str.replace("\\", "-").replace("/", "-").replace(":", "-")
    return Path.home() / ".claude" / "projects" / mapped


def find_sessions_dir(path_str: str) -> Path:
    """
    Given a path string, return the sessions directory to use.

    Resolution order:
      1. Path has .jsonl files directly or recursively -> use as-is
      2. Otherwise -> map to ~/.claude/projects/<encoded>/
    """
    path = Path(path_str).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if any(path.glob("*.jsonl")) or any(path.rglob("*.jsonl")):
        return path

    mapped = map_project_to_sessions(path)
    if mapped.exists() and any(mapped.rglob("*.jsonl")):
        print(f"Using sessions from {mapped}")
        return mapped

    raise FileNotFoundError(
        f"No Claude Code sessions found.\n"
        f"  Checked: {path}\n"
        f"  Checked: {mapped}\n"
        f"Run from a Claude Code project directory, or pass the sessions path directly."
    )


def default_sessions_dir() -> Path:
    """Return ~/.claude/projects/ if it exists and has sessions."""
    default = Path.home() / ".claude" / "projects"
    if default.exists() and any(default.rglob("*.jsonl")):
        return default
    raise FileNotFoundError(
        "~/.claude/projects/ not found or empty.\n"
        "Pass a path: claude-scrollback view <project-or-sessions-dir>"
    )


def resolve(path_arg):
    """Resolve optional path arg to a sessions directory."""
    if path_arg:
        return find_sessions_dir(path_arg)
    return default_sessions_dir()


def open_browser(url: str, delay: float = 0.4):
    """Open browser after a short delay (gives server time to start)."""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


# ── Subcommands ────────────────────────────────────────────────────────────

def cmd_view(args):
    # Single file
    if args.path and Path(args.path).is_file():
        src = Path(args.path)
        if src.suffix != ".jsonl":
            print(f"Error: {src} is not a .jsonl file")
            sys.exit(1)
        out = src.with_suffix(".html")
        print(f"Generating {out} ...")
        generate_html(src, out)
        url = out.resolve().as_uri()
        if not args.no_open:
            webbrowser.open(url)
        else:
            print(f"Open: {url}")
        return

    try:
        sessions_dir = resolve(args.path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    url = f"http://localhost:{args.port}"
    if not args.no_open:
        open_browser(url)
    run_server(sessions_dir, args.port)



UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

def cmd_show(args):
    # Collect UUIDs from positional arg and/or piped stdin
    uuids = []
    if args.uuid:
        if UUID_RE.fullmatch(args.uuid):
            uuids.append(args.uuid.lower())
        else:
            print(f"Error: '{args.uuid}' is not a valid UUID")
            sys.exit(1)

    if not sys.stdin.isatty():
        text = sys.stdin.read()
        for m in UUID_RE.finditer(text):
            u = m.group(0).lower()
            if u not in uuids:
                uuids.append(u)

    if not uuids:
        print("Error: provide a UUID argument or pipe text containing UUIDs")
        sys.exit(1)

    projects = Path.home() / ".claude" / "projects"
    opened = 0
    for uuid in uuids:
        matches = list(projects.rglob(f"{uuid}.jsonl"))
        if not matches:
            print(f"Warning: no session found for {uuid}")
            continue
        for src in matches:
            out = Path(tempfile.mkdtemp()) / (src.stem + ".html")
            generate_html(src, out)
            webbrowser.open(out.resolve().as_uri())
            print(f"Opened: {src.name}")
            opened += 1

    if opened == 0:
        sys.exit(1)


def cmd_generate(args):
    if args.path and Path(args.path).is_file():
        src = Path(args.path)
        if src.suffix != ".jsonl":
            print(f"Error: {src} is not a .jsonl file")
            sys.exit(1)
        out = src.with_suffix(".html")
        generate_html(src, out)
        print(f"Written to {out}")
        return

    try:
        sessions_dir = resolve(args.path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    print(f"Generating static site from {sessions_dir} -> {out_dir} ...")
    process_directory(sessions_dir, out_dir)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="claude-scrollback",
        description="Lightweight viewer for Claude Code session transcripts.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    # view
    p_view = sub.add_parser(
        "view",
        help="start a local server and open the session browser",
    )
    p_view.add_argument(
        "path", nargs="?",
        help="session file (.jsonl), sessions dir, or project dir "
             "(default: ~/.claude/projects/)",
    )
    p_view.add_argument("-p", "--port", type=int, default=8080, help="port (default: 8080)")
    p_view.add_argument("-n", "--no-open", action="store_true", help="don't open browser")

    # show
    p_show = sub.add_parser(
        "show",
        help="find and open a session by UUID (also accepts piped text)",
    )
    p_show.add_argument(
        "uuid", nargs="?",
        help="session UUID (or omit and pipe text containing UUIDs)",
    )

    # generate
    p_gen = sub.add_parser(
        "generate",
        help="generate static HTML from session files",
    )
    p_gen.add_argument(
        "path", nargs="?",
        help="session file (.jsonl), sessions dir, or project dir "
             "(default: ~/.claude/projects/)",
    )
    p_gen.add_argument(
        "-o", "--out-dir", default="_site", metavar="DIR",
        help="output directory (default: _site/)",
    )

    args = parser.parse_args()

    if args.command == "view":
        cmd_view(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "generate":
        cmd_generate(args)


if __name__ == "__main__":
    main()
