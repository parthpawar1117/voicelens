# Start everything for local VoiceLens development, each in its own window.
#   Right-click > Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
# Close a window to stop that part. Then open http://127.0.0.1:8800

$root = $PSScriptRoot
$py = Join-Path $root 'server\.venv\Scripts\python.exe'

function Start-Part($title, $dir, $command) {
    Start-Process powershell -WorkingDirectory $dir -ArgumentList '-NoExit', '-Command',
        "`$Host.UI.RawUI.WindowTitle = '$title'; `$env:PYTHONIOENCODING = 'utf-8'; $command"
}

Start-Part 'VoiceLens server (Telegram + Whisper + inbox)' $root "& '$py' -u server\run.py"
Start-Part 'VoiceLens glasses app (Vite :5173)' (Join-Path $root 'g2-app') 'npx vite --port 5173 --strictPort'
Start-Part 'VoiceLens dashboard (:8800)' $root "& '$py' server\devtools\dashboard.py"

Write-Host 'Waiting for the glasses app before opening the simulator...'
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-WebRequest 'http://localhost:5173' -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
}
Start-Part 'VoiceLens simulator' (Join-Path $root 'g2-app') 'npx evenhub-simulator --automation-port 9898 http://localhost:5173'

Start-Sleep 3
Start-Process 'http://127.0.0.1:8800'
Write-Host 'Started. The server needs ~20 s to warm up Whisper and load recent messages.'
