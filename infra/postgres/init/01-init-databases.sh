#!/bin/bash
# SUNIL V2 - Postgres first-boot initialisation.
#
# Runs ONCE, on the very first start of an empty pgdata volume, via the
# official postgres image's /docker-entrypoint-initdb.d contract. It will NOT
# re-run against an existing volume - if you change this file you must
# `docker compose down -v` (destroys data) for it to take effect again.
#
# Two jobs:
#   1. enable the `vector` extension in the main SUNIL database
#   2. create the side databases LiteLLM and n8n keep their own state in
#
# No credentials are set here: both side databases are owned by the same
# POSTGRES_USER the entrypoint already created from the environment.
set -euo pipefail

LITELLM_DB="${SUNIL_LITELLM_DB:-litellm}"
N8N_DB="${SUNIL_N8N_DB:-n8n}"

echo "[sunil-init] main db=${POSTGRES_DB} litellm db=${LITELLM_DB} n8n db=${N8N_DB}"

# pgvector in the application database (ADR-013 / ADR-030 S3 - Stream C's
# Mem0 embeddings land here). Done at init time so no migration has to hold
# superuser rights later.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-'SQL'
	CREATE EXTENSION IF NOT EXISTS vector;
	CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL

# CREATE DATABASE cannot run inside a transaction block or take IF NOT
# EXISTS, so guard it with a catalogue lookup instead.
for db in "${LITELLM_DB}" "${N8N_DB}"; do
	exists=$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${db}'" \
		--username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}")
	if [ "${exists}" = "1" ]; then
		echo "[sunil-init] database ${db} already present, skipping"
	else
		psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
			-c "CREATE DATABASE \"${db}\" OWNER \"${POSTGRES_USER}\""
		echo "[sunil-init] created database ${db}"
	fi
done

# Sanity line in the container log, so a failed vector install is obvious in
# `docker compose logs postgres` rather than at first query.
psql -tAc "SELECT 'pgvector ' || extversion FROM pg_extension WHERE extname='vector'" \
	--username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}"

echo "[sunil-init] done"
