<#
One-command run on this VM: get the code, run every pipeline stage, build the UI, publish it and serve it.

  .\deploy\windows\run_local.ps1 -EnvName dev -Variant default -RepoUrl <git-url> -Branch develop -DocsDir C:\knowledge-hub\docs

Without -RepoUrl the current working copy is copied and used instead of a git clone.
#>
param(
    [ValidateSet("dev", "uat")][string]$EnvName = "dev",
    [ValidatePattern('^[a-z0-9_-]+$')][string]$Variant = "default",
    [string]$RepoUrl = "",
    [string]$Branch = "develop",
    [string]$DocsDir = "C:\knowledge-hub\docs",
    [string]$WorkDir = "C:\knowledge-hub\work",
    [string]$Base = "C:\knowledge-hub\www"
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$repo = Join-Path $WorkDir "repo"

if ($RepoUrl) {
    if (Test-Path "$repo\.git") {
        git -C $repo fetch --prune origin
        git -C $repo checkout -q $Branch
        git -C $repo reset -q --hard "origin/$Branch"
        git -C $repo clean -fdq
    }
    else {
        New-Item -ItemType Directory -Force $WorkDir | Out-Null
        git clone --branch $Branch $RepoUrl $repo
    }
    if ($LASTEXITCODE -ne 0) { throw "git failed" }
    $sha = (git -C $repo rev-parse HEAD).Trim()
}
else {
    $source = (Resolve-Path (Join-Path $here "..\..")).Path
    New-Item -ItemType Directory -Force $repo | Out-Null
    robocopy $source $repo /MIR /XD node_modules .venv dist .git "$repo\.venv" "$repo\Knowledge_Hub_Build_Pipeline_4\Knowledge Hub Tool\node_modules" /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
    $sha = [guid]::NewGuid().ToString("N") + "00000000"
}

& "$repo\deploy\windows\start_server.ps1" -Base $Base
& "$repo\deploy\windows\build.ps1" -RepoRoot $repo -DocsDir $DocsDir
$dist = Join-Path $repo "Knowledge_Hub_Build_Pipeline_4\Knowledge Hub Tool\dist"
& "$repo\deploy\windows\deploy.ps1" -EnvName $EnvName -Variant $Variant -Site $dist -Sha $sha -Base $Base

$port = if ($EnvName -eq "uat") { 8080 } else { 8081 }
Write-Host ""
Write-Host "UI:      http://<this-vm>:$port/$Variant/"
Write-Host "Reports: http://<this-vm>:$port/$Variant/reports/"
Write-Host "OpenAPI: http://<this-vm>:$port/$Variant/openapi/"
