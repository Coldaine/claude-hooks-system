#!/bin/bash
# Start the Chroma Bridge Server for Claude hooks system

set -e

BRIDGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$BRIDGE_DIR/bridge.pid"
LOG_FILE="$BRIDGE_DIR/bridge.log"

stop_bridge() {
    echo "Stopping Chroma Bridge Server..."

    if [[ -f "$PID_FILE" ]]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "[OK] Bridge server stopped (PID: $pid)"
        else
            echo "[WARN] No process found with PID $pid"
        fi
        rm "$PID_FILE"
    else
        echo "[INFO] Bridge server not running (no PID file)"
    fi
}

test_bridge_running() {
    if [[ -f "$PID_FILE" ]]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "[INFO] Bridge already running (PID: $pid)"

            # Test health endpoint
            if health=$(curl -s http://localhost:9000/health 2>/dev/null); then
                echo "[OK] Bridge is healthy"
                echo "     $health"
                return 0
            else
                echo "[WARN] Bridge process exists but not responding"
                return 1
            fi
        fi
    fi
    return 1
}

# Handle -stop flag
if [[ "$1" == "-stop" ]] || [[ "$1" == "--stop" ]]; then
    stop_bridge
    exit 0
fi

# Check if already running
if test_bridge_running; then
    echo ""
    echo "Bridge server is already running and healthy."
    echo "Use -stop to stop it, or check logs at: $LOG_FILE"
    exit 0
fi

echo "============================================================"
echo "Starting Chroma Bridge Server"
echo "============================================================"

# Check for .env file
ENV_FILE="$BRIDGE_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[ERROR] .env file not found at: $ENV_FILE"
    echo "        Please create .env with Chroma Cloud credentials"
    echo ""
    echo "Example .env:"
    echo "  USE_CHROMA_CLOUD=true"
    echo "  CHROMA_API_KEY=ck-..."
    echo "  CHROMA_TENANT=your-tenant-id"
    echo "  CHROMA_DATABASE=ClaudeCallHome"
    exit 1
fi

# Check Python
if ! python3 --version &>/dev/null; then
    echo "[ERROR] Python 3 not found"
    echo "        Install Python 3.8+ and ensure it's in PATH"
    exit 1
fi

echo "[OK] Python found: $(python3 --version)"

# Check dependencies
echo "Checking dependencies..."
missing_deps=()
for dep in chromadb python-dotenv; do
    if ! python3 -c "import $dep" 2>/dev/null; then
        missing_deps+=("$dep")
    fi
done

if [[ ${#missing_deps[@]} -gt 0 ]]; then
    echo "[WARN] Missing dependencies: ${missing_deps[*]}"
    echo "       Installing..."
    python3 -m pip install "${missing_deps[@]}" --quiet
    echo "[OK] Dependencies installed"
fi

# Start bridge server
echo ""
echo "Starting bridge server..."

if [[ "$1" == "-foreground" ]] || [[ "$1" == "--foreground" ]]; then
    echo "[INFO] Running in foreground mode (Ctrl+C to stop)"
    echo ""
    cd "$BRIDGE_DIR"
    python3 chroma_bridge_server_v2.py
else
    # Run in background
    cd "$BRIDGE_DIR"
    nohup python3 chroma_bridge_server_v2.py > "$LOG_FILE" 2>&1 &
    pid=$!
    echo "$pid" > "$PID_FILE"

    echo "[OK] Bridge server started (PID: $pid)"
    echo "     PID file: $PID_FILE"
    echo "     Logs: $LOG_FILE"

    # Wait for server to be ready
    echo ""
    echo "Waiting for server to be ready..."
    max_attempts=10
    attempt=0

    while [[ $attempt -lt $max_attempts ]]; do
        sleep 1
        if curl -s http://localhost:9000/health >/dev/null 2>&1; then
            echo "[OK] Bridge server is ready!"
            echo ""
            curl -s http://localhost:9000/health | python3 -m json.tool 2>/dev/null || echo "Health check OK"
            break
        fi
        echo -n "."
        ((attempt++))
    done

    if [[ $attempt -eq $max_attempts ]]; then
        echo ""
        echo "[ERROR] Bridge server failed to start or not responding"
        echo "        Check logs at: $LOG_FILE"
        stop_bridge
        exit 1
    fi

    echo ""
    echo "============================================================"
    echo "Chroma Bridge Server Running"
    echo "============================================================"
    echo "Endpoint: http://localhost:9000"
    echo "Health:   http://localhost:9000/health"
    echo "Metrics:  http://localhost:9000/metrics"
    echo ""
    echo "Hooks will now send events to Chroma Cloud!"
    echo ""
    echo "To stop: ./start-bridge.sh -stop"
fi
