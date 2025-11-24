# Remote VM Deployment Guide

The original goal for this repository is to ship Claude hooks into **isolated virtual machines** (often Linux micro VMs) and centralize every event inside a single ChromaDB deployment. This runbook walks through the recommended topology.

---

## 1. Stand up the central bridge

1. **Provision a host** (bare metal, VM, or container) with Python 3.9+, outbound connectivity to Anthropic, and disk space for Chroma.
2. **Install dependencies** once:

   ```bash
   python3 -m venv /srv/claude-hooks/.venv
   source /srv/claude-hooks/.venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure env vars** (e.g. via systemd unit, docker env, or shell):

   ```bash
   export CHROMA_DB_PATH=/srv/chroma
   export ZO_API_KEY="choose-a-secret"
   export CHROMA_BRIDGE_PORT=9000
   ```

4. **Run the server**:

   ```bash
   python chroma_bridge_server_v2.py
   ```

   Put it behind nginx/Traefik if you need TLS. `/health` → readiness probe; `/metrics` → Prometheus scraping.

---

## 2. Bootstrap Linux VMs

Every worker VM only needs Python (comes with Claude CLI images) and SSH access so you can copy the repo or the `scripts/bootstrap_vm.sh` file.

```bash
scp -r claude-hooks-system vm-01:/tmp/claude-hooks-system
ssh vm-01 '
    cd /tmp/claude-hooks-system &&
    ZO_EVENT_ENDPOINT="https://bridge.example.com/ingest" \
    ZO_API_KEY="$ZO_API_KEY" \
    ./scripts/bootstrap_vm.sh \
        --install-dir /opt/claude-hooks \
        --project-id vm-01 \
        --log-dir /var/log/claude-events
'
```

The script:
- copies all Python hooks + `event_utils.py` into `/opt/claude-hooks/hooks`
- writes wrapper commands under `/opt/claude-hooks/bin/...`
- saves environment defaults inside `/opt/claude-hooks/.env`
- ensures the local JSONL fallback lives at `/var/log/claude-events`

Re-run it any time you update the repo to push new schema logic to the VM.

---

## 3. Wire Claude hooks on the VM

Claude Code’s `hooks.json` (or CLI settings) should point to the wrapper binaries created above. Example mapping:

```json
{
  "SessionStart": ["$HOME/bin/claude-hooks/session_start"],
  "UserPromptSubmit": ["$HOME/bin/claude-hooks/zo_report_event"],
  "PostToolUse": [
    "$HOME/bin/claude-hooks/zo_report_event",
    "$HOME/bin/claude-hooks/mcp_telemetry"
  ],
  "Stop": ["$HOME/bin/claude-hooks/zo_report_event"]
}
```

If you spawn additional worker agents from a conductor, export `CLAUDE_RUN_ID` before launching them so all events stay on the same timeline:

```bash
export CLAUDE_RUN_ID=$(uuidgen)
cns run-worker-a  # inherits CLAUDE_RUN_ID
```

---

## 4. Rolling out to fleets

For tens/hundreds of VMs:

- **SSH loop**: Keep a hosts file and run `for host in $(cat hosts.txt); do ssh "$host" '...bootstrap...' ; done`.
- **Ansible**: Wrap `scripts/bootstrap_vm.sh` inside a `copy` + `shell` task.
- **Immutable images**: During image build, copy this repo, run the bootstrap script once, and bake `/opt/claude-hooks` into the artifact so ephemeral VMs already have the hooks.

---

## 5. Validation checklist

1. On the VM, run:

   ```bash
   echo '{"session_id":"dry-run","hook_event_name":"SessionStart"}' \
     | /opt/claude-hooks/bin/session_start
   ```

   Expect a new JSONL entry in `/var/log/claude-events` and a `201` entry on the bridge logs.

2. Hit the bridge query endpoint from your laptop:

   ```bash
   curl -H "X-API-Key: $ZO_API_KEY" \
     "https://bridge.example.com/query?collection=events&limit=5"
   ```

3. If nothing shows up, confirm:
   - Bridge reachable from VM (`curl -v https://bridge.../health`)
   - `ZO_API_KEY` matches on both sides
   - VM clock is in sync (schema timestamps rely on UTC)

---

## 6. Windows?

Some environments still want PowerShell/CMD launchers. Those instructions now live in `docs/WINDOWS_DEPLOYMENT.md`. You can safely ignore them if every agent runs in Linux VMs or containers.
python $HookScript
```

**Execution Policy**:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### WSL Integration

**Use Case**: Run Linux hooks from Windows Git.

**Setup**:
```powershell
# .cmd launcher invoking WSL
@echo off
wsl python3 %~dp0zo_report_event.py %*
```

**Pros**: Native Linux environment, full POSIX compatibility.

**Cons**: WSL overhead (~100ms), path translation complexity.

### CI/CD Integration

**GitHub Actions** (cross-platform):

```yaml
name: Validate Hooks

on: [push, pull_request]

jobs:
  test-hooks:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Install hooks
        run: .\hook-pack\install.ps1
      
      - name: Test hook execution
        run: |
          echo '{"session_id":"ci-test"}' | python .git\hooks-windows\session_start.py
```

### Performance Considerations

**Hook Overhead**:
- Python interpreter startup: ~50-100ms
- HTTP POST to bridge: ~10-50ms (local)
- JSON parsing + redaction: ~5-10ms
- **Total**: ~65-160ms per hook invocation

**Optimization**:
- Use background POSTs (fire-and-forget)
- Batch events (future feature)
- Cache Python bytecode (`.pyc`)

### Security Best Practices

1. **Never commit API keys**: Use `.env` (gitignored)
2. **Restrict hooks directory**: `icacls .git\hooks-windows /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"`
3. **Validate hook sources**: Pin hook-pack version, verify checksums
4. **Use HTTPS for remote bridge**: Encrypt transport layer
5. **Rotate API keys**: Monthly rotation, logged in audit trail

### Multi-User Scenarios

**Shared Repository**:
- Each developer runs own bridge server (localhost:9000)
- OR central bridge server on internal network
- Use per-user API keys for access control

**Team Setup**:
```powershell
# Team lead: Start central bridge
$env:ZO_API_KEY = "team-shared-key"
python chroma_bridge_server_v2.py --host 0.0.0.0

# Developers: Configure endpoint
echo "ZO_EVENT_ENDPOINT=http://bridge.internal:9000/ingest" >> .env
echo "ZO_API_KEY=team-shared-key" >> .env
```

### Rollback Procedure

**Disable hooks quickly**:

```powershell
# Option 1: Unset hooks path
git config --unset core.hooksPath

# Option 2: Rename hooks directory
Rename-Item .git\hooks-windows .git\hooks-windows.disabled

# Option 3: Delete .cmd launchers
Remove-Item .git\hooks-windows\*.cmd
```

**Re-enable**:
```powershell
git config core.hooksPath .git/hooks-windows
```

### Summary Checklist

- [ ] Install Python 3.11+
- [ ] Create `.git/hooks-windows/` directory
- [ ] Copy hook scripts with LF line endings
- [ ] Generate `.cmd` launchers with CRLF
- [ ] Set `git config core.hooksPath`
- [ ] Add `.gitattributes` rules
- [ ] Configure `.env` with bridge endpoint
- [ ] Test with `echo '...' | python hook.py`
- [ ] Test with `git commit --allow-empty`
- [ ] Verify events in bridge (`/query?limit=1`)

**Next Steps**: See [hook-pack/README.md](../hook-pack/README.md) for multi-repo rollout strategies.
