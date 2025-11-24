#!/usr/bin/env pwsh
<#
.SYNOPSIS
    PowerShell equivalent of mcp_telemetry.py for Windows Git hooks
.DESCRIPTION
    Logs MCP telemetry events to local files for Claude Code hook system
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$LogDir = $env:MCP_TELEMETRY_LOG_DIR
)

# Set default values if not provided
if (-not $LogDir) {
    $LogDir = "$env:USERPROFILE\.zo\mcp-events"
}

# Read input from stdin
$inputData = $null
try {
    $stdin = [System.Console]::In.ReadToEnd()
    if ($stdin) {
        $inputData = $stdin | ConvertFrom-Json -ErrorAction Stop
    }
} catch {
    Write-Error "[mcp_telemetry] Bad JSON: $_"
    exit 1
}

if (-not $inputData) {
    Write-Error "[mcp_telemetry] No input data provided"
    exit 1
}

$toolName = $inputData.tool_name -or ""
if (-not $toolName.StartsWith("mcp_")) {
    # Nothing to do
    exit 0
}

$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$sessionId = $inputData.session_id -or ""

# Create log directory if it doesn't exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$day = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
$logFile = Join-Path $LogDir "mcp-$day.jsonl"

# Build event
$event = @{
    ts = $timestamp
    session_id = $sessionId
    tool_name = $toolName
    hook_event_name = $inputData.hook_event_name
    payload = $inputData
}

# Append to log file
try {
    $eventJson = $event | ConvertTo-Json -Depth 10 -Compress
    Add-Content -Path $logFile -Value $eventJson -Encoding UTF8
} catch {
    Write-Error "[mcp_telemetry] File log error: $_"
}

# No structured output, just logging
exit 0