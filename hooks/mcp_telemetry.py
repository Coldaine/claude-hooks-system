#!/usr/bin/env python3
"""
MCP tool telemetry hook for Claude Code.
Captures tool invocations for MCP-prefixed tools and logs them.
Uses canonical schema v1.0 via event_utils module.
"""
import sys
import os
import json
from pathlib import Path

# Import shared event utilities
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


def append_mcp_log(log_dir: Path, event: dict):
    """Append MCP tool event to daily JSONL log."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = utc_now_iso()[:10].replace('-', '')  # YYYYMMDD
        log_file = log_dir / f"mcp-{day}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[mcp_telemetry] file log error: {e}", file=sys.stderr)


def main():
    """Main hook entry point for MCP tool telemetry."""
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(f"[mcp_telemetry] invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    tool_name = input_data.get("tool_name", "")
    
    # Early exit if not MCP tool
    if not tool_name.startswith("mcp_"):
        sys.exit(0)

    # Extract context
    session_id = input_data.get("session_id", "unknown")
    run_id = get_run_id_from_env_or_generate()
    hook_event = input_data.get("hook_event_name", "PostToolUse")
    
    # Build data payload with tool parameters
    data_payload = {
        "tool_parameters": input_data.get("tool_parameters", {}),
        "tool_result": str(input_data.get("tool_result", ""))[:500] if input_data.get("tool_result") else None,  # Truncate
        "permission_mode": input_data.get("permission_mode"),
        "cwd": input_data.get("cwd", "")
    }
    
    # Build message
    msg = f"MCP tool invocation: {tool_name}"
    
    # Build canonical event envelope
    event = build_event_envelope(
        event_type="tool_invocation",
        session_id=session_id,
        run_id=run_id,
        level="info",
        hook_event_name=hook_event,
        msg=msg,
        data=data_payload,
        tool_name=tool_name,
        tool_use_id=input_data.get("tool_use_id"),
        cwd=input_data.get("cwd"),
        redaction_mode=os.getenv("ZO_REDACTION_MODE", "strict")
    )

    # Append to MCP-specific log
    log_root = os.getenv("MCP_TELEMETRY_LOG_DIR", os.path.expanduser("~/.zo/mcp-events"))
    append_mcp_log(Path(log_root), event)

    sys.exit(0)

if __name__ == "__main__":
    main()

