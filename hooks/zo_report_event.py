#!/usr/bin/env python3
import sys
import os
import json
import datetime
from pathlib import Path
from typing import Any, Dict

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None  # Very unlikely, but be defensive


def safe_get(d: Dict[str, Any], key: str, default=None):
    return d.get(key, default)


def send_http_event(endpoint: str, event: Dict[str, Any]):
    if not endpoint or not urllib:
        return

    data = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as _:
            pass
    except Exception as e:
        # Non-blocking: log but don't fail the hook
        print(f"[zo_report_event] HTTP error: {e}", file=sys.stderr)


def append_local_log(log_dir: Path, event: Dict[str, Any]):
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.datetime.utcnow().strftime("%Y%m%d")
        log_file = log_dir / f"events-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[zo_report_event] file log error: {e}", file=sys.stderr)


def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[zo_report_event] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    hook_event = safe_get(input_data, "hook_event_name", "")
    session_id = safe_get(input_data, "session_id", "")
    cwd = safe_get(input_data, "cwd", "")
    transcript_path = safe_get(input_data, "transcript_path", "")

    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Build a compact event envelope
    event = {
        "ts": now,
        "hook_event_name": hook_event,
        "session_id": session_id,
        "cwd": cwd,
        "transcript_path": transcript_path,
        "tool_name": safe_get(input_data, "tool_name"),
        "tool_use_id": safe_get(input_data, "tool_use_id"),
        "permission_mode": safe_get(input_data, "permission_mode"),
        "prompt": safe_get(input_data, "prompt"),
        "notification_type": safe_get(input_data, "notification_type"),
        "stop_hook_active": safe_get(input_data, "stop_hook_active"),
        "source": {
            "remote": (os.getenv("CLAUDE_CODE_REMOTE") == "true"),
            "project_dir": os.getenv("CLAUDE_PROJECT_DIR"),
            "host": os.uname().nodename if hasattr(os, "uname") else None,
        },
        "payload": input_data,  # full raw payload for later ingestion
    }

    # 1) Local JSONL log
    log_root = os.getenv("ZO_EVENT_LOG_DIR", os.path.expanduser("~/.zo/claude-events"))
    append_local_log(Path(log_root), event)

    # 2) Optional HTTP endpoint (Zo/computer, Chroma mock, etc.)
    endpoint = os.getenv("ZO_EVENT_ENDPOINT", "")  # e.g. http://localhost:9000/events
    if endpoint:
        send_http_event(endpoint, event)

    # 3) Optional structured output back to Claude Code
    output = None

    # For UserPromptSubmit: inject a tiny status line as additional context
    if hook_event == "UserPromptSubmit":
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    f"[zo-log] Session {session_id or 'unknown'} "
                    f"prompt logged at {now} (cwd={cwd})."
                )
            }
        }

    # For PostToolUse: let Claude know we logged this tool call
    elif hook_event == "PostToolUse":
        tool_name = safe_get(input_data, "tool_name", "")
        tool_use_id = safe_get(input_data, "tool_use_id", "")
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"[zo-log] Logged tool '{tool_name}' "
                    f"use_id={tool_use_id or 'n/a'} for session {session_id or 'unknown'}."
                )
            }
        }

    # For SessionStart: inject a one-line "session opened" banner into context
    elif hook_event == "SessionStart":
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    f"[zo-log] Session {session_id or 'unknown'} started at {now} "
                    f"(cwd={cwd}). Events are being streamed to Zo/Chroma."
                )
            }
        }

    # For Stop / SessionEnd we just log; we don't block or change behavior.
    # output = None is fine.

    if output is not None:
        print(json.dumps(output))

    # exit 0 -> no blocking, JSON (if any) is processed normally
    sys.exit(0)


if __name__ == "__main__":
    main()

