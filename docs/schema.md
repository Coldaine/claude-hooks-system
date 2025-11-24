# Claude Code Event Schema v1.0

## Overview
Canonical event schema for Claude Code hooks, enabling parallel agent orchestration via ChromaDB event log. Supports Conductor/Worker patterns with lifecycle tracking, artifact management, and semantic retrieval.

## Event Types (Enum)
- `session_start` - User session begins; initializes run_id
- `session_end` - Session terminates; finalizes artifacts
- `worker_spawn` - Conductor spawns worker with task assignment
- `worker_heartbeat` - Periodic progress checkpoint
- `progress` - General progress update (e.g., PostToolUse)
- `artifact` - File/output produced
- `error` - Tool or hook failure
- `tool_invocation` - MCP or native tool executed
- `decision` - Planning/reasoning step captured
- `done` - Task completion marker

## Agent Roles (Enum)
- `conductor` - Orchestrator/planner
- `worker` - Task executor
- `system` - Infrastructure event

## Severity Levels (Enum)
- `debug` - Verbose operational detail
- `info` - Normal lifecycle event
- `warn` - Degraded operation or retry
- `error` - Failure requiring attention

## Core Event Fields (Required)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `event_id` | UUID string | Unique event identifier | `"550e8400-e29b-41d4-a716-446655440000"` |
| `ts` | RFC3339 UTC | Event timestamp | `"2025-11-19T14:23:01.234Z"` |
| `schema_version` | string | Schema revision | `"1.0"` |
| `session_id` | string | Claude session identifier | `"sess_abc123"` |
| `run_id` | UUID string | Orchestration run (per multi-agent task) | `"run_xyz789"` |
| `event_type` | enum | Event category | `"worker_spawn"` |
| `level` | enum | Severity | `"info"` |

## Extended Event Fields (Optional)

| Field | Type | Description |
|-------|------|-------------|
| `hook_event_name` | string | Original hook name (e.g., "PostToolUse") |
| `agent_role` | enum | conductor / worker / system |
| `worker_id` | UUID string | Unique worker instance ID |
| `task_id` | string | Assigned task identifier |
| `tool_name` | string | Tool invoked (if applicable) |
| `tool_use_id` | string | Claude tool execution ID |
| `msg` | string | Human-readable summary (max 500 chars) |
| `data` | object | Sanitized structured payload |
| `artifact_refs` | array | `[{path, type, hash, size_bytes}]` |
| `source` | object | `{host, remote:bool, cwd, project_dir}` |
| `indexable_text` | string | Plain text for embedding (max 2000 chars) |
| `hash` | SHA256 hex | Content hash for deduplication |
| `redaction` | object | `{applied:bool, rules:[...]}` |
| `parent_event_id` | UUID string | Causal link to triggering event |
| `error_detail` | object | `{type, message, stack_trace}` |

## Source Object
```json
{
  "host": "redacted",           // Hostname (sanitized)
  "remote": false,               // Running remotely
  "cwd": "/project/path",        // Working directory
  "project_dir": "my-project"    // Project identifier
}
```

## Artifact Reference
```json
{
  "path": "outputs/report.md",
  "type": "markdown",
  "hash": "sha256:abc123...",
  "size_bytes": 4096,
  "produced_at": "2025-11-19T14:23:05Z"
}
```

## Redaction Rules

### PII & Secrets
- **Email addresses**: Replace with `[EMAIL]`
- **API keys/tokens**: Pattern match `(sk|pk|ck|ghp|gho)_[A-Za-z0-9]{20,}` → `[REDACTED_KEY]`
- **File paths**: Allowlist `/project/`, `/workspace/` → redact user home paths
- **Hostnames**: Hash with salt → `host_abc123`
- **IP addresses**: `192.168.x.x` → `[IP]`

### Configuration
```json
{
  "redaction": {
    "applied": true,
    "rules": ["email", "api_key", "hostname"],
    "mode": "strict"  // strict | lenient | disabled
  }
}
```

## Collection Partitioning

### 1. `events` (Primary Log)
- **Purpose**: Append-only event stream
- **Retention**: 90 days
- **Indexes**: `(run_id, ts)`, `(event_type, level, ts)`, `(session_id, ts)`
- **Document**: Full JSON event envelope
- **Metadata**: `{event_id, ts, run_id, event_type, level, worker_id, task_id}`

### 2. `artifacts` (File Catalog)
- **Purpose**: Artifact metadata registry
- **Retention**: 365 days (hash-based dedup)
- **Indexes**: `(hash)` UNIQUE, `(run_id, task_id)`
- **Document**: Artifact description + lineage
- **Metadata**: `{hash, path, type, size_bytes, produced_by_event_id, run_id}`

### 3. `embeddings` (Semantic Index)
- **Purpose**: Vector search over decisions, errors, summaries
- **Retention**: Selective (decision, error, artifact types only)
- **Indexes**: Vector index + metadata filters
- **Document**: `indexable_text` field only
- **Metadata**: `{event_id, event_type, run_id, worker_id, ts}`

### 4. `agent_state` (Status Snapshots)
- **Purpose**: Latest worker/run status (upsert by composite key)
- **Retention**: Until run finalized
- **Indexes**: `(run_id, worker_id)` UNIQUE
- **Document**: Latest state summary
- **Metadata**: `{run_id, worker_id, status, last_heartbeat, task_id, progress_pct}`

## Ingestion Flow
1. Hook captures event → `event_utils.build_event_envelope()`
2. Apply `redact_payload()` based on configured rules
3. Generate `event_id`, `hash`, `indexable_text`
4. Append to local JSONL (rotated daily)
5. POST to bridge `/ingest` endpoint (authenticated)
6. Bridge validates schema_version, partitions to collections
7. `events`: direct add; `embeddings`: if event_type in [decision, error, artifact]; `agent_state`: upsert if worker_heartbeat/progress

## Deduplication Strategy
- Use `hash` field (SHA256 of `{session_id, ts, event_type, data}`)
- Bridge checks last N events in `events` collection for matching hash
- If duplicate within 5-minute window → return 202 Accepted (idempotent)

## Evolution & Versioning
- `schema_version` field enables forward/backward compatibility
- Bridge supports multiple schema versions simultaneously
- Migrations stored in `migrations/` with `vN_to_vM.py` scripts
- Breaking changes increment major version (e.g., 1.x → 2.0)

## Windows Compatibility
- Line endings: LF enforced via `.gitattributes`
- Hook launchers: `.cmd` wrappers invoke Python with explicit interpreter
- File paths: Normalize separators (`/` preferred; `os.path.normpath` in hooks)
- Encodings: UTF-8 with BOM handling (`PYTHONUTF8=1` env var)

## Security Considerations
1. **Authentication**: Bridge requires `X-API-Key` header (configurable secret)
2. **Transport**: HTTPS recommended for remote deployments
3. **Encryption**: ChromaDB path permissions (700), optional at-rest encryption
4. **Audit**: All ingestion attempts logged with client IP/timestamp
5. **Rate Limiting**: 100 req/min per API key (configurable)

## Example Event: Worker Spawn
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "ts": "2025-11-19T14:23:01.234Z",
  "schema_version": "1.0",
  "session_id": "sess_abc123",
  "run_id": "run_xyz789",
  "event_type": "worker_spawn",
  "level": "info",
  "hook_event_name": "PostToolUse",
  "agent_role": "conductor",
  "worker_id": "worker_001",
  "task_id": "task_refactor_utils",
  "msg": "Spawned worker for refactor task",
  "data": {
    "worker_config": {
      "max_iterations": 10,
      "tools": ["edit_file", "run_tests"]
    },
    "task_description": "Refactor event utilities module"
  },
  "source": {
    "host": "host_abc123",
    "remote": false,
    "cwd": "/workspace/claude-hooks-system",
    "project_dir": "claude-hooks-system"
  },
  "indexable_text": "Spawned worker worker_001 for task task_refactor_utils: Refactor event utilities module",
  "hash": "d2a84f4b8b650937ec8f73cd8be2c74add5a911ba64df27458ed8229da804a26",
  "redaction": {
    "applied": true,
    "rules": ["hostname"]
  }
}
```
