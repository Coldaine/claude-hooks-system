#!/usr/bin/env pwsh
<#
.SYNOPSIS
    PowerShell equivalent of zo_report_event.py for Windows Git hooks
.DESCRIPTION
    Reports events to ChromaDB and local logs for Claude Code hook system
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$EventEndpoint = $env:ZO_EVENT_ENDPOINT,
    
    [Parameter(Mandatory=$false)]
    [string]$LogDir = $env:ZO_EVENT_LOG_DIR,
    
    [Parameter(Mandatory=$false)]
    [int]$TimeoutSeconds = 2
)

# Set default values if not provided
if (-not $LogDir) {
    $LogDir = "$env:USERPROFILE\.zo\claude-events"
}

# Create log directory if it doesn't exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Read input from stdin
$inputData = $null
try {
    $stdin = [System.Console]::In.ReadToEnd()
    if ($stdin) {
        $inputData = $stdin | ConvertFrom-Json -ErrorAction Stop
    }
} catch {
    Write-Error "[zo_report_event] Invalid JSON on stdin: $_"
    exit 1
}

if (-not $inputData) {
    Write-Error "[zo_report_event] No input data provided"
    exit 1
}

# Extract event data
$hookEvent = $inputData.hook_event_name -or ""
$sessionId = $inputData.session_id -or ""
$cwd = $inputData.cwd -or ""
$transcriptPath = $inputData.transcript_path -or ""
$toolName = $inputData.tool_name -or ""
$toolUseId = $inputData.tool_use_id -or ""
$permissionMode = $inputData.permission_mode -or ""
$prompt = $inputData.prompt -or ""
$notificationType = $inputData.notification_type -or ""
$stopHookActive = $inputData.stop_hook_active -or $false

# Build event envelope
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$event = @{
    ts = $timestamp
    hook_event_name = $hookEvent
    session_id = $sessionId
    cwd = $cwd
    transcript_path = $transcriptPath
    tool_name = $toolName
    tool_use_id = $toolUseId
    permission_mode = $permissionMode
    prompt = $prompt
    notification_type = $notificationType
    stop_hook_active = $stopHookActive
    source = @{
        remote = ($env:CLAUDE_CODE_REMOTE -eq "true")
        project_dir = $env:CLAUDE_PROJECT_DIR
        host = $env:COMPUTERNAME
    }
    payload = $inputData
}

# 1) Local JSONL log
try {
    $day = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
    $logFile = Join-Path $LogDir "events-$day.jsonl"
    
    # Ensure directory exists
    $logFileDir = Split-Path $logFile -Parent
    if (-not (Test-Path $logFileDir)) {
        New-Item -ItemType Directory -Path $logFileDir -Force | Out-Null
    }
    
    # Append to log file
    $eventJson = $event | ConvertTo-Json -Depth 10 -Compress
    Add-Content -Path $logFile -Value $eventJson -Encoding UTF8
} catch {
    Write-Error "[zo_report_event] File log error: $_"
}

# 2) Optional HTTP endpoint
if ($EventEndpoint) {
    try {
        $body = $event | ConvertTo-Json -Depth 10 -Compress
        $headers = @{
            "Content-Type" = "application/json"
        }
        
        Invoke-RestMethod -Uri $EventEndpoint -Method Post -Body $body -Headers $headers -TimeoutSec $TimeoutSeconds | Out-Null
    } catch {
        Write-Error "[zo_report_event] HTTP error: $_"
    }
}

# 3) Optional structured output back to Claude Code
$output = $null

# For UserPromptSubmit: inject a tiny status line as additional context
if ($hookEvent -eq "UserPromptSubmit") {
    $output = @{
        hookSpecificOutput = @{
            hookEventName = "UserPromptSubmit"
            additionalContext = "[zo-log] Session $($sessionId -or 'unknown') prompt logged at $timestamp (cwd=$cwd)."
        }
    }
}
# For PostToolUse: let Claude know we logged this tool call
elseif ($hookEvent -eq "PostToolUse") {
    $output = @{
        hookSpecificOutput = @{
            hookEventName = "PostToolUse"
            additionalContext = "[zo-log] Logged tool '$toolName' use_id=$($toolUseId -or 'n/a') for session $($sessionId -or 'unknown')."
        }
    }
}
# For SessionStart: inject a one-line "session opened" banner into context
elseif ($hookEvent -eq "SessionStart") {
    $output = @{
        hookSpecificOutput = @{
            hookEventName = "SessionStart"
            additionalContext = "[zo-log] Session $($sessionId -or 'unknown') started at $timestamp (cwd=$cwd). Events are being streamed to Zo/Chroma."
        }
    }
}

if ($output) {
    $output | ConvertTo-Json -Depth 10 -Compress
}

# Exit 0 -> no blocking, JSON (if any) is processed normally
exit 0