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
# Provider keys are scoped to the LiteLLM container only (ADR-030 S2), so
# they live in their own env file rather than the shared one.
LITELLM_ENV_FILE='infra/.env.litellm'
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

# --- secrets ---------------------------------------------------------------
# The rule this section enforces (Phase 0 security + QA review, D-finding 1):
# THE STACK NEVER BOOTS ON A COMMITTED DUMMY VALUE. The old behaviour was to
# copy .env.example over and check the values were merely non-EMPTY, so a
# clean checkout booted straight onto passwords published in a public repo -
# and with the ports on 0.0.0.0 at the time, that was a LAN-reachable n8n
# credential vault behind a password anyone could read on GitHub.
#
# So: on auto-create, generate real random values; on every run, reject any
# secret still carrying `dummy` or `change-me`.

# 32 hex characters from a CSPRNG. Three sources tried in order because this
# script has to work in Git Bash on Windows, where openssl may be absent and
# /dev/urandom may or may not be wired up. If ALL of them fail we refuse to
# invent a value - a weak secret that looks generated is worse than a hard
# stop that tells the user what to do.
rand_secret() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 24 2>/dev/null && return 0
	fi
	if [ -r /dev/urandom ]; then
		local v
		v="$(LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom 2>/dev/null | head -c 48)"
		if [ "${#v}" -eq 48 ]; then printf '%s' "$v"; return 0; fi
	fi
	if command -v python >/dev/null 2>&1; then
		python -c 'import secrets;print(secrets.token_hex(24))' 2>/dev/null && return 0
	fi
	return 1
}

# Replace `KEY=anything` with `KEY=<value>` in place. Values are hex, so no
# sed metacharacter can appear in the replacement.
set_env_value() {
	local file="$1" key="$2" value="$3"
	if grep -Eq "^[[:space:]]*${key}[[:space:]]*=" "$file"; then
		sed -i.bak -E "s|^[[:space:]]*${key}[[:space:]]*=.*$|${key}=${value}|" "$file"
		rm -f "${file}.bak"
	else
		printf '%s=%s\n' "$key" "$value" >> "$file"
	fi
}

# Rewrite the password inside DATABASE_URL's userinfo, in place.
#
# The app reads DATABASE_URL; Postgres reads POSTGRES_PASSWORD. Generating the
# second without the first left a freshly created .env that boots the stack and
# then refuses every application connection - and the old code only WARNED about
# it, so the failure surfaced later as an authentication error with no
# connection to the message that had scrolled past. Values are hex (rand_secret),
# so nothing needs URL-encoding and no sed metacharacter can appear.
sync_database_url_password() {
	local file="$1" password="$2"
	sed -i.bak -E \
		"s|^([[:space:]]*DATABASE_URL[[:space:]]*=[^:]*://[^:@/]*:)[^@]*@|\\1${password}@|" \
		"$file"
	rm -f "${file}.bak"
	# Verified, not assumed: if the template ever stops matching the shape above,
	# this must fail LOUDLY rather than leave a stale password behind a tick.
	case "$(env_val DATABASE_URL '' "$file")" in
		*":${password}@"*) return 0 ;;
		*) return 1 ;;
	esac
}

env_val() {
	local v file="${3:-$ENV_FILE}"
	[ -f "$file" ] || { printf '%s' "$2"; return 0; }
	v="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$file" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
	[ -n "$v" ] && printf '%s' "$v" || printf '%s' "$2"
}

# Secrets that MUST be real for the three infrastructure services to be
# trustworthy. Anything the app will need but no running process consumes yet
# is warned about instead (see SOFT_SECRETS below) - blocking a platform boot
# on a variable nothing reads would just teach people to bypass this check.
HARD_SECRETS='POSTGRES_PASSWORD LITELLM_MASTER_KEY N8N_ENCRYPTION_KEY LITELLM_DB_PASSWORD N8N_DB_PASSWORD'
SOFT_SECRETS='SESSION_SECRET SUNIL_SERVICE_TOKEN SUNIL_N8N_MCP_AUTH_TOKEN LITELLM_VIRTUAL_KEY_DEFAULT'

if [ ! -f "$ENV_FILE" ]; then
	warn "No ${ENV_FILE} found - creating it from .env.example."
	cp .env.example "$ENV_FILE"
	generated=0
	for k in $HARD_SECRETS $SOFT_SECRETS; do
		# LITELLM_VIRTUAL_KEY_DEFAULT is minted BY LiteLLM (POST /key/generate)
		# against the master key; a random string here would just 401. Leave it
		# for a human and rely on the soft warning.
		[ "$k" = 'LITELLM_VIRTUAL_KEY_DEFAULT' ] && continue
		if v="$(rand_secret)"; then
			# LiteLLM requires its master key to look like an API key.
			case "$k" in LITELLM_MASTER_KEY) v="sk-${v}" ;; esac
			set_env_value "$ENV_FILE" "$k" "$v"
			generated=$((generated + 1))
			# DATABASE_URL embeds this same password; the app would otherwise
			# be handed the template one and fail to authenticate.
			if [ "$k" = 'POSTGRES_PASSWORD' ] && ! sync_database_url_password "$ENV_FILE" "$v"; then
				rm -f "$ENV_FILE"
				err "Could not rewrite DATABASE_URL's password in ${ENV_FILE}, so it"
				err 'would still carry the template value while Postgres used a'
				err "generated one - every app connection would fail. ${ENV_FILE} was"
				err 'NOT created.'
				err "Do this instead:  cp .env.example ${ENV_FILE}  and set DATABASE_URL"
				err 'and POSTGRES_PASSWORD to the same password by hand.'
				exit 1
			fi
		else
			rm -f "$ENV_FILE"
			err 'No source of randomness available (tried openssl, /dev/urandom, python),'
			err "so ${ENV_FILE} was NOT created with dummy values - that would boot the"
			err 'stack on passwords published in a public repository.'
			err "Do this instead:  cp .env.example ${ENV_FILE}  and edit every value"
			err 'marked REQUIRED by hand.'
			exit 1
		fi
	done
	ok "Generated ${generated} random secret(s) into ${ENV_FILE}."
	ok "DATABASE_URL's password was synced to the generated POSTGRES_PASSWORD."
fi

if [ ! -f "$LITELLM_ENV_FILE" ]; then
	warn "No ${LITELLM_ENV_FILE} found - creating it from the template."
	cp infra/.env.litellm.example "$LITELLM_ENV_FILE"
	if v="$(rand_secret)"; then
		set_env_value "$LITELLM_ENV_FILE" LITELLM_SALT_KEY "sk-${v}"
		ok "Generated LITELLM_SALT_KEY into ${LITELLM_ENV_FILE}."
	else
		rm -f "$LITELLM_ENV_FILE"
		err "Could not generate a salt key; create ${LITELLM_ENV_FILE} by hand."
		exit 1
	fi
fi

# Present-and-not-a-dummy, for both files.
check_secret() {
	local key="$1" file="$2" fatal="$3" value
	value="$(env_val "$key" '' "$file")"
	if [ -z "$value" ]; then
		if [ "$fatal" = 'yes' ]; then
			err "${key} is missing or empty in ${file}. See ${file}.example."
			return 1
		fi
		warn "${key} is empty in ${file} (no process needs it yet)."
		return 0
	fi
	# Case-insensitive: the template markers are lowercase, but a human
	# writing CHANGE-ME must not slip through.
	if printf '%s' "$value" | grep -Eqi 'dummy|change-me|changeme'; then
		if [ "$fatal" = 'yes' ]; then
			err "${key} in ${file} is still a TEMPLATE value."
			err 'That value is committed to a PUBLIC repository - it is not a secret.'
			err 'Replace it with a generated value: openssl rand -hex 24'
			return 1
		fi
		warn "${key} in ${file} is still a template value (nothing reads it yet)."
	fi
	return 0
}

secret_failures=0
for key in $HARD_SECRETS; do
	check_secret "$key" "$ENV_FILE" yes || secret_failures=$((secret_failures + 1))
done
check_secret LITELLM_SALT_KEY "$LITELLM_ENV_FILE" yes || secret_failures=$((secret_failures + 1))
for key in $SOFT_SECRETS; do
	check_secret "$key" "$ENV_FILE" no || true
done
# Upstream provider keys are allowed to stay dummy: the proxy boots and
# serves health without them, and this machine has no ambient Anthropic key
# (docs/ENVIRONMENT.md S8). Say so once rather than failing.
for key in ANTHROPIC_API_KEY OPENAI_API_KEY; do
	v="$(env_val "$key" '' "$LITELLM_ENV_FILE")"
	if [ -z "$v" ] || printf '%s' "$v" | grep -Eqi 'dummy|not-a-real'; then
		warn "${key} is a placeholder - completion calls to that provider will fail."
	fi
done
if [ "$secret_failures" -gt 0 ]; then
	err "${secret_failures} secret(s) rejected. Refusing to boot."
	exit 1
fi
ok 'Required secrets present and not template values.'

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
		# 127.0.0.1, never `localhost`. ADR-032 binds every published port to
		# host_ip 127.0.0.1 (the CI port gate asserts it), so nothing is
		# listening on ::1 - and `localhost` resolves to ::1 first on a modern
		# dual-stack host. A client that honours that order (psql, curl, the
		# browser) waits out a connection timeout on the v6 address before
		# falling back, which reads as "the stack is up but hangs".
		echo "  Postgres  127.0.0.1:${PG_PORT}  (databases: $(env_val POSTGRES_DB sunil), $(env_val LITELLM_DB_NAME litellm), $(env_val N8N_DB_NAME n8n))"
		echo "  LiteLLM   http://127.0.0.1:${LL_PORT}   (UI /ui, health /health/liveliness)"
		echo "  n8n       http://127.0.0.1:${N8_PORT}   (health /healthz)"
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
