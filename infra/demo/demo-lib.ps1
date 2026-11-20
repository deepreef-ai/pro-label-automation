# Shared helpers for run-demo.ps1 / reset-demo.ps1 / stop-demo.ps1 (dot-sourced).
# Windows PowerShell 5.1 compatible: no &&, ||, ternary or ?? operators.

$ErrorActionPreference = 'Stop'

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:DataDir = Join-Path $script:RepoRoot 'data'
$script:PidFile = Join-Path $script:DataDir 'demo.pids'
$script:LogDir = Join-Path $script:DataDir 'logs'

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2([string]$msg) { Write-Host "    WARNING: $msg" -ForegroundColor Yellow }

# Load KEY=VALUE pairs from the repo-root .env into this process. Variables that are already
# set in the environment win, so `$env:AI_MODE='off'; .\run-demo.ps1` still works.
function Import-DotEnv {
    $path = Join-Path $script:RepoRoot '.env'
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Warn2 ".env not found; using defaults (copy .env.example to .env and add your keys)"
        return
    }
    foreach ($line in Get-Content -LiteralPath $path) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $k = $t.Substring(0, $i).Trim()
        $v = $t.Substring($i + 1).Trim()
        if ($v.Length -ge 2 -and (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'")))) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($k, 'Process'))) {
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}

function Get-EnvOr([string]$name, [string]$default) {
    $v = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrEmpty($v)) { return $default }
    return $v
}

# Find a Python >= 3.11 to create the venv with.
function Find-BasePython {
    $candidates = @(@('py', '-3.11'), @('py', '-3.12'), @('py', '-3'), @('python'), @('python3'))
    foreach ($c in $candidates) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $cmdArgs = @()
        if ($c.Count -gt 1) { $cmdArgs = $c[1..($c.Count - 1)] }
        try {
            $out = & $c[0] @cmdArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch { continue }
        if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
        $ver = [version]("$out".Trim())
        if ($ver -ge [version]'3.11') { return , $c }
    }
    throw "Python 3.11+ not found. Install it from python.org (tick 'Add to PATH') and re-run."
}

# Returns the venv's python.exe. DEMO_VENV=<path to an existing venv> skips creation and installs.
function Initialize-Venv {
    $override = Get-EnvOr 'DEMO_VENV' ''
    if ($override -ne '') {
        $py = Join-Path $override 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $py)) { throw "DEMO_VENV is set but $py does not exist" }
        Write-Ok "using existing venv from DEMO_VENV: $override"
        return $py
    }
    $venv = Join-Path $script:RepoRoot '.venv'
    $py = Join-Path $venv 'Scripts\python.exe'
    $marker = Join-Path $venv '.demo-installed'
    $req = Join-Path $script:RepoRoot 'apps\api\requirements.txt'
    if (-not (Test-Path -LiteralPath $py)) {
        Write-Step "Creating .venv (first run only)"
        $base = Find-BasePython
        $baseArgs = @()
        if ($base.Count -gt 1) { $baseArgs = $base[1..($base.Count - 1)] }
        & $base[0] @baseArgs -m venv $venv | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
    }
    $needInstall = -not (Test-Path -LiteralPath $marker)
    if (-not $needInstall) {
        $needInstall = (Get-Item -LiteralPath $req).LastWriteTimeUtc -gt (Get-Item -LiteralPath $marker).LastWriteTimeUtc
    }
    if ($needInstall) {
        Write-Step "Installing API requirements (first run only, a few minutes)"
        & $py -m pip install --disable-pip-version-check -q -r $req | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
        Set-Content -LiteralPath $marker -Value (Get-Date -Format o) -Encoding ASCII
    }
    return $py
}

# npm ci only when node_modules is missing or older than package-lock.json.
function Initialize-NodeModules {
    $web = Join-Path $script:RepoRoot 'apps\web'
    $stamp = Join-Path $web 'node_modules\.package-lock.json'
    $lock = Join-Path $web 'package-lock.json'
    $need = -not (Test-Path -LiteralPath $stamp)
    if (-not $need) {
        $need = (Get-Item -LiteralPath $lock).LastWriteTimeUtc -gt (Get-Item -LiteralPath $stamp).LastWriteTimeUtc
    }
    if ($need) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js 20+ (npm) not found on PATH" }
        Write-Step "Installing web dependencies with npm ci (first run only)"
        Push-Location -LiteralPath $web
        try {
            & npm ci --no-audit --no-fund | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        } finally { Pop-Location }
    }
}

# The SQLite file behind DATABASE_URL, or $null for a non-SQLite database.
function Get-SqlitePath {
    $url = Get-EnvOr 'DATABASE_URL' 'sqlite:///data/demo.db'
    if (-not $url.StartsWith('sqlite:///')) { return $null }
    $p = $url.Substring('sqlite:///'.Length)
    if (-not [System.IO.Path]::IsPathRooted($p)) { $p = Join-Path $script:RepoRoot $p }
    return $p
}

function Invoke-Py([string]$py, [string[]]$pyArgs) {
    $old = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $script:RepoRoot 'apps\api'
    Push-Location -LiteralPath $script:RepoRoot
    try {
        & $py @pyArgs | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $env:PYTHONPATH = $old
    }
    return $code
}

function Build-DemoDb([string]$py, [bool]$synthetic) {
    $a = @('-m', 'core.etl.build_demo_db')
    $raw = Join-Path $script:RepoRoot 'data\raw'
    if ($synthetic -or -not (Test-Path -LiteralPath $raw)) {
        $a += '--synthetic'
        Write-Step "Building demo database (synthetic data)"
    } else {
        Write-Step "Building demo database from data\raw"
    }
    $code = Invoke-Py $py $a
    if ($code -ne 0) { throw "core.etl.build_demo_db failed (exit $code)" }
}

# PID file: one line per process, "name pid startTicks". The start time guards against PID reuse.
function Read-DemoPids {
    $out = @()
    if (-not (Test-Path -LiteralPath $script:PidFile)) { return $out }
    foreach ($line in Get-Content -LiteralPath $script:PidFile) {
        $parts = $line.Trim() -split '\s+'
        if ($parts.Count -lt 3) { continue }
        $out += [pscustomobject]@{ Name = $parts[0]; Id = [int]$parts[1]; Ticks = [long]$parts[2] }
    }
    return $out
}

function Add-DemoPid([string]$name, $proc) {
    if (-not (Test-Path -LiteralPath $script:DataDir)) { New-Item -ItemType Directory -Path $script:DataDir | Out-Null }
    $ticks = (Get-Process -Id $proc.Id).StartTime.ToUniversalTime().Ticks
    Add-Content -LiteralPath $script:PidFile -Value "$name $($proc.Id) $ticks" -Encoding ASCII
}

function Test-DemoProcessAlive($entry) {
    $p = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    try { return $p.StartTime.ToUniversalTime().Ticks -eq $entry.Ticks } catch { return $false }
}

function Stop-DemoProcesses {
    $entries = Read-DemoPids
    if ($entries.Count -eq 0) {
        Write-Ok "no demo processes recorded"
        if (Test-Path -LiteralPath $script:PidFile) { Remove-Item -LiteralPath $script:PidFile -Force }
        return
    }
    foreach ($e in $entries) {
        if (Test-DemoProcessAlive $e) {
            # /T stops the whole tree (the venv python.exe launcher spawns the real interpreter).
            & taskkill.exe /PID $e.Id /T /F 2>&1 | Out-Null
            Write-Ok "stopped $($e.Name) (PID $($e.Id))"
        } else {
            Write-Ok "$($e.Name) (PID $($e.Id)) was not running"
        }
    }
    Remove-Item -LiteralPath $script:PidFile -Force
}

function Test-Url([string]$url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch { return $false }
}

function Wait-Url([string]$url, [int]$seconds, $proc) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url $url) { return $true }
        if ($proc -and $proc.HasExited) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Start a background process in its own hidden console, output to data\logs\<name>.log.
# It goes through `cmd /c` with ShellExecute so that no console or pipe handle of the caller is
# inherited: the caller (a double-clicked .cmd, CI, a pipe) can exit while the demo keeps running.
# The recorded PID is that cmd.exe; stop-demo kills it with its whole tree.
function Start-DemoProcess([string]$name, [string]$exe, [string[]]$exeArgs, [string]$workDir) {
    if (-not (Test-Path -LiteralPath $script:LogDir)) { New-Item -ItemType Directory -Path $script:LogDir | Out-Null }
    $log = Join-Path $script:LogDir "$name.log"
    $parts = @('"' + $exe + '"')
    foreach ($a in $exeArgs) {
        if ($a -match '[\s"]') { $parts += '"' + ($a -replace '"', '\"') + '"' } else { $parts += $a }
    }
    $line = '/d /c "' + ($parts -join ' ') + ' > "' + $log + '" 2>&1"'
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList $line -WorkingDirectory $workDir -WindowStyle Hidden -PassThru
    Add-DemoPid $name $p
    return $p
}
