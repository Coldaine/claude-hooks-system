# Claude Hooks System - Quick Start Guide

Get your hooks sending events to Chroma Cloud in 2 minutes.

---

## Prerequisites

- Python 3.8+ installed
- Chroma Cloud account with credentials (API key, tenant, database)

---

## Setup (One-Time)

### 1. Configure Chroma Cloud Credentials

Edit `.env` file:

```bash
USE_CHROMA_CLOUD=true
CHROMA_API_KEY=ck-your-api-key-here
CHROMA_TENANT=your-tenant-id
CHROMA_DATABASE=ClaudeCallHome
```

### 2. Install Dependencies

```bash
pip install chromadb python-dotenv
```

---

## Usage

### Windows (PowerShell)

```powershell
# Start the bridge server
.\start-bridge.ps1

# Check if it's running
.\start-bridge.ps1    # Shows status if already running

# Stop the bridge server
.\start-bridge.ps1 -Stop

# Run in foreground (for debugging)
.\start-bridge.ps1 -Foreground
```

### Linux/Mac (Bash)

```bash
# Start the bridge server
./start-bridge.sh

# Check if it's running
./start-bridge.sh    # Shows status if already running

# Stop the bridge server
./start-bridge.sh -stop

# Run in foreground (for debugging)
./start-bridge.sh -foreground
```

---

## What Happens?

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Claude Code Session Starts                              │
│    └─> SessionStart hook fires                             │
│        └─> Logs locally + sends to localhost:9000          │
└─────────────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Bridge Server (localhost:9000)                          │
│    ├─ Receives event via HTTP POST                         │
│    ├─ Validates schema                                     │
│    ├─ Checks for duplicates (hash)                         │
│    └─> Sends to Chroma Cloud                               │
└─────────────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Chroma Cloud (api.trychroma.com)                        │
│    └─ Stores in ClaudeCallHome database                    │
│       ├─ events collection                                 │
│       ├─ artifacts collection                              │
│       ├─ embeddings collection                             │
│       └─ agent_state collection                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Verify It's Working

### 1. Check Bridge Health

```bash
curl http://localhost:9000/health
```

**Expected output:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-24T...",
  "collections": {
    "events": 5,
    "artifacts": 0,
    "embeddings": 0,
    "agent_state": 0
  }
}
```

### 2. Check Local Logs

**Windows:**
```powershell
Get-Content ~\.zo\claude-events\events-*.jsonl | Select-Object -Last 5
```

**Linux/Mac:**
```bash
tail -5 ~/.zo/claude-events/events-*.jsonl
```

### 3. Query Events from Chroma

```bash
curl "http://localhost:9000/query?collection=events&limit=5"
```

### 4. Use Claude Code

Just use Claude Code normally! Every time you:
- Start a session → `SessionStart` event logged
- Send a prompt → `UserPromptSubmit` event logged
- Use a tool → `PostToolUse` event logged
- Use MCP tools → `mcp_telemetry` captures details
- Session ends → `Stop` event logged

---

## Troubleshooting

### Bridge Won't Start

**Error:** `.env file not found`
- **Solution:** Create `.env` with your Chroma Cloud credentials

**Error:** `Python not found`
- **Solution:** Install Python 3.8+ and add to PATH

**Error:** `Missing dependencies`
- **Solution:** Run `pip install chromadb python-dotenv`

### Bridge Starts But Not Responding

Check the logs:
```bash
cat bridge.log    # Linux/Mac
type bridge.log   # Windows
```

### Events Not Reaching Chroma Cloud

1. **Check bridge is running:**
   ```bash
   curl http://localhost:9000/health
   ```

2. **Check Chroma credentials in `.env`:**
   - API key valid?
   - Tenant ID correct?
   - Database name matches?

3. **Test connection manually:**
   ```bash
   python test_chroma_connection.py
   ```

### Hooks Not Firing

1. **Check `.claude/settings.json` exists** in your project
2. **Verify hooks are enabled:** `"disableAllHooks": false`
3. **Check local logs exist:** `ls ~/.zo/claude-events/`

---

## Architecture

### Why the Bridge?

The bridge server is needed because:

| Concern | Without Bridge | With Bridge |
|---------|---------------|-------------|
| **Hook Speed** | 150ms (create Chroma connection) | 2ms (HTTP POST) |
| **Dependencies** | Each hook imports chromadb | Hooks are simple Python scripts |
| **Deduplication** | ❌ Duplicates possible | ✅ Hash-based dedup |
| **Partitioning** | ❌ Manual logic in each hook | ✅ Smart routing to 4 collections |
| **Monitoring** | ❌ No visibility | ✅ /health + /metrics |
| **Error Handling** | ❌ Hooks fail if Chroma down | ✅ Local fallback always works |

### Event Flow

```
Hook (2ms) → Bridge (50ms) → Chroma Cloud (50-100ms)
             └─> Also logs locally (always succeeds)
```

**Without the bridge**, every hook would:
- Import chromadb (500ms startup penalty)
- Create CloudClient (100ms auth)
- Implement partitioning logic (code duplication)
- Miss deduplication (duplicate events)

**With the bridge**, hooks are fast, simple HTTP POSTs, and the bridge handles all the complexity.

---

## Auto-Start on Boot (Optional)

### Windows (Task Scheduler)

Create a scheduled task:
```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-File E:\_projectsGithub\claude-hooks-system\start-bridge.ps1"

$trigger = New-ScheduledTaskTrigger -AtStartup

Register-ScheduledTask -TaskName "ChromaBridge" `
  -Action $action -Trigger $trigger -RunLevel Highest
```

### Linux (systemd)

Create `/etc/systemd/system/chroma-bridge.service`:

```ini
[Unit]
Description=Chroma Bridge Server for Claude Hooks
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/claude-hooks-system
ExecStart=/usr/bin/python3 /path/to/claude-hooks-system/chroma_bridge_server_v2.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable chroma-bridge
sudo systemctl start chroma-bridge
sudo systemctl status chroma-bridge
```

---

## Next Steps

- **Deploy to remote VMs:** See `docs/DEPLOYMENT.md`
- **Multi-agent orchestration:** See `docs/schema.md` for run_id tracking
- **Custom hooks:** Add new hooks in `hooks/` directory
- **Query events:** Use `/query` endpoint or Chroma Cloud dashboard

---

## Support

- **GitHub Issues:** https://github.com/Coldaine/claude-hooks-system/issues
- **Documentation:** See `docs/` directory
- **Test Scripts:** Run `python test_hooks.py` or `python test_chroma_connection.py`

---

**Status:** ✅ System Ready
**Bridge:** http://localhost:9000
**Chroma Cloud:** Connected
**Hooks:** Registered and firing
