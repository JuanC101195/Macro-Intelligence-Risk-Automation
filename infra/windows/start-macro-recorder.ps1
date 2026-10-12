# Records a Crucix snapshot every 15 minutes into research/macro_snapshots/.
# Used by the "ITP-MacroRecorder" scheduled task (see register-tasks.ps1).
param(
    [string]$RepoDir = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [int]$IntervalMinutes = 15,
    [string]$LogDir = "$env:LOCALAPPDATA\itp\logs"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir ("macro-recorder-{0:yyyy-MM-dd}.log" -f (Get-Date))

# Wait (up to 10 min) until Crucix serves /api/data (200), so the first snapshot is not empty.
# /api/health answers earlier, while /api/data still returns 503 during startup.
$deadline = (Get-Date).AddMinutes(10)
do {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3117/api/data" -TimeoutSec 10
        $ok = $resp.StatusCode -eq 200
    }
    catch { $ok = $false }
    if (-not $ok) { Start-Sleep -Seconds 15 }
} while (-not $ok -and (Get-Date) -lt $deadline)

Set-Location $RepoDir  # .env and research/ are resolved relative to the repo
"$(Get-Date -Format s) starting macro recorder (crucix healthy: $ok)" | Out-File -Append -Encoding utf8 $log
# Redirect inside cmd.exe (see start-crucix.ps1 for why).
cmd.exe /d /c "`"$RepoDir\.venv\Scripts\trading-system.exe`" macro record --interval-minutes $IntervalMinutes >> `"$log`" 2>&1"
exit $LASTEXITCODE
