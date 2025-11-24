# Claude Hooks System - Setup Status

**Last Updated:** 2025-11-24
**Status:** ✅ **FULLY OPERATIONAL**

---

## System Components Status

| Component | Status | Location |
|-----------|--------|----------|
| **Chroma Bridge Server** | ✅ Running | `http://localhost:9000` |
| **Chroma Cloud Connection** | ✅ Connected | Tenant: `eb841491-46b0-4857-9b60-4b1dedc20049` |
| **Hook Registration** | ✅ Configured | `.claude/settings.json` |
| **Python Hooks** | ✅ Working | `hooks/*.py` (3 hooks tested) |
| **Event Schema** | ✅ v1.0 | `hooks/event_utils.py` |

---

## What Was Fixed

### 1. ❌ → ✅ Missing `.claude/settings.json`
**Problem:** Hooks weren't registered with Claude Code (custom `hooks-config.json` isn't recognized)
**Solution:** Created proper `.claude/settings.json` with hook registration

**Now configured:**
- `SessionStart` → `python hooks/session_start.py`
- `UserPromptSubmit` → `python hooks/zo_report_event.py`
- `PostToolUse` → `python hooks/zo_report_event.py` + `python hooks/mcp_telemetry.py`
- `Stop` → `python hooks/zo_report_event.py`

### 2. ❌ → ✅ Regex Escape Bug in `event_utils.py`
**Problem:** Windows path redaction failed with `re.error: bad escape \U at position 2`
**Solution:** Fixed line 159 to properly escape backslashes:
```python
# Before (broken):
path = re.sub(r'C:\\Users\\[^\\]+', 'C:\\Users\\[USER]', path)

# After (working):
path = re.sub(r'C:\\Users\\[^\\]+', r'C:\\Users\\[USER]', path)
```

### 3. ❌ → ✅ Bridge Server Not Loading `.env`
**Problem:** Server ran in local mode instead of Chroma Cloud mode
**Solution:** Added `python-dotenv` loading at top of `chroma_bridge_server_v2.py`

### 4. ❌ → ✅ Unicode Emoji Issues on Windows
**Problem:** Checkmarks and emojis crashed scripts on Windows (cp1252 encoding)
**Solution:** Replaced all emojis with `[OK]` / `[ERROR]` text markers

---

## Verified Working Hooks

All three hooks passed integration tests:

### 1. `session_start.py` ✅
- **Trigger:** When Claude Code session starts
- **Actions:**
  - Generates unique `run_id` for session
  - Sets `CLAUDE_RUN_ID` environment variable
  - Logs session_start event locally
  - Sends to Chroma Cloud (if configured)
- **Test Output:**
  ```json
  {
    "hookSpecificOutput": {
      "hookEventName": "SessionStart",
      "additionalContext": "[session] run_id=0762d22c-7bc7-4321-80a5-add6ab0a4c7a"
    }
  }
  ```

### 2. `zo_report_event.py` ✅
- **Trigger:** User prompts, tool use, session stop
- **Actions:**
  - Captures tool name, parameters, timing
  - Logs event to `~/.zo/claude-events/events-YYYYMMDD.jsonl`
  - POSTs to Chroma Bridge at `ZO_EVENT_ENDPOINT`
  - Applies redaction (PII, API keys, secrets)
- **Test Output:**
  ```json
  {
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": "[zo-log] Tool 'Bash' logged | run_id=90e9019b..."
    }
  }
  ```

### 3. `mcp_telemetry.py` ✅
- **Trigger:** MCP tools (tools starting with `mcp_`)
- **Actions:**
  - Filters for `mcp_*` tool names only
  - Logs tool parameters and results
  - Creates `mcp-YYYYMMDD.jsonl` files
  - Sends tool_invocation events to bridge
- **Test Output:** Exit 0 (early exit for non-MCP tools is correct behavior)

---

## Current Configuration

### Environment Variables (`.env`)
```bash
# Chroma Cloud
USE_CHROMA_CLOUD=true
CHROMA_API_KEY=ck-Gap2oJgWbSrsAEx43GUSguD9Z3tQjTU1sRv551iJuSGm
CHROMA_TENANT=eb841491-46b0-4857-9b60-4b1dedc20049
CHROMA_DATABASE=ClaudeCallHome

# Bridge Server
CHROMA_BRIDGE_PORT=9000

# Hook Configuration
ZO_EVENT_ENDPOINT=http://localhost:9000/ingest
ZO_EVENT_LOG_DIR=~/.zo/claude-events
ZO_REDACTION_MODE=strict
```

### Hook Registration (`.claude/settings.json`)
```json
{
  "hooks": {
    "SessionStart": {
      "*": ["python hooks/session_start.py"]
    },
    "UserPromptSubmit": {
      "*": ["python hooks/zo_report_event.py"]
    },
    "PostToolUse": {
      "Bash|Write|Edit|Read": ["python hooks/zo_report_event.py"],
      "mcp_.*": ["python hooks/mcp_telemetry.py"]
    },
    "Stop": {
      "*": ["python hooks/zo_report_event.py"]
    }
  },
  "disableAllHooks": false
}
```

---

## How It Works (End-to-End)

```
┌─────────────────────────────────────────────────────────────┐
│ Claude Code (This Session)                                 │
│                                                             │
│  User types prompt → UserPromptSubmit hook fires           │
│         ↓                                                   │
│  python hooks/zo_report_event.py                           │
│         ├─ Read JSON from stdin (hook context)             │
│         ├─ Build canonical event envelope (schema v1.0)    │
│         ├─ Apply redaction (emails, API keys, IPs)         │
│         ├─ Log to ~/.zo/claude-events/events-20251124.jsonl│
│         └─ POST to http://localhost:9000/ingest            │
└─────────────────────────────────────────────────────────────┘
                         │
                         ↓ HTTP POST (JSON)
┌─────────────────────────────────────────────────────────────┐
│ Chroma Bridge Server (localhost:9000)                      │
│                                                             │
│  POST /ingest                                               │
│         ├─ Validate schema version                          │
│         ├─ Check hash for duplicates                        │
│         ├─ Partition to 4 collections:                      │
│         │   ├─ events (always)                              │
│         │   ├─ embeddings (if semantic-searchable)          │
│         │   ├─ artifacts (if artifact event)                │
│         │   └─ agent_state (if worker heartbeat)            │
│         └─ Return 201 Created                               │
└─────────────────────────────────────────────────────────────┘
                         │
                         ↓ CloudClient API
┌─────────────────────────────────────────────────────────────┐
│ Chroma Cloud (api.trychroma.com)                           │
│                                                             │
│  Tenant: eb841491-46b0-4857-9b60-4b1dedc20049              │
│  Database: ClaudeCallHome                                   │
│                                                             │
│  Collections:                                               │
│   ├─ events: 1 document                                     │
│   ├─ artifacts: 0 documents                                 │
│   ├─ embeddings: 0 documents                                │
│   └─ agent_state: 0 documents                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Testing the System

### 1. Test Hooks Directly
```bash
python test_hooks.py
```
**Result:** All 3 hooks pass ✅

### 2. Test Bridge Health
```bash
curl http://localhost:9000/health
```
**Result:**
```json
{
  "status": "healthy",
  "collections": {
    "events": 1,
    "artifacts": 0,
    "embeddings": 0,
    "agent_state": 0
  }
}
```

### 3. Send Test Event
```bash
curl -X POST http://localhost:9000/ingest \
  -H "Content-Type: application/json" \
  -d @test_event.json
```
**Result:** Event stored in Chroma Cloud ✅

### 4. Query Events
```bash
curl "http://localhost:9000/query?collection=events&run_id=test-run-123"
```
**Result:** Returns stored events ✅

---

## Next Steps

### ✅ Ready for Production Use

1. **Hooks are live:** Use Claude Code normally - hooks will fire automatically
2. **Monitor events:** Check `%USERPROFILE%\.zo\claude-events\` for local logs
3. **Query Chroma Cloud:** Use `/query` endpoint or Chroma Cloud dashboard
4. **Deploy to remote VMs:** See `docs/DEPLOYMENT.md` for multi-VM setup

### Optional Enhancements

- **Add authentication:** Set `ZO_API_KEY` for bridge server authentication
- **Enable TLS:** Deploy bridge behind nginx with SSL (see `docs/DEPLOYMENT.md`)
- **Worker orchestration:** Use `worker_spawn.py` hook for multi-VM coordination
- **Semantic search:** Query embeddings collection for similar events

---

## Files Reference

| File | Purpose | Status |
|------|---------|--------|
| `.claude/settings.json` | Hook registration (Claude Code reads this) | ✅ Created |
| `.claude/hooks-config.json` | Custom config (not used by Claude Code) | ℹ️ Legacy |
| `hooks/session_start.py` | Initialize run context | ✅ Working |
| `hooks/zo_report_event.py` | General event reporter | ✅ Working |
| `hooks/mcp_telemetry.py` | MCP tool telemetry | ✅ Working |
| `hooks/event_utils.py` | Shared utilities (schema, redaction) | ✅ Fixed regex bug |
| `chroma_bridge_server_v2.py` | HTTP bridge to Chroma Cloud | ✅ Running |
| `.env` | Environment configuration | ✅ Configured |
| `test_hooks.py` | Integration test script | ✅ All tests pass |

---

## Troubleshooting

### Hooks Not Firing?
1. Check `.claude/settings.json` exists in project root
2. Verify `disableAllHooks` is `false`
3. Ensure Python is in PATH: `python --version`

### Events Not Reaching Cloud?
1. Check bridge server is running: `curl http://localhost:9000/health`
2. Verify `ZO_EVENT_ENDPOINT` is set: `echo $ZO_EVENT_ENDPOINT`
3. Check bridge logs for errors

### Local Logs Not Created?
1. Check directory exists: `ls ~/.zo/claude-events/`
2. Verify `ZO_EVENT_LOG_DIR` is set correctly
3. Hooks will create directory automatically if missing

---

**Status:** ✅ System fully operational and tested
**Chroma Cloud:** ✅ Connected and storing events
**All Hooks:** ✅ Registered and working
**Ready for:** Live use + remote VM deployment

