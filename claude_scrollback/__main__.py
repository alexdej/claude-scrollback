#!/usr/bin/env python3
"""
claude-scrollback CLI
Usage: scrollback [path] [options]
       python -m claude_scrollback [path] [options]
"""

import sys
import argparse
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
    e.g. C:\\Users\\alex\\Projects\\myapp → C--Users-alex-Projects-myapp
    """
    path_str = str(project_path.resolve())
    mapped = path_str.replace("\\", "-").replace("/", "-").replace(":", "-")
    return Path.home() / ".claude" / "projects" / mapped


def find_sessions_dir(path_str: str) -> Path:
    """
    Given a path string, return the sessions directory to use.

    Resolution order:
      1. Path has .jsonl files directly → use as-is
      2. Path has .jsonl files recursively → use as-is (projects root)
      3. Otherwise → map to ~/.claude/projects/<encoded>/
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
    """Return ~/.claude/projects/ if it exists."""
    default = Path.home() / ".claude" / "projects"
    if default.exists() and any(default.rglob("*.jsonl")):
        return default
    raise FileNotFoundError(
        "~/.claude/projects/ not found or empty.\n"
        "Pass a path: scrollback <project-or-sessions-dir>"
    )


def open_browser(url: str, delay: float = 0.4):
    """Open browser after a short delay (gives server time to start)."""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="scrollback",
        description="Lightweight viewer for Claude Code session transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  scrollback                        # browse all projects in ~/.claude/projects/
  scrollback .                      # sessions for the current project
  scrollback ~/projects/myapp       # sessions for a specific project
  scrollback ~/path/to/sessions/    # use a sessions directory directly
  scrollback session.jsonl          # view a single session file
  scrollback . --build              # generate static HTML to ./_site/
  scrollback . --build ~/site/      # generate static HTML to a custom path
  scrollback . --port 9000          # custom port
  scrollback . --no-browser         # don't open browser automatically
""",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="session file (.jsonl), sessions directory, or project directory "
             "(default: ~/.claude/projects/)",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="server port (default: 8080)",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="don't open browser automatically",
    )
    parser.add_argument(
        "--build", nargs="?", const="_site", metavar="OUTDIR",
        help="generate static HTML instead of serving "
             "(default output dir: _site/)",
    )

    args = parser.parse_args()

    # ── Single file mode ───────────────────────────────────────────────────
    if args.path and Path(args.path).is_file():
        src = Path(args.path)
        if src.suffix != ".jsonl":
            print(f"Error: {src} is not a .jsonl file")
            sys.exit(1)
        out = src.with_suffix(".html")
        print(f"Generating {out} ...")
        generate_html(src, out)
        url = out.resolve().as_uri()
        if not args.no_browser:
            webbrowser.open(url)
        else:
            print(f"Open: {url}")
        return

    # ── Resolve sessions directory ─────────────────────────────────────────
    try:
        if args.path:
            sessions_dir = find_sessions_dir(args.path)
        else:
            sessions_dir = default_sessions_dir()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # ── Build mode ─────────────────────────────────────────────────────────
    if args.build is not None:
        out_dir = Path(args.build)
        print(f"Building static site from {sessions_dir} -> {out_dir} ...")
        process_directory(sessions_dir, out_dir)
        url = (out_dir / "index.html").resolve().as_uri()
        if not args.no_browser:
            webbrowser.open(url)
        else:
            print(f"Open: {url}")
        return

    # ── Serve mode (default) ───────────────────────────────────────────────
    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        open_browser(url)
    run_server(sessions_dir, args.port)


if __name__ == "__main__":
    main()
