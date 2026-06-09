$ErrorActionPreference = "Stop"

$Workspace = $env:OPENCLAW_WORKSPACE
if (-not $Workspace) {
  $Workspace = Join-Path $HOME ".openclaw\workspace"
}

$Python = "python"
$Scripts = Join-Path $Workspace "scripts"
$Daemon = Join-Path $Scripts "afterglow_daemon.py"
$Pulse = Join-Path $Scripts "pulse.py"

if (-not (Test-Path -LiteralPath $Daemon)) {
  throw "afterglow_daemon.py not found at $Daemon"
}
if (-not (Test-Path -LiteralPath $Pulse)) {
  throw "pulse.py not found at $Pulse"
}

$env:OPENCLAW_WORKSPACE = $Workspace
$env:OPENCLAW_STATE_DIR = Split-Path -Parent $Workspace

$daemonAction = New-ScheduledTaskAction -Execute $Python -Argument "`"$Daemon`" --interval 5" -WorkingDirectory $Workspace
$daemonTrigger = New-ScheduledTaskTrigger -AtLogOn
$daemonSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask -TaskName "AfterglowIngestDaemon" -Action $daemonAction -Trigger $daemonTrigger -Settings $daemonSettings -Force | Out-Null

$pulseAction = New-ScheduledTaskAction -Execute $Python -Argument "`"$Pulse`" --once" -WorkingDirectory $Workspace
$pulseTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$pulseSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "AfterglowPulse" -Action $pulseAction -Trigger $pulseTrigger -Settings $pulseSettings -Force | Out-Null

Write-Output "Installed Windows tasks:"
Write-Output "  AfterglowIngestDaemon -> $Daemon"
Write-Output "  AfterglowPulse -> $Pulse"
