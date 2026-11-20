<#
.SYNOPSIS
  Start the whole demo (API + web, plus Ollama in local AI mode) with one command.

.DESCRIPTION
  First run: creates .venv and installs the API requirements, runs `npm ci` in apps/web and
  builds data/demo.db (from data/raw if present, else synthetic). Later runs skip all of that.
  API and web run in the background; their PIDs go to data/demo.pids and their logs to
  data/logs/. Stop them with stop-demo.

  Environment overrides (also read from .env; already-set variables win):
    DEMO_VENV      path to an existing venv to use instead of .venv (no creation, no installs)
    AI_MODE        cloud | local | off   (local starts `ollama serve` when needed)
    DATABASE_URL   default sqlite:///data/demo.db

.EXAMPLE
  .\run-demo.cmd
  .\run-demo.ps1 -Mock -NoBrowser
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173,
    [switch]$Synthetic,   # build a synthetic DB if the DB is missing, even when data\raw exists
    [switch]$Mock,        # web uses contract fixtures instead of the API
    [switch]$NoBrowser
)

. (Join-Path $PSScriptRoot 'infra\demo\demo-lib.ps1')
$started = Get-Date
Set-Location -LiteralPath $RepoRoot

# Already running?
$alive = @(Read-DemoPids | Where-Object { Test-DemoProcessAlive $_ })
if ($alive.Count -gt 0) {
    Write-Warn2 "the demo is already running (PIDs $(($alive | ForEach-Object { $_.Id }) -join ', ')). Run stop-demo first."
    exit 1
}
if (Test-Path -LiteralPath $PidFile) { Remove-Item -LiteralPath $PidFile -Force }

Write-Step "Loading .env"
Import-DotEnv

# One heavy step at a time (2-core laptop): venv/pip, then npm, then the DB.
$py = Initialize-Venv
Initialize-NodeModules

$dbPath = Get-SqlitePath
if ($dbPath -and -not (Test-Path -LiteralPath $dbPath)) {
    Build-DemoDb $py $Synthetic.IsPresent
}

# ---- Ollama (local AI mode only)
$aiMode = (Get-EnvOr 'AI_MODE' 'cloud').Trim().ToLower()
if ($aiMode -eq 'local') {
    $ollamaBase = (Get-EnvOr 'OLLAMA_URL' 'http://localhost:11434/v1') -replace '/v1/?$', ''
    if (Test-Url "$ollamaBase/api/tags") {
        Write-Ok "Ollama already running at $ollamaBase"
    } elseif (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-Step "Starting ollama serve"
        $o = Start-DemoProcess 'ollama' (Get-Command ollama).Source @('serve') $RepoRoot
        if (-not (Wait-Url "$ollamaBase/api/tags" 20 $o)) { Write-Warn2 "Ollama did not answer; the AI will fall back to deterministic text" }
    } else {
        Write-Warn2 "AI_MODE=local but Ollama is not installed; the AI will fall back to deterministic text"
    }
}

# ---- API
$webOrigin = "http://localhost:$WebPort"
if ((Get-EnvOr 'CORS_ORIGINS' '') -eq '') { $env:CORS_ORIGINS = "$webOrigin,http://127.0.0.1:$WebPort" }
$env:PYTHONPATH = Join-Path $RepoRoot 'apps\api'
$apiUrl = "http://localhost:$ApiPort"
Write-Step "Starting API on $apiUrl"
$api = Start-DemoProcess 'api' $py @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'apps/api', '--host', '127.0.0.1', '--port', "$ApiPort") $RepoRoot

# ---- Web (Vite dev server, run with node directly rather than through npm)
$webDir = Join-Path $RepoRoot 'apps\web'
$node = (Get-Command node -ErrorAction Stop).Source
$viteArgs = @('node_modules/vite/bin/vite.js', '--port', "$WebPort", '--strictPort')
if ($Mock) {
    $env:VITE_API_MODE = 'mock'
} else {
    $env:VITE_API_MODE = 'live'
    $env:VITE_API_URL = $apiUrl
    $viteArgs += @('--mode', 'live')
}
Write-Step "Starting web on $webOrigin ($env:VITE_API_MODE mode)"
$web = Start-DemoProcess 'web' $node $viteArgs $webDir

# ---- Wait until both answer
if (-not (Wait-Url "$apiUrl/api/health" 90 $api)) {
    Write-Warn2 "API did not become healthy; see data\logs\api.log"
    Stop-DemoProcesses
    exit 1
}
Write-Ok "API healthy: $apiUrl/api/health"
if (-not (Wait-Url $webOrigin 60 $web)) {
    Write-Warn2 "web server did not answer; see data\logs\web.log"
    Stop-DemoProcesses
    exit 1
}
Write-Ok "web ready: $webOrigin"

if (-not $NoBrowser) { Start-Process $webOrigin }

$secs = [int]((Get-Date) - $started).TotalSeconds
Write-Host ""
Write-Host "Demo is running ($secs s)." -ForegroundColor Green
Write-Host "  Web:      $webOrigin"
Write-Host "  API:      $apiUrl   (docs: $apiUrl/docs)"
Write-Host "  AI mode:  $aiMode"
Write-Host "  Logs:     data\logs\   PIDs: data\demo.pids"
Write-Host "  Stop:     .\stop-demo.cmd"
exit 0
