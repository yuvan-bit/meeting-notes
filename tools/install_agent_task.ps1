param(
    [switch]$Uninstall,
    [int]$IntervalMinutes = 2
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
$taskName = "MeetingNotesCloudAgent"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$taskName'."
    exit 0
}

$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Missing pythonw: $pythonw"
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m app.cloud_agent run --once" -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon, $repeat) -Settings $settings -Principal $principal -Description "Meeting notes cloud agent: check the queue every $IntervalMinutes minutes when the PC is idle" -Force | Out-Null

Write-Host "Registered scheduled task '$taskName' (one-shot run every $IntervalMinutes minutes)."
Write-Host "Python: $pythonw"
Write-Host "Uninstall: powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1 -Uninstall"
