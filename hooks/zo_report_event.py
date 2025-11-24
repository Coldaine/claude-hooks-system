#!/usr/bin/env python3
"""
General event reporter for Claude Code hooks.
Logs lifecycle/tool events locally and POSTs to HTTP endpoint (e.g. Chroma bridge).
Uses canonical schema v1.0 via event_utils module.
"""
import sys
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

# Import shared event utilities
try:
    from event_utils import (
        build_event_envelope,
        get_run_id_from_env_or_generate,
        utc_now_iso
    )
except ImportError:
    # Fallback if event_utils not in path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from event_utils import (
        build_event_envelope,
        get_run_id_from_env_or_generate,
        utc_now_iso
    )

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None  # Very unlikely, but be defensive


def safe_get(d: Dict[str, Any], key: str, default=None):
    return d.get(key, default)


def send_http_event(endpoint: str, event: Dict[str, Any], max_retries: int = 3):
    """
    POST event to HTTP endpoint with exponential backoff retry.
    
    Args:
        endpoint: HTTP(S) URL
        event: Event envelope to send
        max_retries: Maximum retry attempts
    """
    if not endpoint or not urllib:
        return

    data = json.dumps(event).encode("utf-8")
    
    # Add API key if configured
    headers = {"Content-Type": "application/json"}
    if api_key := os.getenv("ZO_API_KEY"):
        headers["X-API-Key"] = api_key
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers=headers,
                method="POST",
            )
            timeout = 2.0 * (2 ** attempt)  # Exponential backoff: 2s, 4s, 8s
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status in (200, 201, 202):
                    return  # Success
        except urllib.error.HTTPError as e:
            if e.code == 409:  # Duplicate (idempotent)
                return
            print(f"[zo_report_event] HTTP {e.code}: {e.reason} (attempt {attempt+1}/{max_retries})", file=sys.stderr)
        except Exception as e:
            print(f"[zo_report_event] HTTP error: {e} (attempt {attempt+1}/{max_retries})", file=sys.stderr)
        
        if attempt < max_retries - 1:
            import time
            time.sleep(0.5 * (2 ** attempt))  # Sleep before retry: 0.5s, 1s, 2s


def append_local_log(log_dir: Path, event: Dict[str, Any]):
    """Append event to daily JSONL log file."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = utc_now_iso()[:10].replace('-', '')  # YYYYMMDD
        log_file = log_dir / f"events-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[zo_report_event] file log error: {e}", file=sys.stderr)


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[zo_report_event] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract hook context
    hook_event = input_data.get("hook_event_name", "")
    session_id = input_data.get("session_id", "unknown")
    run_id = get_run_id_from_env_or_generate()
    cwd = input_data.get("cwd", "")
    
    # Map hook event to event_type
    event_type_map = {
        "UserPromptSubmit": "progress",
        "PostToolUse": "progress",
        "SessionStart": "session_start",
        "SessionEnd": "session_end",
        "Stop": "session_end",
        "PreToolUse": "progress"
    }
    event_type = event_type_map.get(hook_event, "progress")
    
    # Determine level
    level = "info"
    if error_data := input_data.get("error"):
        level = "error"
        event_type = "error"
    
    # Build enriched data payload
    data_payload = {
        "hook_event_name": hook_event,
        "transcript_path": input_data.get("transcript_path", ""),
        "permission_mode": input_data.get("permission_mode"),
        "notification_type": input_data.get("notification_type"),
        "stop_hook_active": input_data.get("stop_hook_active"),
        "prompt": input_data.get("prompt", "")[:1000] if input_data.get("prompt") else None  # Truncate
    }
    
    # Build message summary
    msg = f"{hook_event} event"
    if tool_name := input_data.get("tool_name"):
        msg = f"{hook_event}: {tool_name}"
    
    # Build canonical event envelope using event_utils
    event = build_event_envelope(
        event_type=event_type,
        session_id=session_id,
        run_id=run_id,
        level=level,
        hook_event_name=hook_event,
        msg=msg,
        data=data_payload,
        tool_name=input_data.get("tool_name"),
        tool_use_id=input_data.get("tool_use_id"),
        cwd=cwd,
        redaction_mode=os.getenv("ZO_REDACTION_MODE", "strict")
    )

    # 1) Local JSONL log
    log_root = os.getenv("ZO_EVENT_LOG_DIR", os.path.expanduser("~/.zo/claude-events"))
    append_local_log(Path(log_root), event)

    # 2) HTTP endpoint (Chroma bridge - hardcoded default)
    endpoint = os.getenv("ZO_EVENT_ENDPOINT", "http://localhost:9000/ingest")
    if endpoint:
        send_http_event(endpoint, event)

    # 3) Optional structured output back to Claude Code
    output = None

    # Inject contextual status lines for selected hook events
    if hook_event == "UserPromptSubmit":
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    f"[zo-log] Session {session_id} prompt logged | "
                    f"run_id={run_id[:8]}... | event_id={event['event_id'][:8]}..."
                )
            }
        }

    elif hook_event == "PostToolUse":
        tool_name = input_data.get("tool_name", "")
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"[zo-log] Tool '{tool_name}' logged | "
                    f"run_id={run_id[:8]}... | event_id={event['event_id'][:8]}..."
                )
            }
        }

    elif hook_event == "SessionStart":
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    f"[zo-log] Session started | run_id={run_id} | "
                    f"Events streaming to {endpoint or 'local-only'}"
                )
            }
        }

    if output is not None:
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
