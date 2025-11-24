# Claude Code Hook Pack Installation Script
# Installs hooks into target repository with Windows-compatible launchers

param(
    [string]$TargetRepo = ".",
    [switch]$Global,
    [string]$HooksPath = ".git/hooks-windows"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Claude Code Hook Pack Installer ===" -ForegroundColor Cyan
Write-Host ""

# Validate target is a git repository
$GitRoot = git -C $TargetRepo rev-parse --show-toplevel 2>$null
if (-not $GitRoot) {
    Write-Error "Target directory is not a Git repository: $TargetRepo"
    exit 1
}

Write-Host "Target repository: $GitRoot" -ForegroundColor Green

# Determine hook pack source directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HookPackRoot = Split-Path -Parent $ScriptDir

if (-not (Test-Path "$HookPackRoot\hooks")) {
    Write-Error "Hooks directory not found. Ensure install.ps1 is in hook-pack/"
    exit 1
}

# Create hooks directory structure
$HooksDir = Join-Path $GitRoot $HooksPath
if (-not (Test-Path $HooksDir)) {
    New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null
    Write-Host "Created hooks directory: $HooksDir" -ForegroundColor Yellow
}

# Copy hook scripts
Write-Host "Copying hook scripts..." -ForegroundColor Cyan
$HookScripts = @(
    "event_utils.py",
    "zo_report_event.py",
    "mcp_telemetry.py",
    "session_start.py",
    "worker_spawn.py",
    "artifact_produced.py",
    "error_event.py"
)

foreach ($script in $HookScripts) {
    $source = Join-Path "$HookPackRoot\hooks" $script
    $dest = Join-Path $HooksDir $script
    
    if (Test-Path $source) {
        Copy-Item -Path $source -Destination $dest -Force
        Write-Host "  ✓ $script" -ForegroundColor Green
    } else {
        Write-Warning "  ⚠ $script not found, skipping"
    }
}

# Create Windows .cmd launchers
Write-Host ""
Write-Host "Creating Windows launchers..." -ForegroundColor Cyan

$Launchers = @{
    "post-commit" = "zo_report_event.py"
    "post-merge" = "zo_report_event.py"
    "pre-push" = "zo_report_event.py"
}

foreach ($hookName in $Launchers.Keys) {
    $scriptName = $Launchers[$hookName]
    $launcherPath = Join-Path $HooksDir "$hookName.cmd"
    
    $launcherContent = @"
@echo off
REM Auto-generated Claude Code hook launcher
REM Invokes: $scriptName

python "%~dp0$scriptName" %*
"@
    
    Set-Content -Path $launcherPath -Value $launcherContent -Force
    Write-Host "  ✓ $hookName.cmd → $scriptName" -ForegroundColor Green
}

# Configure Git hooks path
Write-Host ""
Write-Host "Configuring Git..." -ForegroundColor Cyan

if ($Global) {
    git config --global core.hooksPath $HooksPath
    Write-Host "  ✓ Global hooks path set: $HooksPath" -ForegroundColor Green
} else {
    Push-Location $GitRoot
    git config core.hooksPath $HooksPath
    Pop-Location
    Write-Host "  ✓ Repository hooks path set: $HooksPath" -ForegroundColor Green
}

# Create .gitattributes for LF enforcement
$GitAttributesPath = Join-Path $GitRoot ".gitattributes"
$attributeRules = @"
# Claude Code Hooks - Enforce LF line endings
*.py text eol=lf
*.sh text eol=lf
hooks/** text eol=lf
"@

if (Test-Path $GitAttributesPath) {
    $existingContent = Get-Content $GitAttributesPath -Raw
    if ($existingContent -notmatch "Claude Code Hooks") {
        Add-Content -Path $GitAttributesPath -Value "`n$attributeRules"
        Write-Host "  ✓ Updated .gitattributes" -ForegroundColor Green
    }
} else {
    Set-Content -Path $GitAttributesPath -Value $attributeRules -Force
    Write-Host "  ✓ Created .gitattributes" -ForegroundColor Green
}

# Copy or create .env.example
$EnvExamplePath = Join-Path $GitRoot ".env.example"
if (-not (Test-Path $EnvExamplePath)) {
    $envTemplate = @"
# Claude Code Event Logging Configuration

# ChromaDB Bridge Endpoint
ZO_EVENT_ENDPOINT=http://localhost:9000/ingest

# API Key for bridge authentication (optional)
# ZO_API_KEY=your-secret-key-here

# Redaction mode: strict | lenient | disabled
ZO_REDACTION_MODE=strict

# Local event log directory (fallback when bridge unavailable)
ZO_EVENT_LOG_DIR=~/.zo/claude-events

# MCP telemetry log directory
MCP_TELEMETRY_LOG_DIR=~/.zo/mcp-events

# Hostname salt for privacy (optional)
# HOSTNAME_SALT=random-salt-value
"@
    
    Set-Content -Path $EnvExamplePath -Value $envTemplate -Force
    Write-Host "  ✓ Created .env.example" -ForegroundColor Green
}

# Summary
Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Copy .env.example to .env and configure:"
Write-Host "   cp .env.example .env"
Write-Host ""
Write-Host "2. Start ChromaDB Bridge (if not running):"
Write-Host "   cd claude-hooks-system"
Write-Host "   python chroma_bridge_server_v2.py"
Write-Host ""
Write-Host "3. Test hook execution:"
Write-Host "   echo '{\"session_id\":\"test\"}' | python $HooksDir\session_start.py"
Write-Host ""
Write-Host "4. Verify Git integration:"
Write-Host "   git commit --allow-empty -m 'Test hooks'"
Write-Host ""

Write-Host "Hooks installed in: $HooksDir" -ForegroundColor Green
Write-Host "Documentation: hook-pack/README.md" -ForegroundColor Green
