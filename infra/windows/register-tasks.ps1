# Registers two per-user scheduled tasks that start at logon:
#   ITP-Crucix         -> start-crucix.ps1
#   ITP-MacroRecorder  -> start-macro-recorder.ps1
# No admin rights needed. Remove with:  .\register-tasks.ps1 -Unregister
param([switch]$Unregister)

$ErrorActionPreference = "Stop"
$names = @("ITP-Crucix", "ITP-MacroRecorder")

if ($Unregister) {
    foreach ($n in $names) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
    }
    "unregistered: $($names -join ', ')"
    exit 0
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable

$scripts = @{
    "ITP-Crucix"        = "$PSScriptRoot\start-crucix.ps1"
    "ITP-MacroRecorder" = "$PSScriptRoot\start-macro-recorder.ps1"
}

foreach ($n in $names) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$($scripts[$n])`""
    Register-ScheduledTask -TaskName $n -Trigger $trigger -Action $action -Settings $settings `
        -Description "Intelligence Trading Platform: $n" -Force | Out-Null
    "registered: $n"
}
