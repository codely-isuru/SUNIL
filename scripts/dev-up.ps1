<#
.SYNOPSIS
    Boots the SUNIL V2 development platform and waits for it to be healthy.

.DESCRIPTION
    Brings up Postgres+pgvector, LiteLLM and n8n from
    infra/docker-compose.yml, then blocks until every service with a
    healthcheck reports `healthy` (or fails loudly with logs).

    Idempotent: safe to re-run against an already-running stack.

    No application container is started - branch V2 is a clean-slate rebuild
    and no app code exists yet (ADR-030 Amendment 1).

.PARAMETER TimeoutSeconds
    How long to wait for all services to become healthy. Default 300.
    First boot is the slow one: Postgres runs initdb + the database init
    script, then LiteLLM pushes its Prisma schema and n8n runs its own
    migrations.

.PARAMETER Pull
    Pull the pinned images before booting.

.EXAMPLE
    ./scripts/dev-up.ps1
.EXAMPLE
    ./scripts/dev-up.ps1 -Pull -TimeoutSeconds 600
#>
[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 300,
    [switch]$Pull
)

$ErrorActionPreference = 'Stop'

# Always operate from the repo root, whatever directory the caller is in.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$ComposeFile = 'infra/docker-compose.yml'
$EnvFile     = '.env'
# Explicit --env-file: without it Compose looks for infra/.env next to the
# compose file, not the repo-root .env we actually keep.
$ComposeArgs = @('compose', '--env-file', $EnvFile, '-f', $ComposeFile)

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    $msg" -ForegroundColor Yellow }
function Write-Err2($msg) { Write-Host "    $msg" -ForegroundColor Red }

# --- preflight ------------------------------------------------------------
Write-Step 'Preflight'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Err2 'docker is not on PATH. Install Docker Desktop, then re-run.'
    exit 1
}

# Check the DAEMON, not just the CLI: `docker --version` answers happily with
# a dead engine.
docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Err2 'The Docker daemon is not responding. Start Docker Desktop and wait'
    Write-Err2 'for it to report "Engine running", then re-run this script.'
    exit 1
}
Write-Ok ("Docker engine " + (docker info --format '{{.ServerVersion}}'))

if (-not (Test-Path $EnvFile)) {
    Write-Warn2 "No .env found - creating one from .env.example (dummy values)."
    Copy-Item '.env.example' $EnvFile
    Write-Warn2 "Edit .env before using this stack for anything real."
}

# Fail fast and specifically on the required secrets, rather than letting a
# container die with a cryptic error 40 seconds from now.
$envText = Get-Content $EnvFile -Raw
foreach ($required in @('POSTGRES_PASSWORD', 'LITELLM_MASTER_KEY', 'LITELLM_SALT_KEY', 'N8N_ENCRYPTION_KEY')) {
    if ($envText -notmatch "(?m)^\s*$required\s*=\s*\S+") {
        Write-Err2 "$required is missing or empty in $EnvFile. See .env.example."
        exit 1
    }
}
Write-Ok 'Required variables present.'

# Host-level port check. Learned the hard way: `docker ps` is not enough -
# a host-native process can own the port with no container in sight.
$portMap = @{}
foreach ($line in (Get-Content $EnvFile | Where-Object { $_ -match '^\s*[A-Z0-9_]+\s*=' })) {
    $k, $v = $line -split '=', 2
    $portMap[$k.Trim()] = $v.Trim()
}

# Windows PowerShell 5.1 has no `??` operator - use an explicit fallback.
function Get-EnvVal([string]$Name, $Default) {
    if ($portMap.ContainsKey($Name) -and $portMap[$Name]) { return $portMap[$Name] }
    return $Default
}

$wanted = @(
    @{ Name = 'postgres'; Port = [int](Get-EnvVal 'POSTGRES_HOST_PORT' 5433) },
    @{ Name = 'litellm';  Port = [int](Get-EnvVal 'LITELLM_HOST_PORT'  4000) },
    @{ Name = 'n8n';      Port = [int](Get-EnvVal 'N8N_HOST_PORT'      5680) }
)
# Ports this stack already owns are fine; anything else on the port is not.
$ourContainers = @()
try { $ourContainers = docker @ComposeArgs ps -q 2>$null } catch { }
foreach ($w in $wanted) {
    if ($w.Port -eq 4317) {
        Write-Err2 "Port 4317 is the Minions Portal and must never be bound by this stack."
        exit 1
    }
    $held = Get-NetTCPConnection -State Listen -LocalPort $w.Port -ErrorAction SilentlyContinue
    if ($held -and -not $ourContainers) {
        $pids = ($held.OwningProcess | Sort-Object -Unique) -join ','
        Write-Warn2 ("Port {0} ({1}) is already LISTENING (PID {2}). If it is not this stack," -f $w.Port, $w.Name, $pids)
        Write-Warn2 ("change {0}_HOST_PORT in .env - the bind will otherwise fail." -f $w.Name.ToUpper())
    }
}

# --- validate -------------------------------------------------------------
Write-Step 'Validating compose file'
docker @ComposeArgs config --quiet
if ($LASTEXITCODE -ne 0) { Write-Err2 'Compose file is invalid.'; exit 1 }
Write-Ok 'infra/docker-compose.yml is valid.'

# --- boot -----------------------------------------------------------------
if ($Pull) {
    Write-Step 'Pulling pinned images'
    docker @ComposeArgs pull
}

Write-Step 'Starting services'
docker @ComposeArgs up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { Write-Err2 'docker compose up failed.'; exit 1 }

# --- wait for health ------------------------------------------------------
Write-Step "Waiting for healthchecks (timeout ${TimeoutSeconds}s)"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastLine = ''

while ((Get-Date) -lt $deadline) {
    $rows = @()
    $json = docker @ComposeArgs ps --format json 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) {
        # Compose emits either one JSON array or newline-delimited objects,
        # depending on version - handle both.
        foreach ($chunk in @($json)) {
            foreach ($l in ($chunk -split "`n" | Where-Object { $_.Trim() })) {
                try { $rows += ($l | ConvertFrom-Json) } catch { }
            }
        }
    }
    $rows = @($rows | Where-Object { $_.Service })

    if ($rows.Count -gt 0) {
        # Treat a service with no healthcheck as satisfied when it is running.
        $states = $rows | ForEach-Object {
            $h = if ($_.Health) { $_.Health } elseif ($_.State -eq 'running') { 'healthy' } else { $_.State }
            "$($_.Service)=$h"
        }
        $line = ($states -join '  ')
        if ($line -ne $lastLine) { Write-Host "    $line"; $lastLine = $line }

        $unhealthy = $rows | Where-Object {
            $_.Health -eq 'unhealthy' -or $_.State -eq 'exited' -or $_.State -eq 'dead'
        }
        if ($unhealthy) {
            Write-Err2 ("Service(s) failed: " + (($unhealthy | ForEach-Object { $_.Service }) -join ', '))
            foreach ($u in $unhealthy) { docker @ComposeArgs logs --tail 40 $u.Service }
            exit 1
        }

        $pending = $rows | Where-Object {
            -not ($_.Health -eq 'healthy' -or (-not $_.Health -and $_.State -eq 'running'))
        }
        if (-not $pending) {
            Write-Ok 'All services healthy.'
            Write-Step 'Status'
            docker @ComposeArgs ps
            Write-Host ''
            Write-Host ("  Postgres  localhost:{0}  (databases: {1}, {2}, {3})" -f `
                (Get-EnvVal 'POSTGRES_HOST_PORT' '5433'), (Get-EnvVal 'POSTGRES_DB' 'sunil'), `
                (Get-EnvVal 'LITELLM_DB_NAME' 'litellm'), (Get-EnvVal 'N8N_DB_NAME' 'n8n'))
            Write-Host ("  LiteLLM   http://localhost:{0}   (UI /ui, health /health/liveliness)" -f (Get-EnvVal 'LITELLM_HOST_PORT' '4000'))
            Write-Host ("  n8n       http://localhost:{0}   (health /healthz)" -f (Get-EnvVal 'N8N_HOST_PORT' '5680'))
            Write-Host ''
            Write-Host '  No app container yet - clean-slate rebuild (ADR-030 Amendment 1).'
            Write-Host '  Teardown: ./scripts/dev-down.ps1'
            exit 0
        }
    }
    Start-Sleep -Seconds 5
}

Write-Err2 "Timed out after ${TimeoutSeconds}s waiting for healthchecks."
docker @ComposeArgs ps
exit 1
