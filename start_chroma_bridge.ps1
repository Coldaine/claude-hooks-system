Write-Host "Starting Chroma Bridge Server..."
$env:PYTHONUTF8=1
& .\.venv\Scripts\python.exe chroma_bridge_server.py
