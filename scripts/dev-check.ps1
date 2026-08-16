<#
.SYNOPSIS
    SUNIL local dev preflight check.

.DESCRIPTION
    Pulled forward from optional task T17 into T21 (docs/M1_BUILD_PLAN.md
    section 5, section 9) because the single biggest local-dev trap on this
    project - the session cookie behaving differently on `localhost` vs
    `127.0.0.1` (ADR-008) - is cheap to catch here and expensive to
    discover mid-build.

    Checks:
      1. Python version (expect 3.13.x, docs/ARCHITECTURE_V1.md section 14.3).
      2. Backend venv presence (apps/api/.venv).
      3. Dev port availability (8000, 3000, 3001) and that 4317 (the Minions
         Portal) is never something SUNIL itself is asked to bind.
      4. Whether .env exists at the repo root, and whether each required
         variable is present - for SecretStr-marked variables this reports
         presence only, NEVER the value.
      5. The localhost/127.0.0.1 cookie trap: WEB_ORIGIN and
         NEXT_PUBLIC_API_BASE_URL are non-secret (docs/ARCHITECTURE_V1.md
         section 14.4 marks both "Secret: no"), so this script reads and
         prints those two specific values only, to assert both use
         `localhost`.
      6. Best-effort health probe against a running API, if there is one.

    Hard rule honoured throughout: this script never prints the value of
    ANTHROPIC_API_KEY, GITHUB_TOKEN, SESSION_SECRET, OWNER_PASSWORD or
    DATABASE_URL (which may embed credentials on Postgres) - presence only.

.EXAMPLE
    powershell -File scripts\dev-check.ps1
#>

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Write-Line($ok, $msg) {
    if ($ok) {
        Write-Host "  [OK]   $msg" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $msg" -ForegroundColor Red
    }
}

Write-Host "SUNIL dev preflight check" -ForegroundColor Cyan
Write-Host "=========================="

# 1. Python version -----------------------------------------------------
Write-Host "`n[1] Python"
try {
    $pyVersionRaw = (& python --version) 2>&1 | Out-String
    $pyVersionRaw = $pyVersionRaw.Trim()
    if ($pyVersionRaw -match "Python 3\.13") {
        Write-Line $true "python --version -> $pyVersionRaw"
    } else {
        Write-Line $false "python --version -> $pyVersionRaw (expected 3.13.x, docs/ARCHITECTURE_V1.md section 14.3)"
        $warnings.Add("Python is not 3.13.x - dependencies in apps/api/pyproject.toml are pinned against 3.13.")
    }
} catch {
    Write-Line $false "python did not run: $($_.Exception.Message)"
    $failures.Add("python is not runnable from this shell. Install Python 3.13 and ensure it is on PATH.")
}
Write-Host "  Reminder: always invoke 'python', never 'python3' - python3 is a broken Microsoft" -ForegroundColor DarkGray
Write-Host "  Store app-execution-alias stub on this machine (docs/ENVIRONMENT.md section 1)." -ForegroundColor DarkGray

# 2. Backend venv presence ------------------------------------------------
Write-Host "`n[2] Backend virtualenv"
$venvPath = Join-Path $repoRoot "apps\api\.venv"
if (Test-Path $venvPath) {
    Write-Line $true "apps\api\.venv exists"
} else {
    Write-Line $false "apps\api\.venv not found"
    $warnings.Add('Run scripts\dev-api.ps1 (or "python -m venv apps\api\.venv" then "pip install -e .[dev]") to create it.')
}

# 3. Port availability -----------------------------------------------------
Write-Host "`n[3] Ports"

function Get-PortListener($port) {
    try {
        return Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    } catch {
        return $null
    }
}

foreach ($p in @(8000, 3000, 3001)) {
    $listener = Get-PortListener $p
    if (-not $listener) {
        Write-Line $true "port $p is free"
    } else {
        Write-Host "  [WARN] port $p is already in use (PID(s): $($listener.OwningProcess -join ', ')) - a dev server may already be running." -ForegroundColor Yellow
        $warnings.Add("Port $p is in use. If that isn't your own dev server: Get-Process -Id <pid> then stop it, or pick a different port.")
    }
}

# 4317 is the Minions Portal. SUNIL must NEVER bind to it (M1_BUILD_PLAN.md
# section 0.2 rule 5). This script only checks - it never binds anything itself.
$portalListener = Get-PortListener 4317
if ($portalListener) {
    Write-Host "  [INFO] port 4317 is in use (PID(s): $($portalListener.OwningProcess -join ', ')) - expected to be the Minions Portal. Do not repurpose it for a SUNIL service." -ForegroundColor DarkGray
} else {
    Write-Line $true "port 4317 is free right now - still never point a SUNIL service at it."
}

# 4/5. .env existence + presence of required keys + the localhost trap -----
Write-Host "`n[4] .env"
$envPath = Join-Path $repoRoot ".env"
$envExists = Test-Path $envPath
Write-Line $envExists ".env exists at repo root"
if (-not $envExists) {
    $warnings.Add("No .env found. Copy .env.example to .env at the repo root and fill in real secrets - never commit .env.")
}

# Required variables, per docs/ARCHITECTURE_V1.md section 14.4.
$requiredKeys = @(
    "DATABASE_URL", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "SESSION_SECRET",
    "SESSION_COOKIE_NAME", "WEB_ORIGIN", "API_HOST", "API_PORT", "LOG_LEVEL",
    "SUNIL_PROGRESS_EVENTS", "SUNIL_CONFIG_DIR", "SUNIL_TURN_DEADLINE_S",
    "OWNER_USERNAME", "OWNER_PASSWORD", "NEXT_PUBLIC_API_BASE_URL"
)
# Secret per section 14.4's own "Secret" column - value is never surfaced by this script.
$secretKeys = @("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "SESSION_SECRET", "OWNER_PASSWORD", "DATABASE_URL")

# Presence-only map for secret keys; full (trimmed) value only for the two
# non-secret keys this script needs to compare (WEB_ORIGIN,
# NEXT_PUBLIC_API_BASE_URL) - everything else is also read but never printed
# below, to keep the "no full-file dump" intent even if the list grows.
$present = @{}
$nonSecretValues = @{}
if ($envExists) {
    foreach ($line in Get-Content -LiteralPath $envPath) {
        if ($line -match '^\s*#') { continue }
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $key = $Matches[1]
            $present[$key] = $true
            if (($secretKeys -notcontains $key) -and ($requiredKeys -contains $key)) {
                $nonSecretValues[$key] = $Matches[2].Trim()
            }
        }
    }
}

Write-Host "  Required variables (secrets: presence only, value never printed):"
foreach ($key in $requiredKeys) {
    $isSecret = $secretKeys -contains $key
    $has = $present.ContainsKey($key)
    if ($has) {
        if ($isSecret) {
            Write-Host "    [OK]   $key present" -ForegroundColor Green
        } else {
            $shown = if ($nonSecretValues.ContainsKey($key)) { " = $($nonSecretValues[$key])" } else { "" }
            Write-Host "    [OK]   $key present$shown" -ForegroundColor Green
        }
    } else {
        if ($envExists) {
            Write-Host "    [WARN] $key MISSING from .env" -ForegroundColor Yellow
            $warnings.Add("$key is missing from .env.")
        }
    }
}

Write-Host "`n[5] Session-cookie trap: localhost vs 127.0.0.1 (ADR-008)"
if ($envExists -and $nonSecretValues.ContainsKey("WEB_ORIGIN") -and $nonSecretValues.ContainsKey("NEXT_PUBLIC_API_BASE_URL")) {
    $webOrigin = $nonSecretValues["WEB_ORIGIN"]
    $apiBase = $nonSecretValues["NEXT_PUBLIC_API_BASE_URL"]
    $trapHit = $false

    if ($webOrigin -match "127\.0\.0\.1") {
        Write-Line $false "WEB_ORIGIN uses 127.0.0.1 ($webOrigin)"
        $failures.Add("WEB_ORIGIN must use 'localhost', not '127.0.0.1' - fix: WEB_ORIGIN=http://localhost:3000. Otherwise SameSite=Lax silently withholds the session cookie across the two 'sites' (ADR-008).")
        $trapHit = $true
    }
    if ($apiBase -match "127\.0\.0\.1") {
        Write-Line $false "NEXT_PUBLIC_API_BASE_URL uses 127.0.0.1 ($apiBase)"
        $failures.Add("NEXT_PUBLIC_API_BASE_URL must use 'localhost', not '127.0.0.1' - fix: NEXT_PUBLIC_API_BASE_URL=http://localhost:8000.")
        $trapHit = $true
    }
    if (-not $trapHit) {
        Write-Line $true "WEB_ORIGIN ($webOrigin) and NEXT_PUBLIC_API_BASE_URL ($apiBase) both use localhost"
    }
} else {
    Write-Host "  [WARN] could not check - .env missing, or WEB_ORIGIN / NEXT_PUBLIC_API_BASE_URL not set yet." -ForegroundColor Yellow
}

# 6. Best-effort API health probe -----------------------------------------
Write-Host "`n[6] API health (best-effort - fine if nothing is running yet)"
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    Write-Line ($resp.StatusCode -eq 200) "GET http://localhost:8000/api/v1/health -> $($resp.StatusCode)"
} catch {
    Write-Host "  [INFO] no response from http://localhost:8000/api/v1/health (not started yet? that's fine)." -ForegroundColor DarkGray
}

# Summary ------------------------------------------------------------------
Write-Host "`n=========================="
if ($failures.Count -gt 0) {
    Write-Host "FAIL - $($failures.Count) blocking issue(s):" -ForegroundColor Red
    foreach ($f in $failures) { Write-Host "  - $f" -ForegroundColor Red }
    if ($warnings.Count -gt 0) {
        Write-Host "Also $($warnings.Count) warning(s):" -ForegroundColor Yellow
        foreach ($w in $warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
    }
    exit 1
} elseif ($warnings.Count -gt 0) {
    Write-Host "OK, with $($warnings.Count) warning(s):" -ForegroundColor Yellow
    foreach ($w in $warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
    exit 0
} else {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
}
