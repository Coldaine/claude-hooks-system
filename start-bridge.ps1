#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start the Chroma Bridge Server for Claude hooks system
.DESCRIPTION
    Starts the bridge server in the background and verifies it's running.
    The bridge connects to Chroma Cloud and accepts events from hooks.
#>

param(
    [switch]$Foreground,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$BridgeDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $BridgeDir "bridge.pid"
$LogFile = Join-Path $BridgeDir "bridge.log"

function Stop-Bridge {
    Write-Host "Stopping Chroma Bridge Server..."

    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile
        try {
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process) {
                Stop-Process -Id $pid -Force
                Write-Host "[OK] Bridge server stopped (PID: $pid)"
            } else {
                Write-Host "[WARN] No process found with PID $pid"
            }
        } catch {
            Write-Host "[WARN] Failed to stop process: $_"
        }
        Remove-Item $PidFile -Force
    } else {
        Write-Host "[INFO] Bridge server not running (no PID file)"
    }
}

function Test-BridgeRunning {
    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile
        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "[INFO] Bridge already running (PID: $pid)"

            # Test health endpoint
            try {
                $health = Invoke-RestMethod -Uri "http://localhost:9000/health" -TimeoutSec 2
                Write-Host "[OK] Bridge is healthy"
                Write-Host "      Collections: events=$($health.collections.events), artifacts=$($health.collections.artifacts)"
                return $true
            } catch {
                Write-Host "[WARN] Bridge process exists but not responding to health checks"
                return $false
            }
        }
    }
    return $false
}

# Handle -Stop flag
if ($Stop) {
    Stop-Bridge
    exit 0
}

# Check if already running
if (Test-BridgeRunning) {
    Write-Host ""
    Write-Host "Bridge server is already running and healthy."
    Write-Host "Use -Stop to stop it, or check logs at: $LogFile"
    exit 0
}

Write-Host "=" * 60
Write-Host "Starting Chroma Bridge Server"
Write-Host "=" * 60

# Check for .env file
$EnvFile = Join-Path $BridgeDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[ERROR] .env file not found at: $EnvFile"
    Write-Host "        Please create .env with Chroma Cloud credentials"
    Write-Host ""
    Write-Host "Example .env:"
    Write-Host "  USE_CHROMA_CLOUD=true"
    Write-Host "  CHROMA_API_KEY=ck-..."
    Write-Host "  CHROMA_TENANT=your-tenant-id"
    Write-Host "  CHROMA_DATABASE=ClaudeCallHome"
    exit 1
}

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python found: $pythonVersion"
} catch {
    Write-Host "[ERROR] Python not found in PATH"
    Write-Host "        Install Python 3.8+ and ensure it's in PATH"
    exit 1
}

# Check dependencies
Write-Host "Checking dependencies..."
$missingDeps = @()
@("chromadb", "python-dotenv") | ForEach-Object {
    $result = python -c "import $_" 2>&1
    if ($LASTEXITCODE -ne 0) {
        $missingDeps += $_
    }
}

if ($missingDeps.Count -gt 0) {
    Write-Host "[WARN] Missing dependencies: $($missingDeps -join ', ')"
    Write-Host "       Installing..."
    python -m pip install $missingDeps --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies"
        exit 1
    }
    Write-Host "[OK] Dependencies installed"
}

# Start bridge server
Write-Host ""
Write-Host "Starting bridge server..."

if ($Foreground) {
    # Run in foreground (for debugging)
    Write-Host "[INFO] Running in foreground mode (Ctrl+C to stop)"
    Write-Host ""
    python (Join-Path $BridgeDir "chroma_bridge_server_v2.py")
} else {
    # Run in background
    $job = Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        python "chroma_bridge_server_v2.py"
    } -ArgumentList $BridgeDir

    # Save PID
    $job.Id | Out-File $PidFile -Encoding ASCII

    Write-Host "[OK] Bridge server started (Job ID: $($job.Id))"
    Write-Host "     PID file: $PidFile"
    Write-Host "     Logs: $LogFile"

    # Wait for server to start
    Write-Host ""
    Write-Host "Waiting for server to be ready..."
    $maxAttempts = 10
    $attempt = 0
    $ready = $false

    while ($attempt -lt $maxAttempts) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:9000/health" -TimeoutSec 2
            Write-Host "[OK] Bridge server is ready!"
            Write-Host ""
            Write-Host "Status: $($health.status)"
            Write-Host "Collections:"
            Write-Host "  - events: $($health.collections.events) documents"
            Write-Host "  - artifacts: $($health.collections.artifacts) documents"
            Write-Host "  - embeddings: $($health.collections.embeddings) documents"
            Write-Host "  - agent_state: $($health.collections.agent_state) documents"
            $ready = $true
            break
        } catch {
            $attempt++
            Write-Host "." -NoNewline
        }
    }

    if (-not $ready) {
        Write-Host ""
        Write-Host "[ERROR] Bridge server failed to start or not responding"
        Write-Host "        Check logs at: $LogFile"
        Stop-Bridge
        exit 1
    }

    Write-Host ""
    Write-Host "=" * 60
    Write-Host "Chroma Bridge Server Running"
    Write-Host "=" * 60
    Write-Host "Endpoint: http://localhost:9000"
    Write-Host "Health:   http://localhost:9000/health"
    Write-Host "Metrics:  http://localhost:9000/metrics"
    Write-Host ""
    Write-Host "Hooks will now send events to Chroma Cloud!"
    Write-Host ""
    Write-Host "To stop: .\start-bridge.ps1 -Stop"
}
