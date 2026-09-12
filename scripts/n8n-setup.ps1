#Requires -Version 5.1
<#
.SYNOPSIS
    Complete n8n's first-boot setup and import Stream E's workflows.

.DESCRIPTION
    Windows twin of scripts/n8n-setup.sh. Same behaviour, same exit codes.

    What it does, in order:
      1. boots the platform if n8n is not answering (scripts/dev-up.ps1);
      2. completes the OWNER SETUP with generated credentials, stored in .env;
      3. creates/updates the two n8n credentials that hold SUNIL's bearer tokens;
      4. imports and activates every workflow in infra/n8n/workflows/.

    IDEMPOTENT. Re-running re-syncs credentials and workflows in place; it never
    creates a second copy of either.

    WHY THIS EXISTS AT ALL. n8n 2.x serves an UNAUTHENTICATED owner-setup screen
    until somebody claims it: whoever reaches the port first owns the credential
    vault. Compose binds the port to 127.0.0.1 (ADR-032), which closes the
    window to processes on this host - and this script closes it to a human who
    forgets. Setting the owner from a script also means the password is a
    generated value nobody ever types, which is the only kind a dev instance
    keeps.

    NO SECRET IS EVER PRINTED OR COMMITTED. Generated values live in .env, which
    .gitignore covers. The bearer tokens go into n8n's own encrypted vault
    (N8N_ENCRYPTION_KEY) and are substituted into workflows BY CREDENTIAL ID, so
    the committed JSON in infra/n8n/workflows/ carries a placeholder, never a
    token.

.EXAMPLE
    .\scripts\n8n-setup.ps1
.EXAMPLE
    .\scripts\n8n-setup.ps1 -NoActivate
#>
[CmdletBinding()]
param(
    [switch]$NoActivate,
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$EnvFile = Join-Path $RepoRoot '.env'
$WorkflowDir = Join-Path $RepoRoot 'infra\n8n\workflows'
$BrowserId = 'sunil-n8n-setup'

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "    $m" -ForegroundColor Red }

# --- preflight ------------------------------------------------------------
Write-Step 'Preflight'
if (-not (Test-Path $EnvFile)) {
    Write-Err "No .env. Run .\scripts\dev-up.ps1 first - it creates one with generated secrets."
    exit 1
}

function Get-EnvValue([string]$Key, [string]$Default = '') {
    $line = Select-String -Path $EnvFile -Pattern "^\s*$Key\s*=" | Select-Object -Last 1
    if ($null -eq $line) { return $Default }
    $value = ($line.Line -split '=', 2)[1].Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $content = Get-Content $EnvFile
    if ($content -match "^\s*$Key\s*=") {
        $content = $content -replace "^\s*$Key\s*=.*$", "$Key=$Value"
        Set-Content -Path $EnvFile -Value $content -Encoding utf8
    } else {
        Add-Content -Path $EnvFile -Value "$Key=$Value" -Encoding utf8
    }
}

function New-RandomHex([int]$Bytes = 18) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return (($buffer | ForEach-Object { $_.ToString('x2') }) -join '')
}

$ServiceToken = Get-EnvValue 'SUNIL_SERVICE_TOKEN'
$McpToken = Get-EnvValue 'SUNIL_N8N_MCP_AUTH_TOKEN'
foreach ($pair in @(@{ n = 'SUNIL_SERVICE_TOKEN'; v = $ServiceToken }, @{ n = 'SUNIL_N8N_MCP_AUTH_TOKEN'; v = $McpToken })) {
    if ([string]::IsNullOrWhiteSpace($pair.v) -or $pair.v -imatch 'dummy|change-?me') {
        Write-Err "$($pair.n) in .env is empty or still a TEMPLATE value."
        Write-Err 'Those values are committed to a public repository - they are not secrets.'
        Write-Err 'Generate real ones (openssl rand -hex 24) before wiring n8n to them.'
        exit 1
    }
}
Write-Ok 'Both bearer tokens are present and are not template values.'

# 127.0.0.1, never `localhost`: the published port is v4-loopback only
# (ADR-032), and `localhost` resolves to ::1 first on a dual-stack host.
$Port = Get-EnvValue 'N8N_HOST_PORT' '5680'
$Base = "http://127.0.0.1:$Port"

# --- the stack ------------------------------------------------------------
function Test-N8nUp {
    try {
        $r = Invoke-WebRequest -Uri "$Base/healthz" -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch { return $false }
}

Write-Step "Checking n8n on $Base"
if (Test-N8nUp) {
    Write-Ok 'Already answering /healthz.'
} else {
    Write-Warn 'Not answering - booting the platform (scripts/dev-up.ps1).'
    & (Join-Path $PSScriptRoot 'dev-up.ps1') -TimeoutSeconds $TimeoutSeconds | Out-Null
    if (-not (Test-N8nUp)) { Write-Err "n8n still not answering on $Base/healthz."; exit 1 }
    Write-Ok 'Booted and healthy.'
}

# The session cookie is re-added to a cookie container by hand, with Secure
# OFF. Two Windows PowerShell 5.1 behaviours collide here and each one alone
# produces a 401 with a perfectly valid session sitting in the container:
#
#   1. n8n sets `n8n-auth` with `Secure` even when it is serving plain HTTP on
#      loopback, and the automatic cookie container honours that by never
#      sending it back over http://;
#   2. `Cookie` is a RESTRICTED request header on HttpWebRequest, so passing it
#      through -Headers is dropped SILENTLY - no error, just an unauthenticated
#      request. (Verified both ways against the live container before writing
#      this: the container path returns the credential list, the header path
#      returns 401.)
#
# A `System.Net.Cookie` built by constructor defaults to Secure = $false, which
# is what makes it go back out over loopback HTTP.
$Session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
function Invoke-N8n([string]$Method, [string]$Path, $Body = $null) {
    $args = @{
        Uri             = "$Base$Path"
        Method          = $Method
        WebSession      = $Session
        Headers         = @{ 'browser-id' = $BrowserId }
        UseBasicParsing = $true
    }
    if ($null -ne $Body) {
        $args.ContentType = 'application/json'
        # -Depth 20: n8n nodes nest deeply and ConvertTo-Json silently truncates
        # at depth 2, which would post a workflow whose parameters are the string
        # "System.Collections.Hashtable".
        $args.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
    }
    return Invoke-RestMethod @args
}

function Invoke-N8nSignIn([string]$Path, $Body) {
    # POST an endpoint that ISSUES the session cookie, and capture it.
    $headers = @{ 'browser-id' = $BrowserId }
    $response = Invoke-WebRequest -Uri "$Base$Path" -Method POST -Headers $headers `
        -ContentType 'application/json' -UseBasicParsing `
        -Body ($Body | ConvertTo-Json -Depth 20 -Compress)
    $setCookie = $response.Headers['Set-Cookie']
    if ($setCookie) {
        # Name=value only: the attributes (Secure, SameSite, Max-Age) are the
        # server's instructions to a browser, and re-applying Secure is exactly
        # what would stop the cookie going back out over loopback HTTP.
        $pair = (($setCookie -join ',') -split ';')[0]
        $name, $value = $pair -split '=', 2
        $Session.Cookies.Add((New-Object System.Net.Cookie($name, $value, '/', '127.0.0.1')))
    }
    return ($response.Content | ConvertFrom-Json)
}

# --- owner ----------------------------------------------------------------
Write-Step 'Owner setup'
$settings = Invoke-N8n GET '/rest/settings'
$needsSetup = $settings.data.userManagement.showSetupOnFirstLoad

$OwnerEmail = Get-EnvValue 'N8N_OWNER_EMAIL' 'sunil-owner@sunil.local'
$OwnerPassword = Get-EnvValue 'N8N_OWNER_PASSWORD'
if ([string]::IsNullOrWhiteSpace($OwnerPassword)) {
    # n8n's own rule: >= 8 chars, at least one number and one capital.
    $OwnerPassword = 'Sx' + (New-RandomHex) + 'A9'
    Set-EnvValue 'N8N_OWNER_EMAIL' $OwnerEmail
    Set-EnvValue 'N8N_OWNER_PASSWORD' $OwnerPassword
    Write-Ok 'Generated an owner password into .env (N8N_OWNER_PASSWORD).'
}

if ($needsSetup) {
    $created = Invoke-N8nSignIn '/rest/owner/setup' @{
        email = $OwnerEmail; firstName = 'SUNIL'; lastName = 'Owner'; password = $OwnerPassword
    }
    if (-not $created.data.id) { Write-Err 'Owner setup was refused. Check the n8n container logs.'; exit 1 }
    Write-Ok "Owner claimed as $OwnerEmail - the unauthenticated setup screen is now closed."
} else {
    Write-Ok 'Owner already set.'
}

try {
    $null = Invoke-N8nSignIn '/rest/login' @{ emailOrLdapLoginId = $OwnerEmail; password = $OwnerPassword }
} catch {
    Write-Err "Could not sign in as $OwnerEmail."
    Write-Err "If this instance was set up by hand, put that owner's credentials in .env"
    Write-Err '(N8N_OWNER_EMAIL / N8N_OWNER_PASSWORD) and re-run.'
    exit 1
}
Write-Ok 'Signed in.'

# --- credentials ----------------------------------------------------------
# The tokens live in n8n's ENCRYPTED VAULT, and the workflows reference them by
# id. That is what keeps infra/n8n/workflows/*.json committable.
Write-Step 'Credentials'
$existingCredentials = (Invoke-N8n GET '/rest/credentials').data

function Set-BearerCredential([string]$Name, [string]$Token) {
    $body = @{ name = $Name; type = 'httpBearerAuth'; data = @{ token = $Token } }
    $match = $existingCredentials | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if ($match) {
        # PATCH keeps the id stable, so a token rotation does not orphan every
        # workflow that references it.
        $null = Invoke-N8n PATCH "/rest/credentials/$($match.id)" $body
        return $match.id
    }
    return (Invoke-N8n POST '/rest/credentials' $body).data.id
}

$ServiceCredentialId = Set-BearerCredential 'SUNIL service token' $ServiceToken
$McpCredentialId = Set-BearerCredential 'SUNIL MCP bearer' $McpToken
if (-not $ServiceCredentialId -or -not $McpCredentialId) { Write-Err 'Could not create the n8n credentials.'; exit 1 }
Write-Ok "'SUNIL service token' and 'SUNIL MCP bearer' are in n8n's vault (ids not printed)."

# --- workflows ------------------------------------------------------------
Write-Step 'Workflows'
$existingWorkflows = (Invoke-N8n GET '/rest/workflows').data
$processed = 0

foreach ($file in Get-ChildItem -Path $WorkflowDir -Filter '*.json' | Sort-Object Name) {
    $text = Get-Content -Path $file.FullName -Raw -Encoding utf8
    $text = $text.Replace('__SUNIL_SERVICE_TOKEN_CREDENTIAL_ID__', $ServiceCredentialId)
    $text = $text.Replace('__SUNIL_MCP_BEARER_CREDENTIAL_ID__', $McpCredentialId)
    $document = $text | ConvertFrom-Json

    # SUNIL's own `meta` block is documentation for readers of the repository;
    # n8n's API rejects unknown top-level keys.
    $payload = @{
        name        = $document.name
        nodes       = $document.nodes
        connections = $document.connections
        settings    = $document.settings
    }

    $match = $existingWorkflows | Where-Object { $_.name -eq $document.name } | Select-Object -First 1
    if ($match) {
        $result = Invoke-N8n PATCH "/rest/workflows/$($match.id)" $payload
        $action = 'updated'
    } else {
        $result = Invoke-N8n POST '/rest/workflows' $payload
        $action = 'created'
    }
    $workflowId = $result.data.id
    if (-not $workflowId) { Write-Err "Could not import $($file.Name)."; exit 1 }

    if ($NoActivate) {
        Write-Ok "$($document.name): $action (left inactive, -NoActivate)."
    } else {
        # Activation is its own endpoint in n8n 2.x and needs the CURRENT
        # versionId - PATCHing `{"active": true}` is accepted with a 200 and
        # silently does nothing, which reads as "imported fine" right up until
        # the webhook answers 404.
        $current = Invoke-N8n GET "/rest/workflows/$workflowId"
        $activated = Invoke-N8n POST "/rest/workflows/$workflowId/activate" @{ versionId = $current.data.versionId }
        if ($activated.data.active) {
            Write-Ok "$($document.name): $action and ACTIVE."
        } else {
            Write-Warn "$($document.name): $action, but activation did not take. Activate it in the editor."
        }
    }
    $processed++
}
Write-Ok "$processed workflow(s) processed from infra/n8n/workflows/."

# --- what the app needs next ----------------------------------------------
Write-Step 'Done'
Write-Host ''
Write-Host "  Editor         $Base  (owner: $OwnerEmail, password in .env)"
Write-Host "  MCP endpoint   $Base/mcp/sunil   - Bearer only; 403 without it"
Write-Host ''
Write-Host '  SUNIL must point at the workflow PATH, not at the /mcp prefix:'
Write-Host "      host-native   SUNIL_N8N_MCP_BASE_URL=$Base/mcp/sunil"
Write-Host '      in-network    SUNIL_N8N_MCP_BASE_URL=http://n8n:5678/mcp/sunil'
Write-Host ''
Write-Host '  Teardown: .\scripts\dev-down.ps1'
