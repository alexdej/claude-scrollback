#!/usr/bin/env python3
"""
claude-scrollback: generator
Converts Claude Code .jsonl session files to readable HTML.

Standalone usage (copy this file anywhere, no install needed):
  python generator.py <session.jsonl> [output.html]
  python generator.py <sessions-dir/> [output-dir/]

Pure Python stdlib, no dependencies.
"""

import sys
import json
import html
import os
import re
from pathlib import Path
from datetime import datetime


def fmt_ts(ts_str):
    """Format ISO timestamp to readable string."""
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts_str


def fmt_ms(ms):
    """Format milliseconds to human-readable duration."""
    if ms is None:
        return ""
    ms = int(ms)
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        mins = ms // 60000
        secs = (ms % 60000) / 1000
        return f"{mins}m {secs:.0f}s"


def escape(text):
    return html.escape(str(text))


def render_text_content(text):
    """Render markdown-ish text to safe HTML."""
    text = str(text)
    # Escape HTML
    text = html.escape(text)
    # Code blocks (```...```)
    text = re.sub(
        r"```(\w*)\n(.*?)```",
        lambda m: f'<pre class="code-block"><code class="lang-{escape(m.group(1))}">{m.group(2)}</code></pre>',
        text,
        flags=re.DOTALL,
    )
    # Inline code
    text = re.sub(r"`([^`]+)`", r'<code class="inline-code">\1</code>', text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Newlines to <br> (but not inside pre blocks)
    lines = text.split("\n")
    result = []
    in_pre = False
    for line in lines:
        if "<pre " in line:
            in_pre = True
        if "</pre>" in line:
            in_pre = False
            result.append(line)
            continue
        if in_pre:
            result.append(line + "\n")
        else:
            result.append(line + "<br>")
    return "".join(result)


def render_tool_input(tool_name, tool_input):
    """Render tool call input nicely."""
    parts = []
    for k, v in tool_input.items():
        v_str = json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v)
        parts.append(
            f'<div class="tool-param">'
            f'<span class="param-key">{escape(k)}</span>'
            f'<span class="param-sep">:</span>'
            f'<span class="param-val"><pre>{escape(v_str)}</pre></span>'
            f'</div>'
        )
    return "".join(parts)


def render_tool_result(content):
    """Render tool result content."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", json.dumps(item)))
            else:
                parts.append(str(item))
        text = "\n".join(parts)
    else:
        text = json.dumps(content, indent=2)

    # Truncate very long results
    MAX = 4000
    truncated = False
    if len(text) > MAX:
        text = text[:MAX]
        truncated = True

    escaped = escape(text)
    trunc_note = '<span class="truncated-note">[output truncated]</span>' if truncated else ""
    return f'<pre class="tool-result-content">{escaped}</pre>{trunc_note}'


def build_conversation(messages):
    """
    Build a structured conversation thread from raw messages.
    Returns list of turn groups, where each group is a list of messages
    belonging to the same human-initiated turn.
    """
    # Index by uuid
    by_uuid = {}
    for m in messages:
        uuid = m.get("uuid")
        if uuid:
            by_uuid[uuid] = m

    # Sort by timestamp
    def ts_key(m):
        return m.get("timestamp", "")

    messages_sorted = sorted(messages, key=ts_key)

    # Group into turns: a new turn starts when a user sends a non-tool_result message
    turns = []
    current_turn = []

    for m in messages_sorted:
        mtype = m.get("type")

        if mtype == "user":
            msg = m.get("message", {})
            content = msg.get("content", "")
            # Check if this is a human message or just tool results
            if isinstance(content, str) and content.strip():
                # Human text message — starts a new turn
                if current_turn:
                    turns.append(current_turn)
                current_turn = [m]
            elif isinstance(content, list):
                has_human_text = any(
                    c.get("type") == "text" for c in content
                )
                has_tool_result = any(
                    c.get("type") == "tool_result" for c in content
                )
                if has_human_text and not has_tool_result:
                    if current_turn:
                        turns.append(current_turn)
                    current_turn = [m]
                else:
                    current_turn.append(m)
            else:
                current_turn.append(m)
        elif mtype in ("assistant", "progress", "system"):
            current_turn.append(m)
        # Skip file-history-snapshot and last-prompt for main view

    if current_turn:
        turns.append(current_turn)

    return turns


def render_usage(usage):
    """Render token usage badge."""
    if not usage:
        return ""
    parts = []
    if usage.get("input_tokens"):
        parts.append(f'in:{usage["input_tokens"]}')
    if usage.get("cache_read_input_tokens"):
        parts.append(f'cache_read:{usage["cache_read_input_tokens"]}')
    if usage.get("cache_creation_input_tokens"):
        parts.append(f'cache_write:{usage["cache_creation_input_tokens"]}')
    if usage.get("output_tokens"):
        parts.append(f'out:{usage["output_tokens"]}')
    if not parts:
        return ""
    return f'<span class="usage-badge">{" | ".join(parts)} tokens</span>'


def render_message(m, tool_results_map):
    """Render a single message entry to HTML."""
    mtype = m.get("type")
    ts = fmt_ts(m.get("timestamp", ""))
    parts = []

    if mtype == "user":
        msg = m.get("message", {})
        content = msg.get("content", "")

        # Compact summaries are auto-generated by Claude Code, not real human messages
        if m.get("isCompactSummary"):
            summary_text = ""
            if isinstance(content, str):
                summary_text = content
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        summary_text = item.get("text", "")
                        break
            parts.append(
                f'<div class="compact-summary">'
                f'<div class="compact-summary-header" onclick="toggleNext(this)">'
                f'<span>⚡ Context compacted</span>'
                f'<span class="toggle-hint">▼</span>'
                f'</div>'
                f'<div class="compact-summary-body collapsed">'
                f'<div class="compact-summary-text">{render_text_content(summary_text)}</div>'
                f'</div>'
                f'</div>'
            )
            return "".join(parts)

        if isinstance(content, str):
            parts.append(
                f'<div class="bubble user-bubble">'
                f'<div class="bubble-meta"><span class="role-tag user-tag">Human</span>'
                f'<span class="ts">{ts}</span></div>'
                f'<div class="bubble-body">{render_text_content(content)}</div>'
                f'</div>'
            )
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    parts.append(
                        f'<div class="bubble user-bubble">'
                        f'<div class="bubble-meta"><span class="role-tag user-tag">Human</span>'
                        f'<span class="ts">{ts}</span></div>'
                        f'<div class="bubble-body">{render_text_content(item["text"])}</div>'
                        f'</div>'
                    )
                elif item.get("type") == "tool_result":
                    tool_id = item.get("tool_use_id", "")
                    tool_name = tool_results_map.get(tool_id, {}).get("name", "tool")
                    is_error = item.get("is_error", False)
                    error_cls = " tool-result-error" if is_error else ""
                    parts.append(
                        f'<div class="tool-result-block{error_cls}">'
                        f'<div class="tool-result-header" onclick="toggleNext(this)">'
                        f'<span class="tool-icon">{"⚠" if is_error else "↩"}</span>'
                        f'<span class="tool-result-label">Result: <strong>{escape(tool_name)}</strong></span>'
                        f'<span class="toggle-hint">▼</span>'
                        f'</div>'
                        f'<div class="tool-result-body collapsed">'
                        f'{render_tool_result(item.get("content", ""))}'
                        f'</div>'
                        f'</div>'
                    )

    elif mtype == "assistant":
        msg = m.get("message", {})
        content = msg.get("content", [])
        usage = msg.get("usage")

        # API-level error (auth failure, rate limit, etc.)
        if m.get("isApiErrorMessage") or m.get("error"):
            err = m.get("error") or "unknown error"
            parts.append(
                f'<div class="api-error-block">'
                f'<span class="api-error-icon">⚠</span>'
                f'<span class="api-error-text">API error: {escape(str(err))}</span>'
                f'</div>'
            )
            return "".join(parts)

        for item in content:
            ctype = item.get("type")

            if ctype == "thinking":
                thinking_text = item.get("thinking", "")
                if thinking_text.strip():
                    parts.append(
                        f'<div class="thinking-block">'
                        f'<div class="thinking-header" onclick="toggleNext(this)">'
                        f'<span class="think-icon">💭</span> Thinking'
                        f'<span class="toggle-hint">▼</span>'
                        f'</div>'
                        f'<div class="thinking-body collapsed">'
                        f'<pre class="thinking-content">{escape(thinking_text)}</pre>'
                        f'</div>'
                        f'</div>'
                    )

            elif ctype == "text":
                text = item.get("text", "")
                if text.strip():
                    usage_html = render_usage(usage) if usage else ""
                    parts.append(
                        f'<div class="bubble assistant-bubble">'
                        f'<div class="bubble-meta"><span class="role-tag assistant-tag">Claude</span>'
                        f'<span class="ts">{ts}</span>{usage_html}</div>'
                        f'<div class="bubble-body">{render_text_content(text)}</div>'
                        f'</div>'
                    )
                    usage = None  # only show once

            elif ctype == "tool_use":
                tool_name = item.get("name", "unknown")
                tool_input = item.get("input", {})
                tool_id = item.get("id", "")
                parts.append(
                    f'<div class="tool-call-block">'
                    f'<div class="tool-call-header" onclick="toggleNext(this)">'
                    f'<span class="tool-icon">🔧</span>'
                    f'<span class="tool-name">{escape(tool_name)}</span>'
                    f'<span class="toggle-hint">▼</span>'
                    f'</div>'
                    f'<div class="tool-call-body collapsed">'
                    f'{render_tool_input(tool_name, tool_input)}'
                    f'</div>'
                    f'</div>'
                )

    elif mtype == "system":
        subtype = m.get("subtype", "")
        if subtype == "turn_duration":
            dur = fmt_ms(m.get("durationMs"))
            parts.append(
                f'<div class="system-note">Turn duration: {dur}</div>'
            )
        elif subtype == "compact_boundary":
            meta = m.get("compactMetadata", {})
            pre_tokens = meta.get("preTokens", "")
            trigger = meta.get("trigger", "")
            detail = f"{pre_tokens:,} tokens" if pre_tokens else ""
            if trigger:
                detail = f"{trigger} · {detail}" if detail else trigger
            parts.append(
                f'<div class="compact-boundary">'
                f'<span class="compact-boundary-line"></span>'
                f'<span class="compact-boundary-label">context compacted{(" — " + escape(detail)) if detail else ""}</span>'
                f'<span class="compact-boundary-line"></span>'
                f'</div>'
            )

    return "".join(parts)


def generate_html(jsonl_path, out_path=None):
    """Parse JSONL and generate HTML. Writes to out_path if given, else returns the string."""
    messages = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # Build a map of tool_use_id -> {name, input} for labeling tool results
    tool_results_map = {}
    for m in messages:
        if m.get("type") == "assistant":
            for item in m.get("message", {}).get("content", []):
                if item.get("type") == "tool_use":
                    tool_results_map[item["id"]] = {
                        "name": item.get("name", "unknown"),
                        "input": item.get("input", {}),
                    }

    # Extract session metadata
    session_id = ""
    cwd = ""
    git_branch = ""
    slug = ""
    version = ""
    for m in messages:
        if m.get("type") in ("user", "assistant"):
            session_id = session_id or m.get("sessionId", "")
            cwd = cwd or m.get("cwd", "")
            git_branch = git_branch or m.get("gitBranch", "")
            slug = slug or m.get("slug", "")
            version = version or m.get("version", "")

    # Get timestamps
    timestamps = [m.get("timestamp") for m in messages if m.get("timestamp")]
    start_ts = min(timestamps) if timestamps else ""
    end_ts = max(timestamps) if timestamps else ""

    # Filter for conversation messages
    conv_messages = [
        m for m in messages
        if m.get("type") in ("user", "assistant", "system")
        and not m.get("isSidechain")
    ]

    # Build and render turns
    turns = build_conversation(conv_messages)

    turns_html = []
    for i, turn in enumerate(turns):
        turn_parts = []
        for m in turn:
            rendered = render_message(m, tool_results_map)
            if rendered:
                turn_parts.append(rendered)
        if turn_parts:
            turns_html.append(
                f'<div class="turn" id="turn-{i}">'
                + "".join(turn_parts)
                + "</div>"
            )

    conversation_html = "\n".join(turns_html)

    # Stats
    user_msgs = sum(1 for m in messages if m.get("type") == "user")
    asst_msgs = sum(1 for m in messages if m.get("type") == "assistant")
    tool_calls = sum(
        1
        for m in messages
        if m.get("type") == "assistant"
        for item in m.get("message", {}).get("content", [])
        if item.get("type") == "tool_use"
    )

    title = escape(slug or session_id or jsonl_path.name)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --surface2: #22263a;
      --border: #2e3352;
      --text: #e2e4ed;
      --text-dim: #8b90a8;
      --user-bg: #1e2a3a;
      --user-border: #2d6aad;
      --user-tag: #4a9de8;
      --asst-bg: #1a2035;
      --asst-border: #5a3fa0;
      --asst-tag: #9d7fe8;
      --think-bg: #1e1a2e;
      --think-border: #4a3a6e;
      --tool-bg: #1a2a1e;
      --tool-border: #3a7a4a;
      --tool-name: #5db870;
      --result-bg: #2a1a1a;
      --result-border: #7a3a3a;
      --result-error: #c0392b;
      --code-bg: #12151e;
      --inline-code-bg: #252a3e;
      --accent: #7c6fef;
      --radius: 8px;
      --font-mono: "JetBrains Mono", "Fira Code", "Consolas", monospace;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: var(--font-sans);
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.6;
    }}

    /* ── Header ─────────────────────────────────────────────── */
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      position: sticky;
      top: 0;
      z-index: 100;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }}

    header h1 {{
      font-size: 16px;
      font-weight: 600;
      color: var(--text);
    }}

    .meta-pill {{
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 3px 10px;
      font-size: 11px;
      color: var(--text-dim);
      font-family: var(--font-mono);
    }}

    .header-actions {{
      margin-left: auto;
      display: flex;
      gap: 8px;
    }}

    button {{
      background: var(--surface2);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 5px 12px;
      font-size: 12px;
      cursor: pointer;
      transition: background 0.15s;
    }}
    button:hover {{ background: var(--border); }}

    /* ── Layout ─────────────────────────────────────────────── */
    main {{
      max-width: 860px;
      margin: 0 auto;
      padding: 24px 16px 80px;
    }}

    /* ── Session info card ───────────────────────────────────── */
    .session-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 20px;
      margin-bottom: 24px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 10px;
    }}

    .session-field {{ display: flex; flex-direction: column; gap: 2px; }}
    .session-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-dim); }}
    .session-value {{ font-size: 13px; font-family: var(--font-mono); color: var(--text); word-break: break-all; }}
    .session-id-row {{ display: flex; align-items: center; gap: 6px; }}
    .session-id-row .session-value {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; word-break: normal; }}
    .session-resume {{ grid-column: 1 / -1; }}
    .resume-cmd {{ font-size: 12px; }}
    .copy-btn {{
      flex-shrink: 0;
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--text-dim);
      cursor: pointer;
      font-size: 11px;
      padding: 2px 7px;
      transition: color 0.15s, border-color 0.15s;
    }}
    .copy-btn:hover {{ color: var(--text); border-color: var(--accent); }}

    /* ── Turn ───────────────────────────────────────────────── */
    .turn {{
      margin-bottom: 8px;
    }}

    /* ── Bubbles ────────────────────────────────────────────── */
    .bubble {{
      border-radius: var(--radius);
      padding: 14px 16px;
      margin-bottom: 6px;
      border-left: 3px solid transparent;
    }}

    .bubble-meta {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      font-size: 11px;
    }}

    .role-tag {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 4px;
    }}

    .user-tag {{ background: rgba(74,157,232,0.15); color: var(--user-tag); }}
    .assistant-tag {{ background: rgba(157,127,232,0.15); color: var(--asst-tag); }}

    .ts {{ color: var(--text-dim); font-family: var(--font-mono); }}

    .user-bubble {{
      background: var(--user-bg);
      border-left-color: var(--user-border);
    }}

    .assistant-bubble {{
      background: var(--asst-bg);
      border-left-color: var(--asst-border);
    }}

    .bubble-body br:last-child {{ display: none; }}

    /* ── Thinking block ──────────────────────────────────────── */
    .thinking-block {{
      background: var(--think-bg);
      border: 1px solid var(--think-border);
      border-radius: var(--radius);
      margin-bottom: 6px;
      overflow: hidden;
    }}

    .thinking-header {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-dim);
      user-select: none;
    }}
    .thinking-header:hover {{ background: rgba(255,255,255,0.03); }}

    .thinking-content {{
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.6;
      padding: 12px 14px;
      white-space: pre-wrap;
      word-break: break-word;
      color: #9a9cbf;
      border-top: 1px solid var(--think-border);
    }}

    /* ── Tool call block ─────────────────────────────────────── */
    .tool-call-block {{
      background: var(--tool-bg);
      border: 1px solid var(--tool-border);
      border-radius: var(--radius);
      margin-bottom: 6px;
      overflow: hidden;
    }}

    .tool-call-header {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      cursor: pointer;
      user-select: none;
    }}
    .tool-call-header:hover {{ background: rgba(255,255,255,0.03); }}

    .tool-icon {{ font-size: 14px; }}

    .tool-name {{
      font-family: var(--font-mono);
      font-size: 13px;
      font-weight: 600;
      color: var(--tool-name);
    }}

    .tool-call-body {{
      padding: 12px 14px;
      border-top: 1px solid var(--tool-border);
    }}

    .tool-param {{
      display: grid;
      grid-template-columns: auto auto 1fr;
      gap: 4px 8px;
      align-items: start;
      margin-bottom: 8px;
    }}

    .param-key {{
      font-family: var(--font-mono);
      font-size: 12px;
      color: #6eb5ff;
      white-space: nowrap;
      padding-top: 2px;
    }}
    .param-sep {{ color: var(--text-dim); padding-top: 2px; }}
    .param-val pre {{
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text);
      white-space: pre-wrap;
      word-break: break-word;
      background: var(--code-bg);
      padding: 6px 10px;
      border-radius: 4px;
    }}

    /* ── Tool result block ───────────────────────────────────── */
    .tool-result-block {{
      background: var(--result-bg);
      border: 1px solid var(--result-border);
      border-radius: var(--radius);
      margin-bottom: 6px;
      overflow: hidden;
    }}

    .tool-result-error {{ border-color: var(--result-error); }}
    .tool-result-error .tool-result-header {{ color: #e87070; }}

    .tool-result-header {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 9px 14px;
      cursor: pointer;
      font-size: 12px;
      user-select: none;
      color: #c0855a;
    }}
    .tool-result-header:hover {{ background: rgba(255,255,255,0.03); }}

    .tool-result-label {{ flex: 1; }}

    .tool-result-body {{
      border-top: 1px solid var(--result-border);
      padding: 12px 14px;
    }}

    .tool-result-content {{
      font-family: var(--font-mono);
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
      color: #b0b8c8;
    }}

    .truncated-note {{
      font-size: 11px;
      color: var(--text-dim);
      font-style: italic;
      margin-top: 6px;
      display: block;
    }}

    /* ── Code ────────────────────────────────────────────────── */
    pre.code-block {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      margin: 8px 0;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.5;
    }}

    code.inline-code {{
      background: var(--inline-code-bg);
      border-radius: 3px;
      padding: 1px 5px;
      font-family: var(--font-mono);
      font-size: 12px;
    }}

    /* ── Collapse / expand ───────────────────────────────────── */
    .collapsed {{ display: none; }}

    .toggle-hint {{
      margin-left: auto;
      font-size: 10px;
      color: var(--text-dim);
      transition: transform 0.15s;
    }}

    .toggle-hint.open {{ transform: rotate(180deg); }}

    /* ── System notes ────────────────────────────────────────── */
    .system-note {{
      text-align: center;
      font-size: 11px;
      color: var(--text-dim);
      padding: 4px;
      font-family: var(--font-mono);
    }}

    /* ── Usage badge ─────────────────────────────────────────── */
    .usage-badge {{
      font-size: 10px;
      font-family: var(--font-mono);
      color: var(--text-dim);
      background: var(--surface2);
      border-radius: 4px;
      padding: 2px 6px;
    }}

    /* ── Divider between turns ───────────────────────────────── */
    .turn + .turn {{
      border-top: 1px solid var(--border);
      padding-top: 8px;
    }}

    /* ── Compact summary ─────────────────────────────────────── */
    .compact-summary {{
      background: #1a1f2e;
      border: 1px solid #3a4060;
      border-radius: var(--radius);
      margin-bottom: 6px;
      overflow: hidden;
    }}
    .compact-summary-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 9px 14px;
      cursor: pointer;
      font-size: 12px;
      color: #7a8aaa;
      user-select: none;
    }}
    .compact-summary-header:hover {{ background: rgba(255,255,255,0.03); }}
    .compact-summary-body {{
      border-top: 1px solid #3a4060;
      padding: 12px 14px;
    }}
    .compact-summary-text {{
      font-size: 13px;
      color: var(--text-dim);
      line-height: 1.6;
    }}

    /* ── Compact boundary divider ────────────────────────────── */
    .compact-boundary {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 12px 0;
    }}
    .compact-boundary-line {{
      flex: 1;
      height: 1px;
      background: #3a4060;
    }}
    .compact-boundary-label {{
      font-size: 11px;
      color: #5a6a8a;
      font-family: var(--font-mono);
      white-space: nowrap;
    }}

    /* ── API error ───────────────────────────────────────────── */
    .api-error-block {{
      display: flex;
      align-items: center;
      gap: 10px;
      background: rgba(192,57,43,0.1);
      border: 1px solid rgba(192,57,43,0.4);
      border-radius: var(--radius);
      padding: 10px 14px;
      margin-bottom: 6px;
      font-size: 13px;
    }}
    .api-error-icon {{ font-size: 16px; }}
    .api-error-text {{ color: #e87070; font-family: var(--font-mono); }}

    /* ── Scrollbar ───────────────────────────────────────────── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
  </style>
</head>
<body>

<header>
  <h1>💬 {title}</h1>
  {'<span class="meta-pill">v' + escape(version) + '</span>' if version else ''}
  {'<span class="meta-pill">' + escape(git_branch) + '</span>' if git_branch and git_branch != 'HEAD' else ''}
  <div class="header-actions">
    <button onclick="expandAll()">Expand all</button>
    <button onclick="collapseAll()">Collapse all</button>
  </div>
</header>

<main>

  <div class="session-card">
    <div class="session-field">
      <span class="session-label">Session ID</span>
      <div class="session-id-row">
        <span class="session-value" title="{escape(session_id)}">{escape(session_id)}</span>
        <button class="copy-btn" onclick="copyText(this, '{escape(session_id)}')">📋</button>
      </div>
    </div>
    <div class="session-field">
      <span class="session-label">Working directory</span>
      <span class="session-value">{escape(cwd)}</span>
    </div>
    <div class="session-field">
      <span class="session-label">Started</span>
      <span class="session-value">{escape(start_ts)}</span>
    </div>
    <div class="session-field">
      <span class="session-label">Ended</span>
      <span class="session-value">{escape(end_ts)}</span>
    </div>
    <div class="session-field">
      <span class="session-label">Messages</span>
      <span class="session-value">{user_msgs} user / {asst_msgs} assistant</span>
    </div>
    <div class="session-field">
      <span class="session-label">Tool calls</span>
      <span class="session-value">{tool_calls}</span>
    </div>
    {(
      '<div class="session-field session-resume">'
      '<span class="session-label">Resume</span>'
      '<div class="session-id-row">'
      '<span class="session-value resume-cmd" title="' + escape(f"cd {cwd} && claude --resume {session_id}") + '">'
      + escape(f"cd {cwd} && claude --resume {session_id}") +
      '</span>'
      '<button class="copy-btn" onclick="copyText(this, \'' + escape(f"cd {cwd} && claude --resume {session_id}") + '\')">📋</button>'
      '</div></div>'
    ) if cwd and session_id else ''}
  </div>

  <div id="conversation">
{conversation_html}
  </div>

</main>

<script>
  function copyText(btn, text) {{
    navigator.clipboard.writeText(text).then(() => {{
      const orig = btn.textContent;
      btn.textContent = '✓';
      btn.style.color = '#5db870';
      setTimeout(() => {{ btn.textContent = orig; btn.style.color = ''; }}, 1500);
    }});
  }}

  function toggleNext(header) {{
    const body = header.nextElementSibling;
    const hint = header.querySelector('.toggle-hint');
    if (!body) return;
    body.classList.toggle('collapsed');
    if (hint) hint.classList.toggle('open');
  }}

  function expandAll() {{
    document.querySelectorAll('.collapsed').forEach(el => {{
      el.classList.remove('collapsed');
    }});
    document.querySelectorAll('.toggle-hint').forEach(el => {{
      el.classList.add('open');
    }});
  }}

  function collapseAll() {{
    document.querySelectorAll(
      '.thinking-body, .tool-call-body, .tool-result-body'
    ).forEach(el => {{
      el.classList.add('collapsed');
    }});
    document.querySelectorAll('.toggle-hint').forEach(el => {{
      el.classList.remove('open');
    }});
  }}
</script>

</body>
</html>
"""
    if out_path is not None:
        Path(out_path).write_text(html_content, encoding="utf-8")
    return html_content


def extract_meta(jsonl_path):
    """
    Read a JSONL file and return lightweight metadata for the index page.
    Avoids building the full HTML to stay fast across many files.
    """
    messages = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        return None

    session_id = ""
    cwd = ""
    git_branch = ""
    slug = ""
    version = ""
    first_user_text = ""
    user_msgs = 0
    asst_msgs = 0
    tool_calls = 0

    for m in messages:
        mtype = m.get("type")
        if mtype in ("user", "assistant"):
            session_id = session_id or m.get("sessionId", "")
            cwd = cwd or m.get("cwd", "")
            git_branch = git_branch or m.get("gitBranch", "")
            slug = slug or m.get("slug", "")
            version = version or m.get("version", "")

        if mtype == "user" and not m.get("isSidechain"):
            user_msgs += 1
            if not first_user_text:
                content = m.get("message", {}).get("content", "")
                if isinstance(content, str):
                    first_user_text = content
                elif isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            first_user_text = item.get("text", "")
                            break

        if mtype == "assistant" and not m.get("isSidechain"):
            asst_msgs += 1
            for item in m.get("message", {}).get("content", []):
                if item.get("type") == "tool_use":
                    tool_calls += 1

    timestamps = [m.get("timestamp") for m in messages if m.get("timestamp")]
    start_ts = min(timestamps) if timestamps else ""
    end_ts = max(timestamps) if timestamps else ""

    # Duration
    duration = ""
    if start_ts and end_ts:
        try:
            t0 = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
            duration = fmt_ms(int((t1 - t0).total_seconds() * 1000))
        except Exception:
            pass

    return {
        "session_id": session_id,
        "cwd": cwd,
        "git_branch": git_branch,
        "slug": slug,
        "version": version,
        "first_user_text": first_user_text,
        "user_msgs": user_msgs,
        "asst_msgs": asst_msgs,
        "tool_calls": tool_calls,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration": duration,
        "filename": jsonl_path.name,
        # html_filename and project are set by process_directory once it knows
        # the root, so they start as plain defaults here.
        "html_filename": jsonl_path.stem + ".html",
        "project": "",
    }


def fmt_date(ts_str):
    """Format ISO timestamp to a readable date+time string."""
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts_str


def generate_index_html(sessions):
    """Generate an index page listing all sessions."""
    # Sort newest first
    sessions = sorted(sessions, key=lambda s: s.get("start_ts", ""), reverse=True)

    cards = []
    for s in sessions:
        title = s["slug"] or s["session_id"] or s["filename"]
        preview = s["first_user_text"][:200].replace("\n", " ")
        cwd_short = s["cwd"].replace("\\", "/").split("/")[-1] if s["cwd"] else ""
        branch_pill = (
            f'<span class="idx-pill branch-pill">{escape(s["git_branch"])}</span>'
            if s["git_branch"] and s["git_branch"] != "HEAD"
            else ""
        )

        project_pill = (
            f'<span class="idx-pill project-pill">{escape(s["project"])}</span>'
            if s.get("project") else ""
        )

        cards.append(f"""
  <a class="session-card" href="{escape(s['html_filename'])}">
    <div class="card-title">{escape(title)}</div>
    <div class="card-preview">{escape(preview)}</div>
    <div class="card-footer">
      <span class="idx-pill date-pill">{escape(fmt_date(s['start_ts']))}</span>
      {project_pill}
      {'<span class="idx-pill cwd-pill">' + escape(cwd_short) + '</span>' if cwd_short else ''}
      {branch_pill}
      <span class="idx-pill stat-pill">{s['user_msgs']} msgs</span>
      <span class="idx-pill stat-pill">{s['tool_calls']} tool calls</span>
      {'<span class="idx-pill dur-pill">' + escape(s['duration']) + '</span>' if s['duration'] else ''}
      {'<span class="idx-pill id-pill" title="' + escape(s['session_id']) + '">' + escape(s['session_id'][:8]) + '</span>' if s['session_id'] else ''}
    </div>
  </a>""")

    cards_html = "\n".join(cards)
    count = len(sessions)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Claude Sessions</title>
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --surface2: #22263a;
      --border: #2e3352;
      --border-hover: #4a5280;
      --text: #e2e4ed;
      --text-dim: #8b90a8;
      --accent: #7c6fef;
      --radius: 8px;
      --font-mono: "JetBrains Mono", "Fira Code", "Consolas", monospace;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: var(--font-sans);
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.6;
    }}

    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 20px 24px;
      position: sticky;
      top: 0;
      z-index: 100;
      display: flex;
      align-items: center;
      gap: 16px;
    }}

    header h1 {{ font-size: 18px; font-weight: 600; }}
    .count {{ color: var(--text-dim); font-size: 13px; }}

    #search {{
      margin-left: auto;
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 12px;
      color: var(--text);
      font-size: 13px;
      width: 260px;
      outline: none;
    }}
    #search:focus {{ border-color: var(--accent); }}
    #search::placeholder {{ color: var(--text-dim); }}

    main {{
      max-width: 900px;
      margin: 0 auto;
      padding: 24px 16px 80px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}

    .session-card {{
      display: block;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 20px;
      text-decoration: none;
      color: inherit;
      transition: border-color 0.15s, background 0.15s;
    }}
    .session-card:hover {{
      border-color: var(--border-hover);
      background: var(--surface2);
    }}

    .card-title {{
      font-size: 14px;
      font-weight: 600;
      font-family: var(--font-mono);
      color: var(--text);
      margin-bottom: 6px;
    }}

    .card-preview {{
      font-size: 13px;
      color: var(--text-dim);
      margin-bottom: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .card-footer {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }}

    .idx-pill {{
      font-size: 11px;
      font-family: var(--font-mono);
      border-radius: 20px;
      padding: 2px 9px;
      white-space: nowrap;
    }}

    .date-pill  {{ background: rgba(124,111,239,0.15); color: #a99af5; }}
    .cwd-pill   {{ background: rgba(74,157,232,0.12); color: #6aaee0; }}
    .branch-pill {{ background: rgba(93,184,112,0.12); color: #7ecf8e; }}
    .stat-pill  {{ background: var(--surface2); color: var(--text-dim); border: 1px solid var(--border); }}
    .dur-pill     {{ background: rgba(192,133,90,0.12); color: #d4a574; }}
    .project-pill {{ background: rgba(239,180,80,0.12); color: #c9a84c; }}
    .id-pill      {{ background: transparent; color: #4a5070; border: 1px solid #2a2f45; margin-left: auto; }}

    .no-results {{
      text-align: center;
      color: var(--text-dim);
      padding: 60px 0;
      font-size: 14px;
    }}

    ::-webkit-scrollbar {{ width: 6px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
  </style>
</head>
<body>

<header>
  <h1>💬 Claude Sessions</h1>
  <span class="count">{count} session{"s" if count != 1 else ""}</span>
  <input id="search" type="search" placeholder="Filter sessions..." oninput="filterCards(this.value)">
</header>

<main id="cards">
{cards_html}
  <div class="no-results" id="no-results" style="display:none">No sessions match your filter.</div>
</main>

<script>
  function filterCards(q) {{
    q = q.toLowerCase();
    let visible = 0;
    document.querySelectorAll('.session-card').forEach(card => {{
      const text = card.textContent.toLowerCase();
      const show = !q || text.includes(q);
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('no-results').style.display = visible === 0 ? '' : 'none';
  }}
</script>

</body>
</html>
"""


def process_directory(dir_path, out_path=None):
    """
    Generate index.html and per-session HTMLs from a directory tree of JSONL files.

    dir_path : root to scan recursively for *.jsonl
    out_path : where to write output (default: same as dir_path).
               The subdirectory structure is mirrored, e.g.
               dir_path/projectA/abc.jsonl → out_path/projectA/abc.html
    """
    if out_path is None:
        out_path = dir_path

    jsonl_files = sorted(dir_path.rglob("*.jsonl"))
    if not jsonl_files:
        print(f"No .jsonl files found under {dir_path}")
        sys.exit(1)

    print(f"Found {len(jsonl_files)} JSONL file(s) under {dir_path}")

    sessions = []
    for jsonl_path in jsonl_files:
        # Relative path from the root, e.g. "projectA/abc.jsonl"
        rel = jsonl_path.relative_to(dir_path)
        project = rel.parts[0] if len(rel.parts) > 1 else ""
        html_rel = rel.with_suffix(".html")   # e.g. "projectA/abc.html"

        print(f"  {rel}")
        meta = extract_meta(jsonl_path)
        if meta is None:
            print(f"    Skipping (could not read)")
            continue

        meta["project"] = project
        meta["html_filename"] = html_rel.as_posix()  # forward-slash for URLs

        html_content = generate_html(jsonl_path)
        dest = out_path / html_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html_content, encoding="utf-8")

        sessions.append(meta)

    index_html = generate_index_html(sessions)
    (out_path / "index.html").write_text(index_html, encoding="utf-8")
    print(f"\nIndex written to {out_path / 'index.html'}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python generator.py <session.jsonl> [output.html]")
        print("  python generator.py <sessions-dir/> [output-dir/]")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Error: {target} not found")
        sys.exit(1)

    if target.is_dir():
        out = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
        process_directory(target, out)
    else:
        out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else target.with_suffix(".html")
        print(f"Reading {target}...")
        generate_html(target, out_path)
        print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
