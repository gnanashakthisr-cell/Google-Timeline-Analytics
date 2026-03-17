# Simplified Launcher: Google Timeline Analytics
$ErrorActionPreference = "SilentlyContinue"

Write-Host "--- Stage 1: Environment Cleanup ---" -ForegroundColor Cyan
$port = 8501
$pids = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
foreach ($p in $pids) {
    if ($p) {
        Write-Host "Releasing port $port (Process $p)..."
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Write-Host "`n--- Stage 2: Launching Dashboard ---" -ForegroundColor Cyan
py -3.11 -m streamlit run d:\health\app.py
