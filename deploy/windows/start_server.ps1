<#
Starts the static web server (UAT :8080, Dev :8081) in the background if it is not already running,
and opens the Windows firewall for both ports when run as administrator.
#>
param(
    [string]$Base = "C:\knowledge-hub\www",
    [string]$AppDir = "C:\knowledge-hub"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $AppDir, $Base | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot "serve_static.py") $AppDir

$listening = Get-NetTCPConnection -State Listen -LocalPort 8080, 8081 -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Web server already listening on 8080/8081."
    return
}

$python = if (Get-Command python -ErrorAction SilentlyContinue) { (Get-Command python).Source } else { (Get-Command py).Source }
$serverArgs = "`"$AppDir\serve_static.py`" --base `"$Base`""
# Win32_Process detaches the server from this shell, so pipelines and CI steps do not wait on it.
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "`"$python`" $serverArgs"; CurrentDirectory = $AppDir } | Out-Null

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("Administrator")
if ($isAdmin -and -not (Get-NetFirewallRule -DisplayName "Knowledge Hub" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Knowledge Hub" -Direction Inbound -Protocol TCP -LocalPort 8080, 8081 -Action Allow | Out-Null
}
if ($isAdmin -and -not (Get-ScheduledTask -TaskName "KnowledgeHubWeb" -ErrorAction SilentlyContinue)) {
    $action = New-ScheduledTaskAction -Execute $python -Argument $serverArgs
    Register-ScheduledTask -TaskName "KnowledgeHubWeb" -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -User "SYSTEM" -RunLevel Highest | Out-Null
}
if (-not $isAdmin) {
    Write-Warning "Not administrator: allow TCP 8080/8081 in Windows Firewall and register a startup task (rerun this script once as administrator)."
}
Write-Host "Web server started."
