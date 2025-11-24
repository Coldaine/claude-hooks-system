# Claude Hooks System

Streamlined Claude Code hooks designed for **remote Linux VMs** that report every lifecycle event back to a central ChromaDB instance. The scripts live in this repo, the bridge server accepts events over HTTP(S), and lightweight bootstrap tooling installs the hooks on as many worker machines as you need.

## Why this exists

- Capture telemetry from agents that run in isolated VMs or containers (not on your laptop).
- Normalize events through a shared schema so orchestration code can reason about sessions/runs/workers.
- Ship events to a single ChromaDB deployment for search, analytics, and auditing.
- Keep the install surface minimal: Python stdlib on the VM + a bootstrap script that copies hooks and sets env vars.

## Building blocks

| Component | Purpose |
|-----------|---------|
| `hooks/*.py` | Claude hook entrypoints (PromptSubmit, PostToolUse, SessionStart, error/artifact/worker hooks). Pure Python, works anywhere. |
| `hooks/event_utils.py` | Shared schema helpers: IDs, hashing, redaction, metadata extraction. |
| `chroma_bridge_server_v2.py` | Hardened ingestion/query API with API-key auth, metrics, partitioned collections (`events`, `artifacts`, `embeddings`, `agent_state`). |
| `scripts/bootstrap_vm.sh` | Copies hooks + wrappers onto a VM, writes `.env`, and emits commands you can register in Claude’s hook settings. |
| `docs/schema.md` | Contract for every event payload (types, required fields, redaction expectations). |
| `docs/DEPLOYMENT.md` | End‑to‑end remote deployment runbook: central bridge + VM bootstrap + hook wiring. |
| `docs/SECURITY.md` | Threat model, redaction strategy, API-key handling. |

Windows-specific launchers still live under `hooks/launchers/` for legacy use, but the primary flow is Linux-first. Details are parked in `docs/WINDOWS_DEPLOYMENT.md`.

## End-to-end flow

1. **Central bridge**: Run `python chroma_bridge_server_v2.py` (or wrap it with systemd/docker) on the network segment that all VMs can reach. Set `ZO_API_KEY` if you want authentication.
2. **Bootstrap a VM**: SSH to the VM and run:

   ```bash
   ZO_EVENT_ENDPOINT=https://bridge.example.com/ingest \
     ./scripts/bootstrap_vm.sh \
       --install-dir /opt/claude-hooks \
       --project-id vm-worker-01 \
       --log-dir /var/log/claude-events \
       --api-key "$ZO_API_KEY"
   ```

   This creates `/opt/claude-hooks/bin/{zo_report_event,...}` with an `.env` file that points at your bridge plus a local JSONL fallback in `/var/log/claude-events`.

3. **Wire Claude hooks**: In each VM’s Claude config (or orchestrator), point events at the wrapper commands:

   | Claude Hook Event   | Command to run on the VM |
   |---------------------|--------------------------|
   | `UserPromptSubmit`, `PostToolUse`, `Stop` | `/opt/claude-hooks/bin/zo_report_event` |
   | `SessionStart` | `/opt/claude-hooks/bin/session_start` |
   | `PostToolUse` (mcp tools) | `/opt/claude-hooks/bin/mcp_telemetry` |
   | Worker lifecycle hooks | `/opt/claude-hooks/bin/worker_spawn`, `/opt/claude-hooks/bin/artifact_produced`, `/opt/claude-hooks/bin/error_event` |

4. **Run agents anywhere**: Because the wrappers load `/opt/claude-hooks/.env`, environment defaults (bridge URL, API key, log dir, project label) travel with the install. Set `CLAUDE_RUN_ID` in your orchestrator before spawning additional workers so they share timeline metadata.

## Bridge server quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ZO_API_KEY="choose-a-secret"
export CHROMA_DB_PATH=/srv/chroma
python chroma_bridge_server_v2.py
```

Endpoints:
- `POST /ingest` – append events (expects schema v1.0); rejects duplicates by hash.
- `GET /query?collection=events&run_id=...` – metadata queries.
- `GET /health` and `/metrics` – readiness + Prometheus metrics.

## Directory map

```
hooks/                # Python hook entrypoints + event_utils
hooks/launchers/      # Legacy Windows CMD/PowerShell shims
scripts/bootstrap_vm.sh
chroma_bridge_server.py / _v2.py
docs/
  schema.md
  DEPLOYMENT.md       # Remote VM deployment guide
  SECURITY.md
  WINDOWS_DEPLOYMENT.md (legacy instructions)
```

## More reading

- `docs/DEPLOYMENT.md` – remote VM bootstrap, systemd examples, reverse-proxying the bridge.
- `docs/SECURITY.md` – API key rotation, redaction knobs, compliance notes.
- `docs/MoreHooking.md` & `docs/StopHooks.md` – design discussions that informed the schema.
- `hook-pack/README.md` – optional distribution tips/templates (now includes Linux-first instructions).

Questions or rough edges? Capture them in repo issues so we can keep the remote-first workflow tight. If you still need the Windows/Powershell automation, see `docs/WINDOWS_DEPLOYMENT.md`.
