<#
.SYNOPSIS
  Reset for a rehearsal: stop the demo, rebuild data\demo.db and the chat RAG index.

.DESCRIPTION
  The DB is rebuilt with core.etl.build_demo_db (drops and recreates every table) from data\raw,
  or synthetic data with -Synthetic / when data\raw is missing. The RAG index (data\rag\, see
  apps/api/chat/rag.py) is cleared and rebuilt: semantic vectors when fastembed is installed
  (apps/api/requirements-ai.txt), otherwise the keyword (BM25) chunk cache. The downloaded
  embedding model in data\rag\models is kept.
#>
[CmdletBinding()]
param(
    [switch]$Synthetic
)

. (Join-Path $PSScriptRoot 'infra\demo\demo-lib.ps1')
$started = Get-Date
Set-Location -LiteralPath $RepoRoot

Write-Step "Stopping the demo"
Stop-DemoProcesses

Import-DotEnv
$py = Initialize-Venv
Build-DemoDb $py $Synthetic.IsPresent

Write-Step "Rebuilding the RAG index (data\rag)"
$rag = Join-Path $DataDir 'rag'
if (Test-Path -LiteralPath $rag) {
    Get-ChildItem -LiteralPath $rag -File | Remove-Item -Force
}
$hasFastembed = (Invoke-Py $py @('-c', "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('fastembed') else 1)")) -eq 0
if ($hasFastembed) {
    $code = Invoke-Py $py @('-m', 'chat.rag', '--build')
    if ($code -ne 0) { Write-Warn2 "semantic index build failed; chat will use keyword search" }
} else {
    Write-Ok "fastembed not installed (optional: pip install -r apps/api/requirements-ai.txt); building the keyword index"
    $env:CHAT_RAG_MODE = 'keyword'
    $code = Invoke-Py $py @('-m', 'chat.rag', 'client lock')
    Remove-Item Env:\CHAT_RAG_MODE
    if ($code -ne 0) { Write-Warn2 "keyword index build failed; it will be built on first chat question" }
}

$secs = [int]((Get-Date) - $started).TotalSeconds
Write-Host ""
Write-Host "Reset done ($secs s). Start the demo with .\run-demo.cmd" -ForegroundColor Green
exit 0
