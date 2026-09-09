#!/bin/bash
# SUNIL V2 - Postgres first-boot initialisation.
#
# Runs ONCE, on the very first start of an empty pgdata volume, via the
# official postgres image's /docker-entrypoint-initdb.d contract. It will NOT
# re-run against an existing volume - if you change this file you must
# `docker compose down -v` (destroys data) for it to take effect again.
#
# Three jobs:
#   1. enable the `vector` extension in the main SUNIL database
#   2. create the side databases LiteLLM and n8n keep their own state in
#   3. create ONE LEAST-PRIVILEGE LOGIN ROLE PER SIDE DATABASE
#
# On (3) - this is the whole point of the file, so it is spelled out.
# TB9 promises three role/password pairs. The first version of this script
# created the side databases OWNED BY POSTGRES_USER and Compose handed that
# same superuser credential to both LiteLLM and n8n. The security review
# blocked it (B3), and correctly: the `sunil` database will hold `approvals`
# and `audit_events`, and ADR-031's startup re-scan EXECUTES anything it finds
# in state `approved`. A compromised n8n container - the service that runs
# user-authored Code nodes - holding superuser could simply UPDATE an approval
# row to `approved` and have SUNIL carry out the action for it. The C4
# compare-and-swap is only as trustworthy as write access to that table.
#
# So each side service gets a role that:
#   - owns ONLY its own database (so its own migrations work unchanged), and
#   - has CONNECT on `sunil` REVOKED, verifiably.
# CONNECT is also revoked from PUBLIC on all three databases, because the
# implicit PUBLIC grant is what would otherwise make the two REVOKEs above
# cosmetic - any role can connect to any database by default in Postgres.
set -euo pipefail

LITELLM_DB="${SUNIL_LITELLM_DB:-litellm}"
N8N_DB="${SUNIL_N8N_DB:-n8n}"
LITELLM_USER="${SUNIL_LITELLM_DB_USER:-litellm_user}"
N8N_USER="${SUNIL_N8N_DB_USER:-n8n_user}"

# Fail CLOSED. An empty password on a LOGIN role is not "open access" (scram
# auth rejects it) but it IS an unbootable stack that reports itself as a
# healthy Postgres with a broken LiteLLM 90 seconds later. Say so now.
# Compose declares these as ${VAR:?...} so they cannot normally be empty;
# this is the second line of defence for a hand-run container.
for var in SUNIL_LITELLM_DB_PASSWORD SUNIL_N8N_DB_PASSWORD; do
	if [ -z "${!var:-}" ]; then
		echo "[sunil-init] FATAL: ${var} is unset or empty." >&2
		echo "[sunil-init] Set it in .env (see .env.example) and re-create the" >&2
		echo "[sunil-init] volume - this script only runs on an empty volume." >&2
		exit 1
	fi
done

echo "[sunil-init] main db=${POSTGRES_DB} (owner ${POSTGRES_USER})"
echo "[sunil-init] side dbs: ${LITELLM_DB} (owner ${LITELLM_USER}), ${N8N_DB} (owner ${N8N_USER})"

# pgvector in the application database (ADR-013 / ADR-030 S3 - Stream C's
# Mem0 embeddings land here). Done at init time so no migration has to hold
# superuser rights later.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-'SQL'
	CREATE EXTENSION IF NOT EXISTS vector;
	CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL

# --- roles ---------------------------------------------------------------
# `:'var'` is psql's own quoted-literal interpolation: it escapes the value
# as a SQL string literal. Never build this with shell string concatenation -
# a password containing a quote would end the statement.
create_role() {
	local role="$1" pw="$2"
	if [ "$(psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${role}'" \
		--username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}")" = '1' ]; then
		echo "[sunil-init] role ${role} already present, skipping"
		return 0
	fi
	psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" \
		--dbname "${POSTGRES_DB}" -v role="${role}" -v pw="${pw}" <<-'SQL'
		CREATE ROLE :"role" WITH LOGIN PASSWORD :'pw'
			NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
	SQL
	echo "[sunil-init] created role ${role}"
}

create_role "${LITELLM_USER}" "${SUNIL_LITELLM_DB_PASSWORD}"
create_role "${N8N_USER}"     "${SUNIL_N8N_DB_PASSWORD}"

# --- databases -----------------------------------------------------------
# CREATE DATABASE cannot run inside a transaction block or take IF NOT
# EXISTS, so guard it with a catalogue lookup instead.
create_db() {
	local db="$1" owner="$2"
	if [ "$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${db}'" \
		--username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}")" = '1' ]; then
		echo "[sunil-init] database ${db} already present, skipping"
		return 0
	fi
	psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
		-c "CREATE DATABASE \"${db}\" OWNER \"${owner}\""
	echo "[sunil-init] created database ${db} owned by ${owner}"
}

create_db "${LITELLM_DB}" "${LITELLM_USER}"
create_db "${N8N_DB}"     "${N8N_USER}"

# --- privilege fencing ---------------------------------------------------
# Order matters: revoke the implicit PUBLIC grant first, then the two named
# roles explicitly. The named REVOKEs are strictly redundant after the PUBLIC
# one, and they are here on purpose - they are what the negative probe in
# docs/tasks/P0-platform.md asserts, and they survive someone later granting
# CONNECT back to PUBLIC for convenience.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
	-v main="${POSTGRES_DB}" -v lldb="${LITELLM_DB}" -v n8ndb="${N8N_DB}" \
	-v lluser="${LITELLM_USER}" -v n8nuser="${N8N_USER}" <<-'SQL'
	REVOKE CONNECT ON DATABASE :"main"  FROM PUBLIC;
	REVOKE CONNECT ON DATABASE :"lldb"  FROM PUBLIC;
	REVOKE CONNECT ON DATABASE :"n8ndb" FROM PUBLIC;
	-- The application database is off limits to both side services.
	REVOKE ALL ON DATABASE :"main" FROM :"lluser";
	REVOKE ALL ON DATABASE :"main" FROM :"n8nuser";
	-- ...and they are off limits to each other.
	REVOKE ALL ON DATABASE :"lldb"  FROM :"n8nuser";
	REVOKE ALL ON DATABASE :"n8ndb" FROM :"lluser";
	-- Nobody but the owner creates objects in the app database's public
	-- schema. (PG15+ already drops the world-writable default; explicit
	-- anyway, since this volume may outlive the current major version.)
	REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
echo "[sunil-init] privileges fenced: ${LITELLM_USER}/${N8N_USER} cannot connect to ${POSTGRES_DB}"

# --- self-verification ---------------------------------------------------
# Sanity lines in the container log, so a failed vector install or a
# privilege that did not stick is obvious in `docker compose logs postgres`
# rather than at first query. This is not a substitute for the negative
# connection probe (which needs a real client), but it makes the intended
# state readable at a glance.
psql -tAc "SELECT 'pgvector ' || extversion FROM pg_extension WHERE extname='vector'" \
	--username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}"
psql -tAc "SELECT 'db ' || datname || ' owner=' || pg_get_userbyid(datdba)
		|| ' litellm_can_connect=' || COALESCE(has_database_privilege('${LITELLM_USER}', datname, 'CONNECT')::text, '?')
		|| ' n8n_can_connect=' || COALESCE(has_database_privilege('${N8N_USER}', datname, 'CONNECT')::text, '?')
	FROM pg_database WHERE datname IN ('${POSTGRES_DB}', '${LITELLM_DB}', '${N8N_DB}') ORDER BY datname" \
	--username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}"

echo "[sunil-init] done"
