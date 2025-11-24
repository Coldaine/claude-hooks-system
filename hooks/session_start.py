#!/usr/bin/env python3
"""
Session start hook for Claude Code.
Initializes run context and emits session_start event.
"""
import sys
import os
import json

# Import shared event utilities
try:
    from event_utils import (
        build_event_envelope,
        generate_run_id,
        utc_now_iso
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from event_utils import (
        build_event_envelope,
        generate_run_id,
        utc_now_iso
    )

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None

from pathlib import Path


def send_http_event(endpoint: str, event: dict, max_retries: int = 3):
    """POST event to HTTP endpoint with retry."""
    if not endpoint or not urllib:
        return

    data = json.dumps(event).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key := os.getenv("ZO_API_KEY"):
        headers["X-API-Key"] = api_key
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            timeout = 2.0 * (2 ** attempt)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status in (200, 201, 202):
                    return
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[session_start] HTTP error: {e}", file=sys.stderr)


def append_local_log(log_dir: Path, event: dict):
    """Append event to daily JSONL log."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = utc_now_iso()[:10].replace('-', '')
        log_file = log_dir / f"events-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[session_start] file log error: {e}", file=sys.stderr)


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[session_start] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    run_id = generate_run_id()
    
    # Persist run_id for duration of session (workers inherit this)
    os.environ["CLAUDE_RUN_ID"] = run_id
    
    # Build event
    event = build_event_envelope(
        event_type="session_start",
        session_id=session_id,
        run_id=run_id,
        level="info",
        hook_event_name="SessionStart",
        msg=f"Session started: {session_id}",
        data={
            "user": os.getenv("USER") or os.getenv("USERNAME"),
            "claude_version": input_data.get("claude_version"),
            "workspace": input_data.get("cwd")
        },
        agent_role="conductor",
        cwd=input_data.get("cwd"),
        redaction_mode=os.getenv("ZO_REDACTION_MODE", "strict")
    )

    # Log locally
    log_root = os.getenv("ZO_EVENT_LOG_DIR", os.path.expanduser("~/.zo/claude-events"))
    append_local_log(Path(log_root), event)

    # Send to bridge (hardcoded endpoint)
    endpoint = os.getenv("ZO_EVENT_ENDPOINT", "http://localhost:9000/ingest")
    if endpoint:
        send_http_event(endpoint, event)

    # Output context injection
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"[session] run_id={run_id} | "
                f"Events → {endpoint or 'local-only'}"
            )
        }
    }
    print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
