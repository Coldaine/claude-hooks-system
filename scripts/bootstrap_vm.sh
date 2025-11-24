#!/usr/bin/env bash
# Bootstrap Claude hook utilities on a remote (typically Linux) VM.
# Copies the Python hooks plus helper wrappers into a target directory and
# writes an .env file that points at the central Chroma bridge.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap_vm.sh [options]

Options:
  -d, --install-dir PATH   Directory that will hold hooks/bin (default: /opt/claude-hooks)
  -e, --endpoint URL       HTTP(S) endpoint for the central bridge (default: $ZO_EVENT_ENDPOINT or http://localhost:9000/ingest)
  -l, --log-dir PATH       Directory for JSONL fallbacks (default: /var/log/claude-events)
  -p, --project-id NAME    Project label stored in events (default: hostname)
  -k, --api-key KEY        Optional API key sent as X-API-Key
      --python PATH        Python interpreter to use (default: python3 on PATH)
  -h, --help               Show this message

Example:
  ./scripts/bootstrap_vm.sh -d /opt/claude-hooks -e https://bridge.example.com/ingest \
      -p vm-worker-01 -k supersecret
EOF
}

INSTALL_DIR=${INSTALL_DIR:-/opt/claude-hooks}
BRIDGE_URL=${BRIDGE_URL:-${ZO_EVENT_ENDPOINT:-http://localhost:9000/ingest}}
LOG_DIR=${LOG_DIR:-/var/log/claude-events}
PROJECT_ID=${PROJECT_ID:-$(hostname 2>/dev/null || echo "claude-agent")}
API_KEY=${ZO_API_KEY:-}
PYTHON_BIN=${PYTHON_BIN:-python3}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--install-dir)
      INSTALL_DIR=$2
      shift 2
      ;;
    -e|--endpoint)
      BRIDGE_URL=$2
      shift 2
      ;;
    -l|--log-dir)
      LOG_DIR=$2
      shift 2
      ;;
    -p|--project-id)
      PROJECT_ID=$2
      shift 2
      ;;
    -k|--api-key)
      API_KEY=$2
      shift 2
      ;;
    --python)
      PYTHON_BIN=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_SRC="$ROOT_DIR/hooks"

mkdir -p "$INSTALL_DIR/hooks" "$INSTALL_DIR/bin" "$LOG_DIR"

copy_hook() {
  local name=$1
  install -m 644 "$HOOK_SRC/${name}.py" "$INSTALL_DIR/hooks/${name}.py"
}

HOOKS=(zo_report_event mcp_telemetry session_start worker_spawn artifact_produced error_event)

# Shared utility module
copy_hook "event_utils"

for hook in "${HOOKS[@]}"; do
  copy_hook "$hook"
done

ENV_FILE="$INSTALL_DIR/.env"
{
  echo "ZO_EVENT_ENDPOINT=${BRIDGE_URL}"
  echo "ZO_EVENT_LOG_DIR=${LOG_DIR}"
  echo "CLAUDE_CODE_REMOTE=true"
  echo "CLAUDE_PROJECT_DIR=${PROJECT_ID}"
  echo "PYTHON_BIN=${PYTHON_BIN}"
  if [[ -n "${API_KEY}" ]]; then
    echo "ZO_API_KEY=${API_KEY}"
  fi
} > "$ENV_FILE"

# Wrapper scripts make it easy to reference hooks from Claude's hook config.
create_wrapper() {
  local name=$1
  local target="$INSTALL_DIR/bin/${name}"
  cat <<EOF > "$target"
#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="\$ROOT_DIR/.env"
if [[ -f "\$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "\$ENV_FILE"
  set +a
fi
PY_BIN="\${PYTHON_BIN:-python3}"
exec "\$PY_BIN" "\$ROOT_DIR/hooks/${name}.py"
EOF
  chmod +x "$target"
}

for hook in "${HOOKS[@]}"; do
  create_wrapper "$hook"
done

cat <<EOF
✓ Hooks installed into: $INSTALL_DIR
   - Python scripts: $INSTALL_DIR/hooks
   - Wrapper commands: $INSTALL_DIR/bin
   - Local log dir: $LOG_DIR
   - Bridge endpoint: $BRIDGE_URL

Next steps:
  1. Ensure the central Chroma bridge is reachable from this VM.
  2. Point Claude Code hooks at the wrapper commands, e.g.:
       UserPromptSubmit/PostToolUse → $INSTALL_DIR/bin/zo_report_event
       SessionStart                 → $INSTALL_DIR/bin/session_start
       Error reporting              → $INSTALL_DIR/bin/error_event
       MCP telemetry                → $INSTALL_DIR/bin/mcp_telemetry
  3. Export CLAUDE_RUN_ID in orchestrator processes if you want workers to
     share the same run identifier.

Re-run this script any time you need to update the hooks on a VM.
EOF
