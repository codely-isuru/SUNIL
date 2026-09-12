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

$ComposeFile   = 'infra/docker-compose.yml'
$EnvFile       = '.env'
# Provider keys are scoped to the LiteLLM container only (ADR-030 S2), so
# they live in their own env file rather than the shared one.
$LitellmEnvFile = 'infra/.env.litellm'
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

# --- secrets ---------------------------------------------------------------
# The rule this section enforces (Phase 0 security + QA review, D-finding 1):
# THE STACK NEVER BOOTS ON A COMMITTED DUMMY VALUE. The old behaviour was to
# copy .env.example over and check the values were merely non-EMPTY, so a
# clean checkout booted straight onto passwords published in a public repo -
# and with the ports on 0.0.0.0 at the time, that was a LAN-reachable n8n
# credential vault behind a password anyone could read on GitHub.
#
# Keep this logic behaviourally identical to scripts/dev-up.sh.

# 48 hex characters from the OS CSPRNG. Not Get-Random: that is a seeded
# pseudo-random generator, not a cryptographic one, and these values protect
# a credential vault.
function New-RandomSecret {
    $bytes = New-Object 'byte[]' 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

# Replace `KEY=anything` with `KEY=<value>`. Values are hex, so no regex
# metacharacter can appear in the replacement.
function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = @(Get-Content $Path)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$Key\s*=") { $found = $true; "$Key=$Value" } else { $line }
    }
    if (-not $found) { $out = $out + "$Key=$Value" }
    # utf8 without BOM is not available on 5.1's Set-Content, and these files
    # are pure ASCII, so ascii is the honest encoding to write.
    Set-Content -Path $Path -Value $out -Encoding ascii
}

# Rewrite the password inside DATABASE_URL's userinfo, in place.
#
# The app reads DATABASE_URL; Postgres reads POSTGRES_PASSWORD. Generating the
# second without the first left a freshly created .env that boots the stack and
# then refuses every application connection - and the old code only WARNED about
# it, so the failure surfaced later as an authentication error with no
# connection to the message that had scrolled past. Values are hex
# (New-RandomSecret), so nothing needs URL-encoding and no regex metacharacter
# can appear in the replacement. Returns $true only if the rewrite is VERIFIED.
function Sync-DatabaseUrlPassword([string]$Path, [string]$Password) {
    $pattern = '^(\s*DATABASE_URL\s*=[^:]*://[^:@/]*:)[^@]*@'
    $lines = @(Get-Content $Path)
    $out = foreach ($line in $lines) {
        if ($line -match $pattern) { $line -replace $pattern, "`${1}$Password@" } else { $line }
    }
    Set-Content -Path $Path -Value $out -Encoding ascii
    # Verified, not assumed: if the template ever stops matching the shape
    # above, this must fail LOUDLY rather than leave a stale password behind a
    # tick.
    return (Get-EnvFileValue $Path 'DATABASE_URL').Contains(":$Password@")
}

function Get-EnvFileValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return '' }
    $match = @(Get-Content $Path | Where-Object { $_ -match "^\s*$Key\s*=" })
    if ($match.Count -eq 0) { return '' }
    $parts = $match[-1] -split '=', 2
    if ($parts.Count -lt 2) { return '' }
    return $parts[1].Trim()
}

# Secrets that MUST be real for the three infrastructure services to be
# trustworthy. Anything the app will need but no running process consumes yet
# is warned about instead - blocking a platform boot on a variable nothing
# reads would just teach people to bypass this check.
$HardSecrets = @('POSTGRES_PASSWORD', 'LITELLM_MASTER_KEY', 'N8N_ENCRYPTION_KEY',
                 'LITELLM_DB_PASSWORD', 'N8N_DB_PASSWORD')
$SoftSecrets = @('SESSION_SECRET', 'SUNIL_SERVICE_TOKEN', 'SUNIL_N8N_MCP_AUTH_TOKEN',
                 'LITELLM_VIRTUAL_KEY_DEFAULT')

if (-not (Test-Path $EnvFile)) {
    Write-Warn2 "No $EnvFile found - creating it from .env.example."
    Copy-Item '.env.example' $EnvFile
    $generated = 0
    foreach ($k in ($HardSecrets + $SoftSecrets)) {
        # LITELLM_VIRTUAL_KEY_DEFAULT is minted BY LiteLLM (POST /key/generate)
        # against the master key; a random string here would just 401. Leave it
        # for a human and rely on the soft warning.
        if ($k -eq 'LITELLM_VIRTUAL_KEY_DEFAULT') { continue }
        $v = New-RandomSecret
        # LiteLLM requires its master key to look like an API key.
        if ($k -eq 'LITELLM_MASTER_KEY') { $v = "sk-$v" }
        Set-EnvValue $EnvFile $k $v
        $generated++
        # DATABASE_URL embeds this same password; the app would otherwise be
        # handed the template one and fail to authenticate.
        if ($k -eq 'POSTGRES_PASSWORD') {
            if (-not (Sync-DatabaseUrlPassword $EnvFile $v)) {
                Remove-Item $EnvFile -Force
                Write-Err2 "Could not rewrite DATABASE_URL's password in $EnvFile, so it"
                Write-Err2 'would still carry the template value while Postgres used a'
                Write-Err2 "generated one - every app connection would fail. $EnvFile was"
                Write-Err2 'NOT created.'
                Write-Err2 "Do this instead:  Copy-Item .env.example $EnvFile  and set"
                Write-Err2 'DATABASE_URL and POSTGRES_PASSWORD to the same password by hand.'
                exit 1
            }
        }
    }
    Write-Ok "Generated $generated random secret(s) into $EnvFile."
    Write-Ok "DATABASE_URL's password was synced to the generated POSTGRES_PASSWORD."
}

if (-not (Test-Path $LitellmEnvFile)) {
    Write-Warn2 "No $LitellmEnvFile found - creating it from the template."
    Copy-Item 'infra/.env.litellm.example' $LitellmEnvFile
    Set-EnvValue $LitellmEnvFile 'LITELLM_SALT_KEY' ("sk-" + (New-RandomSecret))
    Write-Ok "Generated LITELLM_SALT_KEY into $LitellmEnvFile."
}

# Present-and-not-a-dummy, for both files.
function Test-Secret([string]$Key, [string]$Path, [bool]$Fatal) {
    $value = Get-EnvFileValue $Path $Key
    if (-not $value) {
        if ($Fatal) {
            Write-Err2 "$Key is missing or empty in $Path. See $Path.example."
            return $false
        }
        Write-Warn2 "$Key is empty in $Path (no process needs it yet)."
        return $true
    }
    # Case-insensitive (-match is): the template markers are lowercase, but a
    # human writing CHANGE-ME must not slip through.
    if ($value -match 'dummy|change-?me') {
        if ($Fatal) {
            Write-Err2 "$Key in $Path is still a TEMPLATE value."
            Write-Err2 'That value is committed to a PUBLIC repository - it is not a secret.'
            Write-Err2 'Replace it with a generated value: openssl rand -hex 24'
            return $false
        }
        Write-Warn2 "$Key in $Path is still a template value (nothing reads it yet)."
    }
    return $true
}

$secretFailures = 0
foreach ($key in $HardSecrets) {
    if (-not (Test-Secret $key $EnvFile $true)) { $secretFailures++ }
}
if (-not (Test-Secret 'LITELLM_SALT_KEY' $LitellmEnvFile $true)) { $secretFailures++ }
foreach ($key in $SoftSecrets) { Test-Secret $key $EnvFile $false | Out-Null }
# Upstream provider keys are allowed to stay dummy: the proxy boots and serves
# health without them, and this machine has no ambient Anthropic key
# (docs/ENVIRONMENT.md S8). Say so once rather than failing.
foreach ($key in @('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')) {
    $v = Get-EnvFileValue $LitellmEnvFile $key
    if ((-not $v) -or ($v -match 'dummy|not-a-real')) {
        Write-Warn2 "$key is a placeholder - completion calls to that provider will fail."
    }
}
if ($secretFailures -gt 0) {
    Write-Err2 "$secretFailures secret(s) rejected. Refusing to boot."
    exit 1
}
Write-Ok 'Required secrets present and not template values.'

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
            # 127.0.0.1, never `localhost`. ADR-032 binds every published port
            # to host_ip 127.0.0.1 (the CI port gate asserts it), so nothing is
            # listening on ::1 - and `localhost` resolves to ::1 first on a
            # modern dual-stack host. A client that honours that order (psql,
            # curl, the browser) waits out a connection timeout on the v6
            # address before falling back, which reads as "the stack is up but
            # hangs".
            Write-Host ("  Postgres  127.0.0.1:{0}  (databases: {1}, {2}, {3})" -f `
                (Get-EnvVal 'POSTGRES_HOST_PORT' '5433'), (Get-EnvVal 'POSTGRES_DB' 'sunil'), `
                (Get-EnvVal 'LITELLM_DB_NAME' 'litellm'), (Get-EnvVal 'N8N_DB_NAME' 'n8n'))
            Write-Host ("  LiteLLM   http://127.0.0.1:{0}   (UI /ui, health /health/liveliness)" -f (Get-EnvVal 'LITELLM_HOST_PORT' '4000'))
            Write-Host ("  n8n       http://127.0.0.1:{0}   (health /healthz)" -f (Get-EnvVal 'N8N_HOST_PORT' '5680'))
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
