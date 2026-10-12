# Starts Crucix (pinned checkout) and keeps a rolling log.
# Used by the "ITP-Crucix" scheduled task (see register-tasks.ps1).
param(
    [string]$CrucixDir = "$env:USERPROFILE\Desktop\Crucix",
    [string]$LogDir = "$env:LOCALAPPDATA\itp\logs"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir ("crucix-{0:yyyy-MM-dd}.log" -f (Get-Date))

# Avoid a second instance fighting for port 3117.
$busy = Get-NetTCPConnection -LocalPort 3117 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    "$(Get-Date -Format s) port 3117 already in use, not starting" | Out-File -Append $log
    exit 0
}

Set-Location $CrucixDir
"$(Get-Date -Format s) starting Crucix" | Out-File -Append -Encoding utf8 $log
# Redirect inside cmd.exe: in Windows PowerShell 5.1, redirecting a native program's
# stderr turns each line into an error record, which with "Stop" kills the script (and node).
cmd.exe /d /c "node server.mjs >> `"$log`" 2>&1"
exit $LASTEXITCODE
