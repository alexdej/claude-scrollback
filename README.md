# scrollback

A viewer for [Claude Code](https://claude.ai/claude-code) session transcripts. Converts `.jsonl` session files into readable, interactive HTML — either as a static site generator or a local web server you point at a directory.

![index page showing a list of sessions with metadata pills](docs/screenshot-index.png)

## What it does

Claude Code saves every session to a `.jsonl` file (typically in `~/.claude/projects/`). These files contain the full conversation: user messages, Claude's responses, tool calls and their results, token usage, and session metadata.

`scrollback` turns those files into something you can actually read — useful for revisiting the reasoning behind a commit, a design decision, or a tricky debugging session.

Each session renders as a threaded conversation with:
- **Human messages** and **Claude responses** in distinct styled bubbles
- **Tool calls** (Read, Edit, Bash, Glob, etc.) collapsible with their full inputs
- **Tool results** collapsible, truncated for large outputs
- **Thinking blocks** collapsible when present (note: Claude Code redacts the thinking text, preserving only the cryptographic signature)
- **Context compaction markers** when Claude Code summarised the context mid-session
- **API errors** (rate limits, auth failures) surfaced inline
- **Token usage** shown per response
- **Session metadata**: working directory, git branch, start/end time, message and tool call counts

The index page lists all sessions sorted newest-first with a live filter box.

## Usage

### Local web server (recommended)

```bash
python server.py path/to/jsonl/directory/
python server.py path/to/jsonl/directory/ 9000   # custom port, default is 8080
```

Open `http://localhost:8080` in your browser. The server regenerates HTML on every request, so newly added session files appear immediately without restarting.

Stop with `Ctrl+C`.

### Static site generator

```bash
# Single file
python viewer.py session.jsonl
python viewer.py session.jsonl output.html

# Whole directory — writes index.html + one HTML per session
python viewer.py path/to/jsonl/directory/
```

## Where Claude Code stores sessions

Sessions live under `~/.claude/projects/`, organised by project path:

```
~/.claude/projects/
  C--Users-you-Projects-myapp/
    abc123.jsonl
    def456.jsonl
  C--Users-you-Projects-other/
    ...
```

Point scrollback at any of those subdirectories.

## Linking sessions to git commits

A session file on its own is useful, but becomes much more useful when you can connect it to the code it produced. One convention that works well: include the session ID as a git trailer when committing work done in a Claude Code session.

```
Fix authentication token refresh race condition

Claude-Session: abc123de-f456-7890-abcd-ef1234567890
```

Git trailers are machine-readable, so you can later do:

```bash
git log --grep="Claude-Session:"
```

The session ID appears in the metadata card at the top of each session page (click 📋 to copy it).

## Requirements

Python 3.8+, standard library only. No dependencies to install.

## Example sessions

The `example/` directory contains three short synthetic sessions demonstrating the viewer's rendering across different scenarios (file reads, edits, bash commands, multi-turn conversations).

```bash
python server.py example/
```
