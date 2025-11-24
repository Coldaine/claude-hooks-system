# Windows PowerShell launcher for hooks
# Usage: .\run-hook.ps1 <hook-name>

param(
    [Parameter(Mandatory=$true)]
    [string]$HookName
)

$ErrorActionPreference = "Stop"
$HookScript = Join-Path $PSScriptRoot "..\$HookName.py"

if (-not (Test-Path $HookScript)) {
    Write-Error "Hook script not found: $HookScript"
    exit 1
}

# Ensure UTF-8 encoding for Python
$env:PYTHONUTF8 = "1"

# Run hook with stdin passthrough
python $HookScript
