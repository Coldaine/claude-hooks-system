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
        utc_now_iso,
        send_event_to_chroma
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from event_utils import (
        build_event_envelope,
        generate_run_id,
        utc_now_iso,
        send_event_to_chroma
    )

from pathlib import Path


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

    # Log locally (always, as fallback)
    log_root = os.getenv("ZO_EVENT_LOG_DIR", os.path.expanduser("~/.zo/claude-events"))
    append_local_log(Path(log_root), event)

    # Send directly to Chroma Cloud
    chroma_ok = send_event_to_chroma(event)
    destination = "chroma-cloud" if chroma_ok else "local-only"

    # Output context injection
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"[session] run_id={run_id} | "
                f"Events → {destination}"
            )
        }
    }
    print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
