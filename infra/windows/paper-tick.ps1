# One paper trading tick (ADR 0016): processes the H4 bars closed since the last run.
# Used by the "ITP-PaperTick" scheduled task every 5 minutes (see register-paper-task.ps1).
# -SrcDir runs code from another checkout (e.g. an unmerged worktree) via PYTHONPATH.
param(
    [string]$RepoDir = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$SrcDir = "",
    [string]$LogDir = "$env:LOCALAPPDATA\itp\logs"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir ("paper-tick-{0:yyyy-MM}.log" -f (Get-Date))

Set-Location $RepoDir  # .env and data/paper/ are resolved relative to the repo
if ($SrcDir) { $env:PYTHONPATH = $SrcDir }
"$(Get-Date -Format s) tick" | Out-File -Append -Encoding utf8 $log
# Redirect inside cmd.exe (see start-crucix.ps1 for why).
cmd.exe /d /c "`"$RepoDir\.venv\Scripts\python.exe`" -m trading_system.cli paper tick >> `"$log`" 2>&1"
exit $LASTEXITCODE
