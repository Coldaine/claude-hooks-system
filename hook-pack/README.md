# Claude Code Hook Pack
> Portable hook bundle for remote Linux workers + optional Windows launchers

## Linux / VM quick start

1. **Bootstrap the VM**

   ```bash
   git clone https://github.com/yourorg/claude-hooks-system.git
   cd claude-hooks-system
   ZO_EVENT_ENDPOINT="https://bridge.example.com/ingest" \
     ZO_API_KEY="$ZO_API_KEY" \
     ./scripts/bootstrap_vm.sh \
       --install-dir /opt/claude-hooks \
       --project-id vm-01
   ```

2. **Wire Claude hooks**

   Point hook events at the generated wrappers (for example `/opt/claude-hooks/bin/zo_report_event`). All environment defaults live in `/opt/claude-hooks/.env`, so rotating API keys or changing the bridge URL is a single-file edit.

3. **Verify telemetry**

   ```bash
   echo '{"session_id":"smoke","hook_event_name":"SessionStart"}' \
     | /opt/claude-hooks/bin/session_start
   curl -H "X-API-Key: $ZO_API_KEY" \
     "https://bridge.example.com/query?collection=events&limit=5"
   ```

For fleets, wrap the bootstrap call inside Ansible, image build steps, or a thin SSH loop. Re-run it whenever hooks change.

## Optional Windows kit

PowerShell/CMD launchers plus Git hook wiring still exist for teams that need them (`hook-pack/install.ps1`, `hooks/launchers/`). The full walkthrough lives in `docs/WINDOWS_DEPLOYMENT.md`. Ignore this section if all agents run in Linux VMs.

## Hook scripts

| Hook | Purpose | Triggered By |
|------|---------|--------------|
| `zo_report_event.py` | General lifecycle events | UserPromptSubmit, PostToolUse, SessionStart, Stop |
| `mcp_telemetry.py` | MCP tool invocations | PostToolUse (mcp_* tools) |
| `session_start.py` | Session initialization | SessionStart |
| `worker_spawn.py` | Worker creation events | Custom orchestration hooks |
| `artifact_produced.py` | File/output tracking | Custom (after artifact creation) |
| `error_event.py` | Error capture with stack traces | PostToolUse (on error) |

All hooks rely on `hooks/event_utils.py` for schema v1.0 compliance (IDs, hashing, redaction, indexable text extraction).

## Rollout patterns

1. **Immutable image bake** – During your VM image build, run `scripts/bootstrap_vm.sh` and bake the resulting `/opt/claude-hooks` directory into the artifact. Every VM boots with the hooks pre-installed.
2. **Provisioning scripts** – Keep a host inventory and run the bootstrap script via Ansible/fabric/ssh. Example:

   ```bash
   for host in $(cat hosts.txt); do
     scp -r claude-hooks-system "$host":/tmp/claude-hooks-system
     ssh "$host" 'cd /tmp/claude-hooks-system && ./scripts/bootstrap_vm.sh --install-dir /opt/claude-hooks'
   done
   ```

3. **Central share** – Store `/opt/claude-hooks` on object storage/NFS and `rsync` it down during boot for air-gapped deployments.

## Event schema + collections

Events conform to [`docs/schema.md`](../docs/schema.md) and land in the following ChromaDB collections when posted to `chroma_bridge_server_v2.py`:

- `events`: canonical log, always updated
- `artifacts`: artifact metadata (hash/path/type)
- `embeddings`: semantic search surface (decisions, errors, artifacts)
- `agent_state`: latest heartbeat per `(run_id, worker_id)`

Each hook produces:

```json
{
  "event_id": "uuid",
  "ts": "2025-11-19T14:23:01.234Z",
  "schema_version": "1.0",
  "session_id": "sess_abc",
  "run_id": "run_xyz",
  "event_type": "worker_spawn | progress | artifact | error | ...",
  "level": "info | warn | error | debug",
  "msg": "Human-readable summary",
  "data": { "sanitized": "payload" },
  "indexable_text": "Plain text for embedding",
  "hash": "sha256:...",
  "redaction": { "applied": true, "rules": ["email", "api_key"] }
}
```

## Security checklist

- Set `ZO_API_KEY` on both VM and bridge; the bootstrap script will write it into `/opt/claude-hooks/.env`.
- Rotate secrets by editing the `.env` file and restarting long-running Claude sessions.
- Use `ZO_REDACTION_MODE=strict` (default) unless you are debugging locally.
- Keep `/var/log/claude-events` readable only by the Claude user if you store sensitive prompts.

Need Git/Windows specifics? Jump to `docs/WINDOWS_DEPLOYMENT.md`.
