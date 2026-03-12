# scrollback

A lightweight viewer for [Claude Code](https://claude.ai/claude-code) session transcripts. Converts `.jsonl` session files into readable, interactive HTML — with a built-in server for browsing and a static site generator for archiving.

Pure python, no dependencies to install.

**[Live demo →](https://alexdej.github.io/claude-scrollback/)**

## Install

pip (recommended)
```bash
pip install claude-scrollback
```

from source:

```bash
git clone https://github.com/alexdej/claude-scrollback
pip install claude_scrollback
```

Or use `generator.py` standalone:

```bash
git clone https://github.com/alexdej/claude-scrollback
cd claude_scrollback
python claude_scrollback/generator.py <dir>
```

## Usage

### Quick start

Installation installs a `claude-scrollback` command.

```bash
# Browse all your Claude Code sessions (uses ~/.claude/projects/ automatically)
claude-scrollback

# Browse sessions for the current Claude Code project directory
claude-scrollback .

# Browse sessions for a specific project
claude-scrollback ~/projects/myapp

# View a single session file
claude-scrollback path/to/session.jsonl
```

All directory modes start a local server and open your browser automatically.

`claude-scrollback` is the command installed by `pip install claude-scrollback`. If you're running from a clone without installing, use `python -m claude_scrollback` in place of `claude-scrollback` throughout. Add a shell alias if you want something shorter:

```bash
alias sb='claude-scrollback'
```

### Options

```
claude-scrollback [path] [--port PORT] [--no-browser] [--build [OUTDIR]]

path            .jsonl file, sessions directory, or project directory
                default: ~/.claude/projects/

--port PORT     server port (default: 8080)
--no-browser    don't open browser automatically
--build [OUTDIR] generate static HTML instead of serving
                 default output: _site/
```

### Examples

```bash
claude-scrollback                          # all projects, port 8080, opens browser
claude-scrollback . --port 9000            # current project, custom port
claude-scrollback . --no-browser           # start server without opening browser
claude-scrollback . --build                # generate static HTML to ./_site/
claude-scrollback . --build ~/my-archive/  # generate to a custom directory
claude-scrollback session.jsonl            # convert single file, open in browser
```

### Path resolution

When you pass a project directory (like `.`), scrollback maps it to the corresponding Claude Code sessions folder automatically. Claude Code stores sessions under `~/.claude/projects/` with the project path encoded as the directory name (colons, slashes, and backslashes replaced with `-`):

```
~/projects/myapp  →  ~/.claude/projects/-home-you-projects-myapp/
C:\Users\you\myapp  →  ~/.claude/projects/C--Users-you-myapp/
```

If the path you give already contains `.jsonl` files (directly or in subdirectories), it's used as-is.

## What it renders

Each session page shows:

- **Human messages** and **Claude responses** in distinct styled bubbles
- **Tool calls** (Read, Edit, Bash, Glob, Write, etc.) collapsible with full inputs
- **Tool results** collapsible, truncated for large outputs
- **Thinking blocks** collapsible when present
- **Context compaction markers** when Claude Code summarised the context mid-session
- **API errors** (rate limits, auth failures) surfaced inline
- **Token usage** per response
- **Session metadata**: working directory, git branch, start/end time, message and tool call counts
- **Resume command** — one click copies `cd <project> && claude --resume <session-id>` to clipboard

The index page lists all sessions sorted newest-first with a live filter box and per-session metadata pills.

> **Note:** Session transcripts include everything shown to Claude during the conversation — file contents, command output, environment details, and more. Review before sharing or publishing.

## Linking sessions to commits

Include the session ID as a git trailer when committing AI-assisted work:

```
Fix authentication token refresh race condition

Claude-Session: abc123de-f456-7890-abcd-ef1234567890
```

The session ID is shown in the metadata card on each session page with a 📋 copy button. The resume command (also one-click copyable) lets you pick up the conversation right where it left off.

```bash
# Find all AI-assisted commits
git log --grep="Claude-Session:"
```

## Session directory layout

Claude Code organises sessions by project under `~/.claude/projects/`:

```
~/.claude/projects/
  C--Users-you-projects-myapp/
    abc123.jsonl
    def456.jsonl
  -home-you-projects-other/
    ...
```

`scrollback` handles both flat directories (one project) and nested trees (all projects).

## Example sessions

The `example/projects/` directory contains synthetic sessions demonstrating the viewer across different scenarios. To browse them:

```bash
scrollback example/projects/
```

## Requirements

Python 3.8+, standard library only.
