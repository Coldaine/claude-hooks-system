Write-Host "Starting Chroma Bridge Server v2.0..."
$env:PYTHONUTF8=1

# Check if we should use v2
$useV2 = $env:USE_BRIDGE_V2
if (-not $useV2) { $useV2 = "true" }

if ($useV2 -eq "true") {
    Write-Host "Using v2 (multi-threaded, partitioned collections)"
    & .\.venv\Scripts\python.exe chroma_bridge_server_v2.py
} else {
    Write-Host "Using v1 (legacy single-threaded)"
    & .\.venv\Scripts\python.exe chroma_bridge_server.py
}
