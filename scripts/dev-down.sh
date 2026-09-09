#!/usr/bin/env bash
# SUNIL V2 - tear down the development platform.
#
# POSIX twin of scripts/dev-down.ps1.
#
# Named volumes are KEPT by default, so Postgres data, LiteLLM virtual keys
# and n8n workflows survive a normal down/up cycle.
#
# Usage:
#   ./scripts/dev-down.sh              # stop containers, keep data
#   ./scripts/dev-down.sh --volumes    # DESTRUCTIVE: also delete all data
#   ./scripts/dev-down.sh --volumes --force
#
# Note: the Postgres first-boot init script
# (infra/postgres/init/01-init-databases.sh) only runs on an empty volume, so
# --volumes is also how you make a change to it take effect.
set -euo pipefail

WITH_VOLUMES=0
FORCE=0
while [ $# -gt 0 ]; do
	case "$1" in
		--volumes|-v) WITH_VOLUMES=1; shift ;;
		--force|-f)   FORCE=1; shift ;;
		-h|--help)    sed -n '2,17p' "$0"; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE='.env'
[ -f "$ENV_FILE" ] || ENV_FILE='.env.example'
compose() { docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml "$@"; }

if ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
	echo '    The Docker daemon is not responding - nothing to tear down.'
	exit 0
fi

if [ "$WITH_VOLUMES" -eq 1 ]; then
	if [ "$FORCE" -ne 1 ]; then
		echo 'This DELETES all platform data:'
		echo '  - the SUNIL Postgres database (incl. pgvector data)'
		echo '  - LiteLLM virtual keys and spend history'
		echo '  - every n8n workflow and stored credential'
		printf 'Type DELETE to confirm: '
		read -r answer
		[ "$answer" = 'DELETE' ] || { echo 'Aborted.'; exit 1; }
	fi
	echo '==> Stopping services and removing volumes'
	compose down --volumes --remove-orphans
else
	echo '==> Stopping services (volumes kept)'
	compose down --remove-orphans
fi

echo '    Done. Bring it back with ./scripts/dev-up.sh'
