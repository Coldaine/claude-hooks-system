#!/usr/bin/env python3
"""
Error event hook for Claude Code.
Captures tool failures and hook errors for debugging.
"""
import sys
import os
import json
import traceback

try:
    from event_utils import (
        build_event_envelope,
        get_run_id_from_env_or_generate,
        utc_now_iso
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from event_utils import (
        build_event_envelope,
        get_run_id_from_env_or_generate,
        utc_now_iso
    )

try:
    import urllib.request
except ImportError:
    urllib = None

from pathlib import Path


def send_http_event(endpoint: str, event: dict):
    """POST event to HTTP endpoint."""
    if not endpoint or not urllib:
        return

    data = json.dumps(event).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key := os.getenv("ZO_API_KEY"):
        headers["X-API-Key"] = api_key
    
    try:
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as _:
            pass
    except Exception as e:
        print(f"[error_event] HTTP error: {e}", file=sys.stderr)


def append_local_log(log_dir: Path, event: dict):
    """Append event to daily JSONL log."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = utc_now_iso()[:10].replace('-', '')
        log_file = log_dir / f"events-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[error_event] file log error: {e}", file=sys.stderr)


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[error_event] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    run_id = get_run_id_from_env_or_generate()
    
    # Extract error details
    error_message = input_data.get("error_message", "Unknown error")
    error_type = input_data.get("error_type", "ToolError")
    stack_trace = input_data.get("stack_trace", "")
    
    # Build error detail
    error_detail = {
        "type": error_type,
        "message": error_message[:500],  # Truncate
        "stack_trace": stack_trace[:2000] if stack_trace else None,
        "tool_name": input_data.get("tool_name"),
        "tool_use_id": input_data.get("tool_use_id")
    }
    
    # Build event
    event = build_event_envelope(
        event_type="error",
        session_id=session_id,
        run_id=run_id,
        level="error",
        hook_event_name=input_data.get("hook_event_name", "PostToolUse"),
        msg=f"Error: {error_message[:200]}",
        data={
            "error_context": input_data.get("context", {}),
            "recovery_attempted": input_data.get("recovery_attempted", False)
        },
        tool_name=input_data.get("tool_name"),
        tool_use_id=input_data.get("tool_use_id"),
        worker_id=input_data.get("worker_id"),
        task_id=input_data.get("task_id"),
        error_detail=error_detail,
        cwd=input_data.get("cwd"),
        redaction_mode=os.getenv("ZO_REDACTION_MODE", "strict")
    )

    # Log locally
    log_root = os.getenv("ZO_EVENT_LOG_DIR", os.path.expanduser("~/.zo/claude-events"))
    append_local_log(Path(log_root), event)

    # Send to bridge
    if endpoint := os.getenv("ZO_EVENT_ENDPOINT"):
        send_http_event(endpoint, event)

    # Output context injection
    output = {
        "hookSpecificOutput": {
            "hookEventName": input_data.get("hook_event_name", "PostToolUse"),
            "additionalContext": (
                f"[error] {error_type}: {error_message[:100]} | event_id={event['event_id'][:8]}..."
            )
        }
    }
    print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
