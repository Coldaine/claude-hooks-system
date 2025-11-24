#!/usr/bin/env python3
"""
Worker spawn hook for Claude Code.
Emits worker_spawn event when Conductor creates a new worker agent.
"""
import sys
import os
import json

try:
    from event_utils import (
        build_event_envelope,
        get_run_id_from_env_or_generate,
        generate_event_id,
        utc_now_iso
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from event_utils import (
        build_event_envelope,
        get_run_id_from_env_or_generate,
        generate_event_id,
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
        print(f"[worker_spawn] HTTP error: {e}", file=sys.stderr)


def append_local_log(log_dir: Path, event: dict):
    """Append event to daily JSONL log."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = utc_now_iso()[:10].replace('-', '')
        log_file = log_dir / f"events-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[worker_spawn] file log error: {e}", file=sys.stderr)


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[worker_spawn] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    run_id = get_run_id_from_env_or_generate()
    
    # Generate worker_id
    worker_id = f"worker_{generate_event_id()[:8]}"
    
    # Extract task assignment from tool parameters
    task_data = input_data.get("task", {})
    task_id = task_data.get("task_id", "unknown")
    task_description = task_data.get("description", "")
    
    # Build event
    event = build_event_envelope(
        event_type="worker_spawn",
        session_id=session_id,
        run_id=run_id,
        level="info",
        hook_event_name="PostToolUse",
        msg=f"Spawned worker {worker_id} for task {task_id}",
        data={
            "task_id": task_id,
            "task_description": task_description,
            "worker_config": task_data.get("config", {}),
            "assigned_tools": task_data.get("tools", [])
        },
        agent_role="conductor",
        worker_id=worker_id,
        task_id=task_id,
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
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"[worker] Spawned {worker_id} for {task_id} | run_id={run_id[:8]}..."
            )
        }
    }
    print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
