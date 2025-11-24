#!/usr/bin/env python3
"""
Artifact produced hook for Claude Code.
Logs file/output artifacts created during agent execution.
"""
import sys
import os
import json
import hashlib

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


def compute_file_hash(filepath: str) -> str:
    """Compute SHA256 hash of file."""
    try:
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return f"sha256:{sha256.hexdigest()}"
    except Exception:
        return "sha256:unknown"


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
        print(f"[artifact_produced] HTTP error: {e}", file=sys.stderr)


def append_local_log(log_dir: Path, event: dict):
    """Append event to daily JSONL log."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = utc_now_iso()[:10].replace('-', '')
        log_file = log_dir / f"events-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[artifact_produced] file log error: {e}", file=sys.stderr)


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[artifact_produced] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    run_id = get_run_id_from_env_or_generate()
    
    # Extract artifact info
    artifact_path = input_data.get("artifact_path", "")
    artifact_type = input_data.get("artifact_type", "file")
    
    if not artifact_path:
        sys.exit(0)
    
    # Compute hash and size
    file_hash = compute_file_hash(artifact_path)
    try:
        size_bytes = os.path.getsize(artifact_path)
    except Exception:
        size_bytes = 0
    
    # Build artifact reference
    artifact_ref = {
        "path": artifact_path,
        "type": artifact_type,
        "hash": file_hash,
        "size_bytes": size_bytes,
        "produced_at": utc_now_iso()
    }
    
    # Build event
    event = build_event_envelope(
        event_type="artifact",
        session_id=session_id,
        run_id=run_id,
        level="info",
        hook_event_name="PostToolUse",
        msg=f"Artifact produced: {Path(artifact_path).name}",
        data={
            "artifact_metadata": artifact_ref,
            "producing_tool": input_data.get("tool_name"),
            "task_id": input_data.get("task_id")
        },
        worker_id=input_data.get("worker_id"),
        task_id=input_data.get("task_id"),
        artifact_refs=[artifact_ref],
        cwd=input_data.get("cwd"),
        redaction_mode=os.getenv("ZO_REDACTION_MODE", "strict")
    )

    # Log locally
    log_root = os.getenv("ZO_EVENT_LOG_DIR", os.path.expanduser("~/.zo/claude-events"))
    append_local_log(Path(log_root), event)

    # Send to bridge
    if endpoint := os.getenv("ZO_EVENT_ENDPOINT"):
        send_http_event(endpoint, event)

    sys.exit(0)


if __name__ == "__main__":
    main()
