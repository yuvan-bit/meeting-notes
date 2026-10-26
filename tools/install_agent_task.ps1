param(
    [switch]$Uninstall,
    [int]$IntervalMinutes = 2
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
$taskName = "MeetingNotesCloudAgent"
$ollamaTaskName = "OllamaKeepAlive"
$keepaliveSource = Join-Path $PSScriptRoot "ollama-keepalive.vbs"
$keepaliveDir = Join-Path $env:LOCALAPPDATA "MeetingNotes"
$keepaliveTarget = Join-Path $keepaliveDir "ollama-keepalive.vbs"
$oldKeepaliveTarget = Join-Path $keepaliveDir "ollama-keepalive.cmd"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $ollamaTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $keepaliveTarget -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $oldKeepaliveTarget -Force -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled tasks '$taskName' and '$ollamaTaskName'."
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

if (Test-Path -LiteralPath $keepaliveSource) {
    New-Item -ItemType Directory -Force -Path $keepaliveDir | Out-Null
    Copy-Item -LiteralPath $keepaliveSource -Destination $keepaliveTarget -Force
    Remove-Item -LiteralPath $oldKeepaliveTarget -Force -ErrorAction SilentlyContinue
    $ollamaAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" -Argument ('//B //Nologo "' + $keepaliveTarget + '"')
    $ollamaRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $ollamaSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $ollamaTaskName -Action $ollamaAction -Trigger @($logon, $ollamaRepeat) -Settings $ollamaSettings -Principal $principal -Description "Start Ollama if it is not running so the meeting-notes agent can summarize recordings" -Force | Out-Null
}

Write-Host "Registered scheduled task '$taskName' (one-shot run every $IntervalMinutes minutes)."
Write-Host "Registered scheduled task '$ollamaTaskName' (Ollama keepalive every 5 minutes)."
Write-Host "Python: $pythonw"
Write-Host "Uninstall: powershell -ExecutionPolicy Bypass -File tools\install_agent_task.ps1 -Uninstall"
