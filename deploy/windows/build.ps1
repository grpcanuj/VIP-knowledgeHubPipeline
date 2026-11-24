<#
Builds the Knowledge Hub from a checked-out repo: Python pipeline stages, then the UI.
Output: <RepoRoot>\Knowledge_Hub_Build_Pipeline_4\Knowledge Hub Tool\dist (with reports\ and openapi\ inside).
#>
param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [string]$DocsDir = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$pipeline = Join-Path $RepoRoot "Knowledge_Hub_Build_Pipeline_4\Knowledge_Hub_Build_Pipeline_4"
$ui = Join-Path $RepoRoot "Knowledge_Hub_Build_Pipeline_4\Knowledge Hub Tool"
$venv = Join-Path $RepoRoot ".venv"

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path "$venv\Scripts\python.exe")) {
    $sysPython = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }
    Invoke-Native $sysPython @("-m", "venv", $venv)
}
$python = "$venv\Scripts\python.exe"

Write-Host "== Install pipeline dependencies"
Invoke-Native $python @("-m", "pip", "install", "-q", "-r", "$pipeline\requirements.txt")

Push-Location $pipeline
try {
    $pipelineArgs = @("scripts/run_pipeline.py", "--ui-dir", $ui)
    if ($DocsDir -and (Test-Path $DocsDir)) { $pipelineArgs += @("--docs-dir", $DocsDir) }
    elseif ($DocsDir) { Write-Warning "Docs dir not found: $DocsDir (extract/lint skipped)" }
    Invoke-Native $python $pipelineArgs
}
finally { Pop-Location }

Write-Host "== Build UI"
Push-Location $ui
try {
    Invoke-Native "npm" @("ci")
    Invoke-Native "npm" @("run", "lint")
    Invoke-Native "npm" @("run", "build")
}
finally { Pop-Location }

$dist = Join-Path $ui "dist"
Copy-Item -Recurse -Force "$pipeline\output\reports" "$dist\reports"
Write-Host "Build complete: $dist"
