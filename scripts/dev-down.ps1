<#
.SYNOPSIS
    Tears down the SUNIL V2 development platform.

.DESCRIPTION
    Stops and removes the platform containers. Named volumes are KEPT by
    default, so Postgres data, LiteLLM virtual keys and n8n workflows survive
    a normal down/up cycle.

.PARAMETER Volumes
    Also delete the named volumes. DESTRUCTIVE and irreversible: drops the
    SUNIL database, LiteLLM's key/spend history and every n8n workflow and
    stored credential. Requires -Force, or an interactive confirmation.

    Note: the Postgres first-boot init script
    (infra/postgres/init/01-init-databases.sh) only runs on an empty volume,
    so this is also how you make a change to it take effect.

.PARAMETER Force
    Skip the confirmation prompt for -Volumes.

.EXAMPLE
    ./scripts/dev-down.ps1
.EXAMPLE
    ./scripts/dev-down.ps1 -Volumes -Force
#>
[CmdletBinding()]
param(
    [switch]$Volumes,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$EnvFile = '.env'
if (-not (Test-Path $EnvFile)) { $EnvFile = '.env.example' }
$ComposeArgs = @('compose', '--env-file', $EnvFile, '-f', 'infra/docker-compose.yml')

docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '    The Docker daemon is not responding - nothing to tear down.' -ForegroundColor Yellow
    exit 0
}

if ($Volumes) {
    if (-not $Force) {
        Write-Host 'This DELETES all platform data:' -ForegroundColor Red
        Write-Host '  - the SUNIL Postgres database (incl. pgvector data)'
        Write-Host '  - LiteLLM virtual keys and spend history'
        Write-Host '  - every n8n workflow and stored credential'
        $answer = Read-Host 'Type DELETE to confirm'
        if ($answer -ne 'DELETE') { Write-Host 'Aborted.'; exit 1 }
    }
    Write-Host '==> Stopping services and removing volumes' -ForegroundColor Cyan
    docker @ComposeArgs down --volumes --remove-orphans
} else {
    Write-Host '==> Stopping services (volumes kept)' -ForegroundColor Cyan
    docker @ComposeArgs down --remove-orphans
}

if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host '    Done. Bring it back with ./scripts/dev-up.ps1' -ForegroundColor Green
