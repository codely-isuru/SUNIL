#!/usr/bin/env bash
# SUNIL V2 - complete n8n's first-boot setup and import Stream E's workflows.
#
# POSIX twin of scripts/n8n-setup.ps1. Same behaviour, same exit codes.
#
# What it does, in order:
#   1. boots the platform if n8n is not answering (scripts/dev-up.sh);
#   2. completes the OWNER SETUP with generated credentials, stored in .env;
#   3. creates/updates the two n8n credentials that hold SUNIL's bearer tokens;
#   4. imports and activates every workflow in infra/n8n/workflows/.
#
# IDEMPOTENT. Re-running it re-syncs credentials and workflows in place; it
# never creates a second copy of either.
#
# WHY THIS EXISTS AT ALL. n8n 2.x serves an UNAUTHENTICATED owner-setup screen
# until somebody claims it: whoever reaches the port first owns the credential
# vault. Compose binds the port to 127.0.0.1 (ADR-032), which closes the window
# to processes on this host - and this script closes it to a human who forgets.
# Setting the owner from a script also means the password is a generated value
# nobody ever types, which is the only kind a dev instance keeps.
#
# NO SECRET IS EVER PRINTED OR COMMITTED. Every value it generates or reads
# lives in .env, which .gitignore covers. The bearer tokens go into n8n's own
# encrypted vault (N8N_ENCRYPTION_KEY) and are substituted into workflows BY
# CREDENTIAL ID, so the committed JSON in infra/n8n/workflows/ carries a
# placeholder and never a token.
#
# Usage:
#   ./scripts/n8n-setup.sh [--no-activate] [--timeout SECONDS]
set -euo pipefail

NO_ACTIVATE=0
TIMEOUT=300
while [ $# -gt 0 ]; do
	case "$1" in
		--no-activate) NO_ACTIVATE=1; shift ;;
		--timeout)     TIMEOUT="$2"; shift 2 ;;
		-h|--help)     sed -n '2,27p' "$0"; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE='.env'
WORKFLOW_DIR='infra/n8n/workflows'
BROWSER_ID='sunil-n8n-setup'
COOKIE_JAR="$(mktemp -t sunil-n8n-cookies.XXXXXX)"
trap 'rm -f "$COOKIE_JAR"' EXIT

if [ -t 1 ]; then C='\033[36m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; N='\033[0m';
else C=''; G=''; Y=''; R=''; N=''; fi
step() { printf "${C}==> %s${N}\n" "$1"; }
ok()   { printf "${G}    %s${N}\n" "$1"; }
warn() { printf "${Y}    %s${N}\n" "$1"; }
err()  { printf "${R}    %s${N}\n" "$1" >&2; }

# --- preflight ------------------------------------------------------------
step 'Preflight'
command -v curl >/dev/null 2>&1 || { err 'curl is not on PATH.'; exit 1; }
PY=''
for candidate in python python3; do
	command -v "$candidate" >/dev/null 2>&1 && { PY="$candidate"; break; }
done
[ -n "$PY" ] || { err 'python is required (JSON handling). Install it, then re-run.'; exit 1; }
[ -f "$ENV_FILE" ] || { err "No ${ENV_FILE}. Run ./scripts/dev-up.sh first - it creates one with generated secrets."; exit 1; }

env_val() {
	local v
	v="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
	[ -n "$v" ] && printf '%s' "$v" || printf '%s' "${2:-}"
}

set_env_value() {
	local key="$1" value="$2"
	if grep -Eq "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE"; then
		sed -i.bak -E "s|^[[:space:]]*${key}[[:space:]]*=.*$|${key}=${value}|" "$ENV_FILE"
		rm -f "${ENV_FILE}.bak"
	else
		printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
	fi
}

rand_hex() {
	if command -v openssl >/dev/null 2>&1; then openssl rand -hex 18 2>/dev/null && return 0; fi
	"$PY" -c 'import secrets;print(secrets.token_hex(18))' 2>/dev/null && return 0
	return 1
}

N8N_PORT="$(env_val N8N_HOST_PORT 5680)"
# 127.0.0.1, never `localhost`: the published port is v4-loopback only
# (ADR-032), and `localhost` resolves to ::1 first on a dual-stack host.
BASE="http://127.0.0.1:${N8N_PORT}"

SERVICE_TOKEN="$(env_val SUNIL_SERVICE_TOKEN)"
MCP_TOKEN="$(env_val SUNIL_N8N_MCP_AUTH_TOKEN)"
for pair in "SUNIL_SERVICE_TOKEN:$SERVICE_TOKEN" "SUNIL_N8N_MCP_AUTH_TOKEN:$MCP_TOKEN"; do
	name="${pair%%:*}"; value="${pair#*:}"
	if [ -z "$value" ] || printf '%s' "$value" | grep -Eqi 'dummy|change-me|changeme'; then
		err "${name} in ${ENV_FILE} is empty or still a TEMPLATE value."
		err 'Those values are committed to a public repository - they are not secrets.'
		err 'Generate real ones (openssl rand -hex 24) before wiring n8n to them.'
		exit 1
	fi
done
ok 'Both bearer tokens are present and are not template values.'

# --- the stack ------------------------------------------------------------
n8n_up() { curl -fsS -o /dev/null --max-time 5 "${BASE}/healthz" 2>/dev/null; }

step "Checking n8n on ${BASE}"
if n8n_up; then
	ok 'Already answering /healthz.'
else
	warn 'Not answering - booting the platform (scripts/dev-up.sh).'
	./scripts/dev-up.sh --timeout "$TIMEOUT" >/dev/null || { err 'dev-up.sh failed. Run it directly to see why.'; exit 1; }
	n8n_up || { err "n8n still not answering on ${BASE}/healthz."; exit 1; }
	ok 'Booted and healthy.'
fi

api() {
	# api METHOD PATH [JSON-BODY]
	local method="$1" path="$2" body="${3:-}"
	if [ -n "$body" ]; then
		curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X "$method" "${BASE}${path}" \
			-H 'content-type: application/json' -H "browser-id: ${BROWSER_ID}" \
			--data-binary "$body"
	else
		curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X "$method" "${BASE}${path}" \
			-H "browser-id: ${BROWSER_ID}"
	fi
}

# Read one JSON path out of stdin. Never echoes anything it was not asked for,
# which is why every response in this script is piped through it rather than
# printed: an n8n response body can contain a credential.
jq_get() { "$PY" -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print(''); raise SystemExit(0)
for key in sys.argv[1].split('.'):
    if d is None: break
    d = d.get(key) if isinstance(d, dict) else None
print('' if d is None else d)
" "$1"; }

# --- owner ----------------------------------------------------------------
step 'Owner setup'
NEEDS_SETUP="$(api GET /rest/settings | jq_get data.userManagement.showSetupOnFirstLoad)"
OWNER_EMAIL="$(env_val N8N_OWNER_EMAIL sunil-owner@sunil.local)"
OWNER_PASSWORD="$(env_val N8N_OWNER_PASSWORD)"

if [ -z "$OWNER_PASSWORD" ]; then
	# n8n's own rule: >= 8 chars, at least one number and one capital.
	if ! hex="$(rand_hex)"; then
		err 'No source of randomness available; refusing to invent an owner password.'
		exit 1
	fi
	OWNER_PASSWORD="Sx${hex}A9"
	set_env_value N8N_OWNER_EMAIL "$OWNER_EMAIL"
	set_env_value N8N_OWNER_PASSWORD "$OWNER_PASSWORD"
	ok "Generated an owner password into ${ENV_FILE} (N8N_OWNER_PASSWORD)."
fi

owner_body() {
	"$PY" -c "
import json,sys
print(json.dumps({'email':sys.argv[1],'firstName':'SUNIL','lastName':'Owner','password':sys.argv[2]}))
" "$OWNER_EMAIL" "$OWNER_PASSWORD"
}
login_body() {
	"$PY" -c "
import json,sys
print(json.dumps({'emailOrLdapLoginId':sys.argv[1],'password':sys.argv[2]}))
" "$OWNER_EMAIL" "$OWNER_PASSWORD"
}

if [ "$NEEDS_SETUP" = 'True' ] || [ "$NEEDS_SETUP" = 'true' ]; then
	id="$(api POST /rest/owner/setup "$(owner_body)" | jq_get data.id)"
	[ -n "$id" ] || { err 'Owner setup was refused. Check the n8n logs (docker logs <project>-n8n).'; exit 1; }
	ok "Owner claimed as ${OWNER_EMAIL} - the unauthenticated setup screen is now closed."
else
	ok 'Owner already set.'
fi

id="$(api POST /rest/login "$(login_body)" | jq_get data.id)"
if [ -z "$id" ]; then
	err "Could not sign in as ${OWNER_EMAIL}."
	err "If this instance was set up by hand, put that owner's credentials in ${ENV_FILE}"
	err '(N8N_OWNER_EMAIL / N8N_OWNER_PASSWORD) and re-run.'
	exit 1
fi
ok 'Signed in.'

# --- credentials ----------------------------------------------------------
# The tokens live in n8n's ENCRYPTED VAULT, and the workflows reference them by
# id. That is what keeps infra/n8n/workflows/*.json committable: the exported
# JSON carries a placeholder id and a credential NAME, never a token.
step 'Credentials'
CREDENTIALS_JSON="$(api GET /rest/credentials)"

credential_id_by_name() {
	printf '%s' "$CREDENTIALS_JSON" | "$PY" -c "
import json,sys
try:
    rows=json.load(sys.stdin).get('data') or []
except Exception:
    rows=[]
print(next((r.get('id','') for r in rows if r.get('name')==sys.argv[1]), ''))
" "$1"
}

credential_body() {
	"$PY" -c "
import json,sys
print(json.dumps({'name':sys.argv[1],'type':'httpBearerAuth','data':{'token':sys.argv[2]}}))
" "$1" "$2"
}

ensure_credential() {
	# ensure_credential NAME TOKEN -> prints the credential id
	local name="$1" token="$2" existing
	existing="$(credential_id_by_name "$name")"
	if [ -n "$existing" ]; then
		# PATCH keeps the id stable, so a token rotation does not orphan every
		# workflow that references it.
		api PATCH "/rest/credentials/${existing}" "$(credential_body "$name" "$token")" >/dev/null
		printf '%s' "$existing"
	else
		api POST /rest/credentials "$(credential_body "$name" "$token")" | jq_get data.id
	fi
}

SERVICE_CRED_ID="$(ensure_credential 'SUNIL service token' "$SERVICE_TOKEN")"
MCP_CRED_ID="$(ensure_credential 'SUNIL MCP bearer' "$MCP_TOKEN")"
[ -n "$SERVICE_CRED_ID" ] && [ -n "$MCP_CRED_ID" ] || { err 'Could not create the n8n credentials.'; exit 1; }
ok "'SUNIL service token' and 'SUNIL MCP bearer' are in n8n's vault (ids not printed)."

# --- workflows ------------------------------------------------------------
step 'Workflows'
WORKFLOWS_JSON="$(api GET /rest/workflows)"

workflow_id_by_name() {
	printf '%s' "$WORKFLOWS_JSON" | "$PY" -c "
import json,sys
try:
    rows=json.load(sys.stdin).get('data') or []
except Exception:
    rows=[]
print(next((r.get('id','') for r in rows if r.get('name')==sys.argv[1]), ''))
" "$1"
}

prepare() {
	# prepare FILE OUT - substitute credential ids and strip SUNIL's own `meta`
	# block (documentation for readers of the repo; n8n's API rejects unknown
	# top-level keys).
	"$PY" - "$1" "$2" "$SERVICE_CRED_ID" "$MCP_CRED_ID" <<'PYEOF'
import json, pathlib, sys
src, dest, service_id, mcp_id = sys.argv[1:5]
text = pathlib.Path(src).read_text(encoding="utf-8")
text = text.replace("__SUNIL_SERVICE_TOKEN_CREDENTIAL_ID__", service_id)
text = text.replace("__SUNIL_MCP_BEARER_CREDENTIAL_ID__", mcp_id)
doc = json.loads(text)
doc.pop("meta", None)
payload = {k: doc[k] for k in ("name", "nodes", "connections", "settings") if k in doc}
pathlib.Path(dest).write_text(json.dumps(payload), encoding="utf-8")
print(payload["name"])
PYEOF
}

imported=0
for file in "$WORKFLOW_DIR"/*.json; do
	[ -f "$file" ] || continue
	prepared="$(mktemp -t sunil-n8n-wf.XXXXXX)"
	name="$(prepare "$file" "$prepared")"
	existing="$(workflow_id_by_name "$name")"
	if [ -n "$existing" ]; then
		wf_id="$(api PATCH "/rest/workflows/${existing}" "$(cat "$prepared")" | jq_get data.id)"
		action='updated'
	else
		wf_id="$(api POST /rest/workflows "$(cat "$prepared")" | jq_get data.id)"
		action='created'
	fi
	rm -f "$prepared"
	if [ -z "$wf_id" ]; then
		err "Could not import ${file}."
		exit 1
	fi

	if [ "$NO_ACTIVATE" -eq 1 ]; then
		ok "${name}: ${action} (left inactive, --no-activate)."
	else
		# Activation is its own endpoint in n8n 2.x and needs the CURRENT
		# versionId - PATCHing `{"active": true}` is accepted with a 200 and
		# silently does nothing, which reads as "imported fine" right up until
		# the webhook answers 404.
		version="$(api GET "/rest/workflows/${wf_id}" | jq_get data.versionId)"
		activate_body="$("$PY" -c "
import json,sys
print(json.dumps({'versionId':sys.argv[1]}))
" "$version")"
		active="$(api POST "/rest/workflows/${wf_id}/activate" "$activate_body" | jq_get data.active)"
		if [ "$active" = 'True' ] || [ "$active" = 'true' ]; then
			ok "${name}: ${action} and ACTIVE."
		else
			warn "${name}: ${action}, but activation did not take. Activate it in the editor."
		fi
	fi
	imported=$((imported + 1))
done
ok "${imported} workflow(s) processed from ${WORKFLOW_DIR}/."

# --- what the app needs next ----------------------------------------------
step 'Done'
echo
echo "  Editor         ${BASE}  (owner: ${OWNER_EMAIL}, password in ${ENV_FILE})"
echo "  MCP endpoint   ${BASE}/mcp/sunil   - Bearer only; 403 without it"
echo
echo '  SUNIL must point at the workflow PATH, not at the /mcp prefix:'
echo "      host-native   SUNIL_N8N_MCP_BASE_URL=${BASE}/mcp/sunil"
echo '      in-network    SUNIL_N8N_MCP_BASE_URL=http://n8n:5678/mcp/sunil'
echo
echo '  Teardown: ./scripts/dev-down.sh'
