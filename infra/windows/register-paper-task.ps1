# Registers the per-user "ITP-PaperTick" task: one paper tick every 5 minutes while logged on
# (MT5 needs the interactive session). No admin rights needed.
# Remove with:  .\register-paper-task.ps1 -Unregister
param(
    [switch]$Unregister,
    [string]$RepoDir = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$SrcDir = ""
)

$ErrorActionPreference = "Stop"
$name = "ITP-PaperTick"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    "unregistered: $name"
    exit 0
}

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$script = "$PSScriptRoot\paper-tick.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -RepoDir `"$RepoDir`""
if ($SrcDir) { $arguments += " -SrcDir `"$SrcDir`"" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
Register-ScheduledTask -TaskName $name -Trigger $trigger -Action $action -Settings $settings `
    -Description "Intelligence Trading Platform: paper tick (ADR 0016), no orders sent" -Force | Out-Null
"registered: $name (every 5 min, repo $RepoDir)"
