# Legacy Deployment Guide: Windows-Specific Considerations

> Prefer Linux/VM deployments? See `docs/DEPLOYMENT.md`. Keep this document only if you must integrate with Git hooks on Windows.

## Git Hooks on Windows: The Complete Guide

### The Problem

Git hooks on Windows face unique challenges:

1. **Shebang Ignored**: `#!/usr/bin/env python3` does nothing on Windows
2. **No Executable Bit**: NTFS doesn't support Unix permissions
3. **File Associations**: `.sh` files open in default text editor (Notepad)
4. **Line Endings**: CRLF vs LF inconsistencies break scripts
5. **Python Resolution**: Multiple Python installations confuse interpreter lookup

### The Solution: Multi-Layered Approach

#### Layer 1: `.cmd` Launchers

Create Windows batch file wrappers for each hook:

```cmd
@echo off
REM post-commit.cmd
REM Launches Python hook with explicit interpreter

python "%~dp0zo_report_event.py" %*
```

**Why it works**:
- `.cmd` is native Windows executable format
- `%~dp0` resolves to directory containing the `.cmd` file
- `python` uses PATH resolution (respects virtual environments)
- `%*` forwards all command-line arguments

#### Layer 2: `core.hooksPath`

Point Git to Windows-specific hooks directory:

```powershell
git config core.hooksPath .git/hooks-windows
```

**Benefits**:
- Isolates Windows launchers from Unix hooks
- Per-repository configuration (not global)
- Avoids conflicts with cross-platform `.sh` scripts

#### Layer 3: `.gitattributes`

Enforce line endings for Python scripts:

```gitattributes
*.py text eol=lf
*.sh text eol=lf
hooks/** text eol=lf

*.cmd text eol=crlf
*.ps1 text eol=crlf
```

**Why LF for Python**:
- Python tokenizer expects `\n` (LF) for line endings
- `#!/usr/bin/env python3` must be first line, LF-terminated
- Cross-platform compatibility (Unix, macOS, WSL)

**Why CRLF for .cmd/.ps1**:
- Windows cmd.exe and PowerShell expect `\r\n` (CRLF)
- Prevents parsing errors in batch scripts

#### Layer 4: `PYTHONUTF8=1`

Set encoding environment variable:

```powershell
$env:PYTHONUTF8=1
python script.py
```

**Prevents**:
- Unicode decode errors in JSON parsing
- Mojibake in non-ASCII output
- `UnicodeDecodeError` on Windows-1252 systems

### Installation Methods

#### Automated (Recommended)

```powershell
cd your-project
.\hook-pack\install.ps1
```

**What it does**:
1. Creates `.git/hooks-windows/` directory
2. Copies Python hook scripts with LF line endings
3. Generates `.cmd` launchers for each hook
4. Sets `git config core.hooksPath .git/hooks-windows`
5. Updates `.gitattributes` with line-ending rules
6. Creates `.env.example` with configuration template

#### Manual Installation

```powershell
# 1. Create hooks directory
mkdir .git\hooks-windows

# 2. Copy hook scripts
cp hooks\*.py .git\hooks-windows\

# 3. Create launcher for post-commit hook
@'
@echo off
python "%~dp0zo_report_event.py" %*
'@ | Out-File -Encoding ASCII .git\hooks-windows\post-commit.cmd

# 4. Configure Git
git config core.hooksPath .git/hooks-windows

# 5. Enforce line endings
@'
*.py text eol=lf
hooks/** text eol=lf
'@ | Out-File -Append .gitattributes
```

### Testing Hook Execution

#### Test 1: Direct Invocation

```powershell
echo '{"session_id":"test","hook_event_name":"SessionStart"}' | python .git\hooks-windows\session_start.py
```

**Expected**: No errors, optional JSON output to stdout.

#### Test 2: Launcher Invocation

```powershell
echo '{"session_id":"test"}' | .git\hooks-windows\post-commit.cmd
```

**Expected**: Hook executes, events logged to `~/.zo/claude-events/`.

#### Test 3: Git Integration

```powershell
git commit --allow-empty -m "Test hooks"
```

**Expected**: Hook triggers automatically, event sent to bridge.

### Troubleshooting

#### Hook Not Executing

**Symptom**: No events logged, no errors.

**Diagnosis**:
```powershell
# Check hooks path
git config core.hooksPath
# Expected: .git/hooks-windows or similar

# Verify launcher exists
Test-Path .git\hooks-windows\post-commit.cmd

# Check Python path
where.exe python
# Expected: Venv or system Python
```

**Fix**:
- Re-run `install.ps1`
- Ensure `.cmd` launcher has CRLF line endings
- Check Python is in PATH

#### Shebang Errors

**Symptom**: `SyntaxError: invalid syntax` on first line.

**Diagnosis**:
```powershell
# Check file encoding
Get-Content -Raw hooks\session_start.py | Format-Hex | Select-Object -First 1
# Should NOT start with BOM (EF BB BF)
```

**Fix**:
```powershell
# Convert to UTF-8 without BOM
Get-Content hooks\session_start.py | Set-Content -Encoding UTF8 hooks\session_start.py
```

#### Unicode Errors

**Symptom**: `UnicodeDecodeError: 'charmap' codec can't decode byte...`

**Fix**:
```powershell
$env:PYTHONUTF8=1
# Add to .cmd launcher or global environment
```

#### Line Ending Issues

**Symptom**: `\r`: command not found` or similar.

**Diagnosis**:
```powershell
# Check line endings
(Get-Content -Raw hooks\session_start.py) -match "\r\n"
# Should be False (LF only)
```

**Fix**:
```powershell
# Normalize to LF
(Get-Content hooks\session_start.py) | Set-Content -NoNewline hooks\session_start.py
```

### Virtual Environment Isolation

**Problem**: System Python vs venv Python conflicts.

**Solution**: Activate venv before running hooks.

```cmd
REM .cmd launcher with venv activation
@echo off
call "%~dp0..\.venv\Scripts\activate.bat"
python "%~dp0zo_report_event.py" %*
```

**Alternative**: Use explicit venv Python path.

```cmd
@echo off
"%~dp0..\.venv\Scripts\python.exe" "%~dp0zo_report_event.py" %*
```

### Global Hooks (Cross-Repository)

**Use Case**: Apply hooks to all repositories on machine.

**Setup**:
```powershell
# Create global hooks directory
mkdir C:\Users\$env:USERNAME\.git-hooks

# Copy hook scripts
cp hooks\*.py C:\Users\$env:USERNAME\.git-hooks\
cp hooks\launchers\*.cmd C:\Users\$env:USERNAME\.git-hooks\

# Configure Git globally
git config --global core.hooksPath C:\Users\$env:USERNAME\.git-hooks
```

**Caution**: Affects ALL repositories. Disable per-repo with:
```powershell
git config --unset core.hooksPath
```

### PowerShell Hooks (Alternative)

**Pros**: Native Windows scripting, no Python required for launchers.

**Cons**: Less portable, requires PowerShell execution policy.

**Example**:
```powershell
# post-commit.ps1
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$HookScript = Join-Path $PSScriptRoot "zo_report_event.py"
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
