<#
Publishes a built site as a timestamped release and repoints <Base>\<env>\<variant>\current to it.
Rolls back when the web server does not serve this exact build.
#>
param(
    [Parameter(Mandatory)][ValidateSet("dev", "uat")][string]$EnvName,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9_-]+$')][string]$Variant,
    [Parameter(Mandatory)][string]$Site,
    [Parameter(Mandatory)][string]$Sha,
    [string]$Base = "C:\knowledge-hub\www"
)

$ErrorActionPreference = "Stop"
$keep = 5
$port = if ($EnvName -eq "uat") { 8080 } else { 8081 }

$target = Join-Path $Base "$EnvName\$Variant"
$release = Join-Path $target ("releases\{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), $Sha.Substring(0, [Math]::Min(7, $Sha.Length)))
$current = Join-Path $target "current"
$tmp = Join-Path $target "current.tmp"

$previous = $null
if (Test-Path $current) { $previous = @((Get-Item $current).Target)[0] }

New-Item -ItemType Directory -Force $release | Out-Null
Copy-Item -Recurse -Force "$Site\*" $release
"$Variant $Sha" | Set-Content -NoNewline -Encoding ascii (Join-Path $release "version.txt")

function Set-Current([string]$Path) {
    if (Test-Path $tmp) { cmd /c rmdir "`"$tmp`"" | Out-Null }
    New-Item -ItemType Junction -Path $tmp -Target $Path | Out-Null
    if (Test-Path $current) { cmd /c rmdir "`"$current`"" | Out-Null }
    [System.IO.Directory]::Move($tmp, $current)
}
Set-Current $release

$ok = $false
for ($i = 0; $i -lt 6 -and -not $ok; $i++) {
    try {
        $body = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/$Variant/version.txt" -TimeoutSec 5).Content
        if ($body -match [regex]::Escape($Sha)) { $ok = $true }
    }
    catch { Start-Sleep -Seconds 2 }
    if (-not $ok) { Start-Sleep -Seconds 1 }
}

if (-not $ok) {
    Write-Error "Health check failed on port $port for $Variant"
    if ($previous -and (Test-Path $previous)) {
        Set-Current $previous
        Write-Host "Rolled back to $previous"
    }
    exit 1
}

Get-ChildItem (Join-Path $target "releases") -Directory |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip $keep |
    Remove-Item -Recurse -Force

Write-Host "Deployed $($Sha.Substring(0, 7)) to $EnvName/$Variant at http://127.0.0.1:$port/$Variant/"
