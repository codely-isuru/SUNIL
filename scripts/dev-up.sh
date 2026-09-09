#!/usr/bin/env bash
# SUNIL V2 - boot the development platform and wait for it to be healthy.
#
# POSIX twin of scripts/dev-up.ps1. Same behaviour, same exit codes.
# Brings up Postgres+pgvector, LiteLLM and n8n, then blocks until every
# service with a healthcheck reports `healthy`.
#
# Idempotent: safe to re-run against an already-running stack.
# No application container is started - branch V2 is a clean-slate rebuild
# and no app code exists yet (ADR-030 Amendment 1).
#
# Usage:
#   ./scripts/dev-up.sh [--timeout SECONDS] [--pull]
set -euo pipefail

TIMEOUT=300
DO_PULL=0
while [ $# -gt 0 ]; do
	case "$1" in
		--timeout) TIMEOUT="$2"; shift 2 ;;
		--pull)    DO_PULL=1; shift ;;
		-h|--help) sed -n '2,16p' "$0"; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

# Always operate from the repo root, whatever directory the caller is in.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE='infra/docker-compose.yml'
ENV_FILE='.env'
# Explicit --env-file: without it Compose looks for infra/.env next to the
# compose file, not the repo-root .env we actually keep.
compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

if [ -t 1 ]; then C='\033[36m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; N='\033[0m';
else C=''; G=''; Y=''; R=''; N=''; fi
step() { printf "${C}==> %s${N}\n" "$1"; }
ok()   { printf "${G}    %s${N}\n" "$1"; }
warn() { printf "${Y}    %s${N}\n" "$1"; }
err()  { printf "${R}    %s${N}\n" "$1" >&2; }

# --- preflight ------------------------------------------------------------
step 'Preflight'

command -v docker >/dev/null 2>&1 || {
	err 'docker is not on PATH. Install Docker Desktop, then re-run.'; exit 1; }

# Check the DAEMON, not just the CLI: `docker --version` answers happily with
# a dead engine.
if ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
	err 'The Docker daemon is not responding. Start Docker Desktop and wait'
	err 'for it to report "Engine running", then re-run this script.'
	exit 1
fi
ok "Docker engine $(docker info --format '{{.ServerVersion}}')"

if [ ! -f "$ENV_FILE" ]; then
	warn 'No .env found - creating one from .env.example (dummy values).'
	cp .env.example "$ENV_FILE"
	warn 'Edit .env before using this stack for anything real.'
fi

# Fail fast and specifically on the required secrets, rather than letting a
# container die with a cryptic error 40 seconds from now.
for required in POSTGRES_PASSWORD LITELLM_MASTER_KEY LITELLM_SALT_KEY N8N_ENCRYPTION_KEY; do
	if ! grep -Eq "^[[:space:]]*${required}[[:space:]]*=[[:space:]]*[^[:space:]]" "$ENV_FILE"; then
		err "${required} is missing or empty in ${ENV_FILE}. See .env.example."
		exit 1
	fi
done
ok 'Required variables present.'

env_val() {
	local v
	v="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
	[ -n "$v" ] && printf '%s' "$v" || printf '%s' "$2"
}

PG_PORT="$(env_val POSTGRES_HOST_PORT 5433)"
LL_PORT="$(env_val LITELLM_HOST_PORT 4000)"
N8_PORT="$(env_val N8N_HOST_PORT 5680)"

# Host-level port check. Learned the hard way: `docker ps` is not enough - a
# host-native process can own the port with no container in sight. ss/lsof
# may be absent (Git Bash on Windows), so this is advisory, never fatal.
port_in_use() {
	if command -v ss >/dev/null 2>&1; then
		ss -ltn 2>/dev/null | grep -Eq "[:.]$1[[:space:]]"
	elif command -v netstat >/dev/null 2>&1; then
		netstat -an 2>/dev/null | grep -Ei 'listen' | grep -Eq "[:.]$1[[:space:]]"
	else
		return 1
	fi
}
OURS="$(compose ps -q 2>/dev/null || true)"
for pair in "postgres:$PG_PORT" "litellm:$LL_PORT" "n8n:$N8_PORT"; do
	name="${pair%%:*}"; port="${pair##*:}"
	if [ "$port" = '4317' ]; then
		err 'Port 4317 is the Minions Portal and must never be bound by this stack.'
		exit 1
	fi
	if [ -z "$OURS" ] && port_in_use "$port"; then
		warn "Port ${port} (${name}) is already LISTENING. If it is not this stack,"
		warn "change the matching *_HOST_PORT in .env - the bind will otherwise fail."
	fi
done

# --- validate -------------------------------------------------------------
step 'Validating compose file'
compose config --quiet
ok "${COMPOSE_FILE} is valid."

# --- boot -----------------------------------------------------------------
if [ "$DO_PULL" -eq 1 ]; then
	step 'Pulling pinned images'
	compose pull
fi

step 'Starting services'
compose up -d --remove-orphans

# --- wait for health ------------------------------------------------------
step "Waiting for healthchecks (timeout ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
last=''

while [ "$(date +%s)" -lt "$deadline" ]; do
	# Query the engine directly rather than parsing `compose ps --format json`,
	# whose shape (array vs NDJSON) varies between Compose releases.
	summary=''; pending=0; failed=''
	for cid in $(compose ps -q 2>/dev/null); do
		svc="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$cid" 2>/dev/null || echo '?')"
		state="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
		health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
		if [ "$health" = 'none' ]; then
			# No healthcheck defined: running is as good as it gets.
			[ "$state" = 'running' ] && shown='healthy' || shown="$state"
		else
			shown="$health"
		fi
		summary="${summary}${svc}=${shown}  "
		case "$shown" in
			healthy) ;;
			unhealthy) failed="${failed}${svc} " ;;
			*) case "$state" in exited|dead) failed="${failed}${svc} " ;; *) pending=1 ;; esac ;;
		esac
	done

	if [ -n "$summary" ] && [ "$summary" != "$last" ]; then
		printf '    %s\n' "$summary"; last="$summary"
	fi

	if [ -n "$failed" ]; then
		err "Service(s) failed: ${failed}"
		for svc in $failed; do compose logs --tail 40 "$svc" || true; done
		exit 1
	fi

	if [ -n "$summary" ] && [ "$pending" -eq 0 ]; then
		ok 'All services healthy.'
		step 'Status'
		compose ps
		echo
		echo "  Postgres  localhost:${PG_PORT}  (databases: $(env_val POSTGRES_DB sunil), $(env_val LITELLM_DB_NAME litellm), $(env_val N8N_DB_NAME n8n))"
		echo "  LiteLLM   http://localhost:${LL_PORT}   (UI /ui, health /health/liveliness)"
		echo "  n8n       http://localhost:${N8_PORT}   (health /healthz)"
		echo
		echo '  No app container yet - clean-slate rebuild (ADR-030 Amendment 1).'
		echo '  Teardown: ./scripts/dev-down.sh'
		exit 0
	fi
	sleep 5
done

err "Timed out after ${TIMEOUT}s waiting for healthchecks."
compose ps
exit 1
