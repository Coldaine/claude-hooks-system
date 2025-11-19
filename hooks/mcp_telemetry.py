#!/usr/bin/env python3
import sys, os, json, datetime
from pathlib import Path

def main():
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        print(f"[mcp_telemetry] bad JSON: {e}", file=sys.stderr)
        sys.exit(1)

    tool_name = data.get("tool_name", "")
    if not tool_name.startswith("mcp_"):
        # Nothing to do
        sys.exit(0)

    now = datetime.datetime.utcnow().isoformat() + "Z"
    session_id = data.get("session_id", "")
    log_dir = Path(os.getenv("MCP_TELEMETRY_LOG_DIR", os.path.expanduser("~/.zo/mcp-events")))
    log_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.datetime.utcnow().strftime("%Y%m%d")
    log_file = log_dir / f"mcp-{day}.jsonl"

    event = {
        "ts": now,
        "session_id": session_id,
        "tool_name": tool_name,
        "hook_event_name": data.get("hook_event_name"),
        "payload": data
    }

    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    # no structured output, just logging
    sys.exit(0)

if __name__ == "__main__":
    main()

