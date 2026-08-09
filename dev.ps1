<#
.SYNOPSIS
    Start, stop and restart the whole project with one command.

.DESCRIPTION
    Runs the backend (uvicorn, port 8000) and the frontend (next dev, port 3000)
    as detached background processes and reports when both actually answer.

    Detached on purpose. Started as children of an interactive shell, both servers
    die the moment that shell receives Ctrl-C -- including the Ctrl-C an agent
    session broadcasts when it recycles. Each gets its own console instead, so
    closing the terminal that launched them leaves them running.

    Because they have no visible window, their output goes to .dev-logs/ under
    backend/ and web/. `dev.ps1 logs` is the only way to read it -- which is why a
    failed start prints the tail of the relevant log itself rather than telling you
    to go and look.

    Do not run `pnpm build` while the frontend is up. Both write web/.next, and
    Turbopack's cache does not survive two writers: it stops emitting chunks
    mid-build and every route 500s until the directory is deleted. Stop the servers
    first, or run `dev.ps1 fresh` afterwards.

.EXAMPLE
    .\dev.ps1              # same as start; leaves anything already running alone
    .\dev.ps1 start
    .\dev.ps1 stop
    .\dev.ps1 restart      # after changing backend code, which uvicorn will not reload
    .\dev.ps1 fresh        # restart, deleting web/.next first -- for a broken dev build
    .\dev.ps1 status
    .\dev.ps1 logs
#>

[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'restart', 'fresh', 'status', 'logs')]
    [string]$Command = 'start',

    # Lines of each log to show. `logs` only.
    [int]$Tail = 40
)

$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Web = Join-Path $Root 'web'

# One record per server, so every command below is a loop rather than two
# near-identical branches that drift apart.
$Services = @(
    @{
        Name    = 'backend'
        Port    = 8000
        Dir     = $Backend
        Logs    = Join-Path $Backend '.dev-logs'
        Ready   = 'http://127.0.0.1:8000/health'
        Command = 'uv run uvicorn api.main:app --host 127.0.0.1 --port 8000'
    }
    @{
        Name    = 'frontend'
        Port    = 3000
        Dir     = $Web
        Logs    = Join-Path $Web '.dev-logs'
        Ready   = 'http://127.0.0.1:3000/en/login'
        Command = $null  # decided at start time; see Get-FrontendCommand
    }
)

function Get-Listener {
    <#  PIDs listening on a port. Ports rather than a PID file: a PID file goes
        stale the moment something dies without cleaning up, and then `stop` lies. #>
    param([int]$Port)
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-FrontendCommand {
    <#  `pnpm build` leaves production artefacts in .next that the next `pnpm dev`
        half-reads: the landing page renders and every other route 404s, with no
        error in the log to explain it. Detect that and clear it; otherwise keep the
        warm cache, because dev:clean forces a full recompile every start. #>
    if (Test-Path (Join-Path $Web '.next\BUILD_ID')) {
        Write-Host '  .next holds a production build - clearing it first' -ForegroundColor DarkYellow
        return 'pnpm dev:clean'
    }
    return 'pnpm dev'
}

function Wait-Url {
    <#  Wait for a server to answer, and judge the answer.

        A 404 or a redirect still means the server is up -- something is listening and
        routing, which is all this asks. A refused connection is "not yet", so keep
        waiting.

        A 5xx is neither. It means the server is listening *and broken*, and it used
        to be reported as ready: this function returned $true for any response at all,
        so a frontend serving 500 on every route came up green. Since both servers run
        detached with no window, that green was the only thing anyone saw.

        Returns 'ready', 'broken' or 'silent'. #>
    param([string]$Url, [int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = $null
        try {
            $status = (Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing).StatusCode
        } catch {
            # A non-2xx is an exception here, so the response carries the real status.
            # No response at all means nothing is listening yet.
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        }

        if ($null -ne $status) {
            return $(if ($status -ge 500) { 'broken' } else { 'ready' })
        }
        Start-Sleep -Seconds 2
    }
    return 'silent'
}

function Show-Log {
    <#  The failure is already written down; print it rather than send someone to
        another command to find it. #>
    param($Service, [int]$Lines = 15)

    foreach ($name in 'err.log', 'out.log') {
        $path = Join-Path $Service.Logs $name
        if (-not (Test-Path $path)) { continue }
        $tail = @(Get-Content -Path $path -Tail $Lines -ErrorAction SilentlyContinue)
        if (-not $tail) { continue }
        Write-Host ("`n  --- {0}/{1} ---" -f $Service.Name, $name) -ForegroundColor DarkGray
        $tail | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }
}

function Stop-DevService {
    param($Service)

    $pids = Get-Listener -Port $Service.Port
    if (-not $pids) {
        Write-Host ("  {0,-9} not running" -f $Service.Name) -ForegroundColor DarkGray
        return
    }

    foreach ($procId in $pids) {
        # /T because `next dev` and `uv run` both sit above the process that owns
        # the socket; killing only the listener orphans the parent.
        taskkill /PID $procId /T /F 2>&1 | Out-Null
    }

    foreach ($attempt in 1..10) {
        if (-not (Get-Listener -Port $Service.Port)) {
            Write-Host ("  {0,-9} stopped" -f $Service.Name) -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host ("  {0,-9} still holding port {1}" -f $Service.Name, $Service.Port) -ForegroundColor Red
}

function Start-DevService {
    param($Service)

    if (Get-Listener -Port $Service.Port) {
        Write-Host ("  {0,-9} already on port {1} - leaving it alone" -f $Service.Name, $Service.Port) -ForegroundColor DarkYellow
        return
    }

    New-Item -ItemType Directory -Force -Path $Service.Logs | Out-Null
    $out = Join-Path $Service.Logs 'out.log'
    $err = Join-Path $Service.Logs 'err.log'

    # cmd.exe /c, not the executable directly: pnpm is a .cmd shim, and this gives
    # both servers a console of their own rather than sharing this one's.
    $proc = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', $Service.Command `
        -WorkingDirectory $Service.Dir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -PassThru

    Write-Host ("  {0,-9} launched (pid {1})" -f $Service.Name, $proc.Id) -ForegroundColor DarkGray
}

function Invoke-Start {
    Write-Host "`nMigrating" -ForegroundColor Cyan
    Push-Location $Backend
    try {
        uv run python -m api.migrate | ForEach-Object { "  $_" }

        # Idempotent by design: seed exits 1 and changes nothing once users exist,
        # so a fresh clone comes up populated and an existing one is untouched. That
        # 1 is the normal case here, not a failure -- clear it, or it survives as the
        # script's own exit code and every start looks broken to a caller.
        Write-Host "`nSeeding" -ForegroundColor Cyan
        uv run python -m api.seed 2>&1 | ForEach-Object { "  $_" }
        $global:LASTEXITCODE = 0
    } finally {
        Pop-Location
    }

    Write-Host "`nStarting" -ForegroundColor Cyan
    foreach ($service in $Services) {
        if ($service.Name -eq 'frontend') { $service.Command = Get-FrontendCommand }
        Start-DevService -Service $service
    }

    Write-Host "`nWaiting" -ForegroundColor Cyan
    $failed = @()
    foreach ($service in $Services) {
        switch (Wait-Url -Url $service.Ready) {
            'ready' {
                Write-Host ("  {0,-9} ready" -f $service.Name) -ForegroundColor Green
            }
            'broken' {
                # Listening, and answering 500. For the frontend that is almost always
                # a half-written Turbopack build, which no restart clears -- `fresh`
                # deletes the cache that a plain start would happily reuse.
                Write-Host ("  {0,-9} answered 500 - it is up and broken" -f $service.Name) -ForegroundColor Red
                if ($service.Name -eq 'frontend') {
                    Write-Host "            run .\dev.cmd fresh to rebuild from scratch" -ForegroundColor Yellow
                }
                Show-Log -Service $service
                $failed += $service.Name
            }
            default {
                Write-Host ("  {0,-9} did not answer" -f $service.Name) -ForegroundColor Red
                Show-Log -Service $service
                $failed += $service.Name
            }
        }
    }

    if ($failed) { exit 1 }

    Write-Host "`n  App   http://localhost:3000" -ForegroundColor White
    Write-Host   "  Docs  http://localhost:8000/docs`n" -ForegroundColor White
}

function Invoke-Status {
    Write-Host ''
    foreach ($service in $Services) {
        $pids = Get-Listener -Port $service.Port
        if ($pids) {
            $names = (Get-Process -Id $pids -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName) -join ', '
            Write-Host ("  {0,-9} up on {1}  ({2}: {3})" -f $service.Name, $service.Port, $names, ($pids -join ', ')) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-9} down" -f $service.Name) -ForegroundColor DarkGray
        }
    }
    Write-Host ''
}

function Invoke-Logs {
    foreach ($service in $Services) {
        foreach ($stream in 'out', 'err') {
            $path = Join-Path $service.Logs "$stream.log"
            if (-not (Test-Path $path)) { continue }
            $lines = Get-Content $path -Tail $Tail -ErrorAction SilentlyContinue
            if (-not $lines) { continue }
            Write-Host "`n=== $($service.Name) $stream ===" -ForegroundColor Cyan
            $lines | ForEach-Object { "  $_" }
        }
    }
    Write-Host ''
}

switch ($Command) {
    'start' { Invoke-Start }
    'stop' { Write-Host "`nStopping" -ForegroundColor Cyan; foreach ($s in $Services) { Stop-DevService -Service $s }; Write-Host '' }
    'restart' {
        Write-Host "`nStopping" -ForegroundColor Cyan
        foreach ($s in $Services) { Stop-DevService -Service $s }
        Invoke-Start
    }
    'fresh' {
        Write-Host "`nStopping" -ForegroundColor Cyan
        foreach ($s in $Services) { Stop-DevService -Service $s }

        # After the stop, never before: a live dev server rewrites .next while the
        # delete walks it, and what survives is a directory half of each.
        #
        # Deliberately a command somebody types rather than something a failed start
        # does by itself. A 500 is just as easily a real error in a page, and wiping
        # the cache on every one of those would bury it under a slow rebuild.
        $next = Join-Path $Web '.next'
        if (Test-Path $next) {
            Write-Host "`nClearing" -ForegroundColor Cyan
            Remove-Item -Recurse -Force $next
            Write-Host '  web/.next removed' -ForegroundColor Green
        }
        Invoke-Start
    }
    'status' { Invoke-Status }
    'logs' { Invoke-Logs }
}

# Explicit, so a native command's exit code from somewhere above (taskkill on a
# process that had already gone, say) cannot become this script's verdict.
exit 0
