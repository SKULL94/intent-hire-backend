# Kill whatever is serving the API and start a fresh one.
#
# Usage:
#   .\restart.ps1                # kill, then run in foreground (logs on screen, Ctrl-C stops)
#   .\restart.ps1 -Detach        # kill, then background, logs to .uvicorn.log.err
#   .\restart.ps1 -Stop          # kill only
#   .\restart.ps1 -Port 9000     # different port
#   .\restart.ps1 -NoReload      # disable auto-reload
#
# Self-contained: no other script needed. Safe to run when nothing is running,
# and safe to run repeatedly.

param(
    [int]$Port = 8000,
    [switch]$Detach,
    [switch]$Stop,
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Say  { param($m) Write-Host "> $m" -ForegroundColor Cyan }
function Warn { param($m) Write-Host "! $m" -ForegroundColor Yellow }
function Ok   { param($m) Write-Host "+ $m" -ForegroundColor Green }

# ─── liveness ─────────────────────────────────────────────────────────────────
# Ask the API, don't read netstat. On Windows the port's listed owner can be a
# dead parent whose child still serves the inherited socket, so netstat will
# happily name a PID that no longer exists while the port keeps answering.
function Test-ApiAlive {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

# ─── the killer ───────────────────────────────────────────────────────────────
# Three kinds of process have to die, and matching on "uvicorn" finds only the
# first:
#   1. launchers / reloaders  - command line contains "uvicorn ... app.main"
#   2. whatever holds the port - may differ from (1)
#   3. multiprocessing workers - `uvicorn --reload` spawns these as
#      `python -c "from multiprocessing.spawn import spawn_main; ..."`, so their
#      command line never mentions uvicorn. They keep serving the inherited
#      socket after their parent exits. This is the one that survives naive
#      kills and makes a port answer HTTP 200 with no visible owner.
function Stop-ApiProcesses {
    $self = $PID
    $procs = Get-CimInstance Win32_Process
    $seed = New-Object System.Collections.Generic.HashSet[int]

    # (1) anything launching this app
    $procs |
        Where-Object { $_.CommandLine -and $_.CommandLine -like '*uvicorn*app.main*' } |
        ForEach-Object { [void]$seed.Add([int]$_.ProcessId) }

    # (2) whoever is bound to the port (may already be dead, still a useful key)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { [void]$seed.Add([int]$_.OwningProcess) }

    # (3) descendants, plus orphans that still name a seed PID as their parent.
    # Repeat so grandchildren get picked up once their parent joins the set.
    for ($pass = 0; $pass -lt 5; $pass++) {
        $before = $seed.Count
        foreach ($p in $procs) {
            if ($seed.Contains([int]$p.ProcessId)) { continue }
            if ($seed.Contains([int]$p.ParentProcessId)) {
                [void]$seed.Add([int]$p.ProcessId)
                continue
            }
            # A dead parent breaks the ParentProcessId link, but spawn_main
            # records the original parent PID in its own command line.
            if ($p.CommandLine -and $p.CommandLine -like '*spawn_main*') {
                foreach ($s in $seed) {
                    if ($p.CommandLine -like "*parent_pid=$s*") {
                        [void]$seed.Add([int]$p.ProcessId)
                        break
                    }
                }
            }
        }
        if ($seed.Count -eq $before) { break }
    }

    [void]$seed.Remove($self)
    if ($seed.Count -eq 0) {
        Write-Host '    nothing to kill'
        return
    }

    # Children first, so a reloader parent cannot respawn a worker mid-sweep.
    $targets = $procs |
        Where-Object { $seed.Contains([int]$_.ProcessId) } |
        Sort-Object -Property ParentProcessId -Descending

    foreach ($p in $targets) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host ("    killed {0}" -f $p.ProcessId)
        } catch {
            if (Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue) {
                Write-Host ("    FAILED {0}: {1}" -f $p.ProcessId, $_.Exception.Message)
            } else {
                Write-Host ("    already exited {0}" -f $p.ProcessId)
            }
        }
    }
}

# ─── locate the interpreter ───────────────────────────────────────────────────
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Warn "No virtualenv at .venv - create one, or run scripts/dev.sh first."
    exit 1
}

# ─── stop ─────────────────────────────────────────────────────────────────────
if (Test-ApiAlive) {
    Say "Server is responding on port $Port - shutting it down"
} else {
    Say "No server responding on port $Port (sweeping for orphans anyway)"
}

for ($attempt = 1; $attempt -le 3; $attempt++) {
    Stop-ApiProcesses
    Start-Sleep -Seconds 2
    if (-not (Test-ApiAlive)) { break }
    Say "Still responding after attempt $attempt; retrying"
}

if (Test-ApiAlive) {
    Warn "Something is still serving port $Port and would not die. Inspect with:"
    Warn "  Get-CimInstance Win32_Process | Where-Object { `$_.CommandLine -like '*uvicorn*' } | Select ProcessId,CommandLine"
    exit 1
}
Ok "Port $Port is clear"

if ($Stop) {
    Ok "Stopped. Not restarting (-Stop)."
    exit 0
}

# ─── sanity-check config before booting ───────────────────────────────────────
if (-not (Test-Path (Join-Path $root '.env'))) {
    Warn "No .env file - app/config.py falls back to a localhost DATABASE_URL and will fail."
    exit 1
}

$uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', "$Port")
if (-not $NoReload) { $uvicornArgs += '--reload' }

# ─── start ────────────────────────────────────────────────────────────────────
if ($Detach) {
    $outLog = Join-Path $root '.uvicorn.log'
    $errLog = Join-Path $root '.uvicorn.log.err'
    Say "Starting detached"
    # Start-Process cannot send both streams to one file; uvicorn writes its
    # startup banner and access log to stderr, so .err is the interesting one.
    $proc = Start-Process -FilePath $py -ArgumentList $uvicornArgs `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -WindowStyle Hidden -PassThru

    for ($i = 0; $i -lt 30; $i++) {
        if (Test-ApiAlive) {
            Ok "Server up on http://localhost:$Port  (PID $($proc.Id))"
            Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" | ConvertTo-Json -Compress
            Ok "Logs:  Get-Content .uvicorn.log.err -Tail 20 -Wait"
            Ok "Stop:  .\restart.ps1 -Stop"
            exit 0
        }
        if ($proc.HasExited) {
            Warn "Server exited during startup. Last lines:"
            if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
            exit 1
        }
        Start-Sleep -Seconds 1
    }
    Warn "Server did not answer /health within 30s. Last lines:"
    if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
    exit 1
}
else {
    Say "Starting on http://localhost:$Port  (Ctrl-C to stop)"
    & $py @uvicornArgs
}
