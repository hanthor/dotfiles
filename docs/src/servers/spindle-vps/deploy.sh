#!/usr/bin/env bash
# Deploy the standalone Matrix stack (Spindle + MAS + Postgres + LiveKit + lk-jwt-service + Caddy).
# Run on himachal-1: it holds the 2026-10-25 backup and the key that decrypts cluster-state.
#
#   ./deploy.sh <vps-tailnet-ip-or-host> [ssh-user]  full deploy (idempotent)
#   ./deploy.sh --render-only <dir>               write the rendered configs to <dir> and stop
#
# Secrets are read from the age-encrypted cluster-state into a private temp directory, then copied
# into /srv/spindle (0700); they are never printed or committed. No ESS chart or workload runs here.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BK="${BACKUP_DIR:-$HOME/backups/tunaos-aws-2026-10-25}"
STATE="$BK/cluster-state.himachal.tar.gz.age"
DATA_TAR="$BK/s3/postgres/shutdown-export-2026-10-25/ess_ess-spindle-data.tar.gz"
MAS_DUMP="$BK/s3/postgres/2026-10-25/mas.dump"
export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"

render_only=""
if [ "${1:-}" = "--render-only" ]; then render_only="${2:?usage: --render-only <dir>}"; fi
vps="${1:-}"; user="${2:-ubuntu}"
[ -n "$render_only" ] || [ -n "$vps" ] || { sed -n '2,10p' "$0"; exit 2; }

for f in "$STATE" "$DATA_TAR" "$MAS_DUMP"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }; done
for t in age yq jq tar; do command -v "$t" >/dev/null || { echo "need $t" >&2; exit 1; }; done

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
out="${render_only:-$work/out}"
mkdir -p "$out/mas/secrets"

# ── render ────────────────────────────────────────────────────────────────
age -d -i "$HOME/.ssh/id_ed25519" "$STATE" |
  tar xz -C "$work" ./resources/secrets.yaml ./resources/configmaps.yaml
secret() { # secret <namespace> <name> <key>
  yq -o=json '.' "$work/resources/secrets.yaml" |
    jq -er --arg ns "$1" --arg n "$2" --arg k "$3" '.items[]|select(.metadata.namespace==$ns and .metadata.name==$n)|.data[$k]' |
    base64 -d
}
configmap() { # configmap <namespace> <name> <key>
  yq -o=json '.' "$work/resources/configmaps.yaml" |
    jq -er --arg ns "$1" --arg n "$2" --arg k "$3" '.items[]|select(.metadata.namespace==$ns and .metadata.name==$n)|.data[$k]'
}

for k in MAS_SYNAPSE_SHARED_SECRET MAS_ENCRYPTION_SECRET MAS_RSA_PRIVATE_KEY MAS_ECDSA_PRIME256V1_PRIVATE_KEY; do
  secret ess ess-generated "$k" > "$out/mas/secrets/$k"
done
secret ess ess-matrix-authentication-service POSTGRES_PASSWORD > "$out/mas/secrets/POSTGRES_PASSWORD"
secret ess ess-generated ELEMENT_CALL_LIVEKIT_SECRET > "$out/livekit.secret"
jq -n --rawfile secret "$out/livekit.secret" '{"keys":{"matrix-rtc": $secret}}' > "$work/livekit-keys.yaml"
for f in "$out"/mas/secrets/* "$out/livekit.secret"; do [ -s "$f" ] || { echo "empty secret $(basename "$f")" >&2; exit 1; }; done

# Spindle: production runtime base + delegated-auth block preserved from the old deployment.
{
  cat "$KIT/spindle.base.toml"
  printf '\n[auth.delegated]\n'
  printf 'issuer = %s\n' "$(jq -Rn --arg v 'https://auth.reilly.asia/' '$v')"
  printf 'introspection_endpoint = %s\n' "$(jq -Rn --arg v 'http://mas:8080/oauth2/introspect' '$v')"
  printf 'homeserver_secret = %s\n' "$(jq -Rs '.' < "$out/mas/secrets/MAS_SYNAPSE_SHARED_SECRET")"
} > "$out/spindle.toml"

# MAS: the previous deployment's overrides, repointed at this Compose network and secret paths.
configmap ess ess-matrix-authentication-service mas-config-underrides.yaml > "$work/underrides.yaml"
configmap ess ess-matrix-authentication-service mas-config-overrides.yaml |
  sed -e 's#/secrets/ess-matrix-authentication-service/#/config/secrets/#g' \
      -e 's#/secrets/ess-generated/#/config/secrets/#g' \
      -e 's#host: "postgres.postgres.svc.cluster.local"#host: "postgres"#' \
      -e 's#ssl_mode: prefer#ssl_mode: disable#' \
      -e 's#endpoint: "http://ess-synapse.ess.svc.cluster.local.:8008"#endpoint: "http://spindle:8008"#' \
  > "$work/overrides.yaml"
yq eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' "$work/underrides.yaml" "$work/overrides.yaml" > "$out/mas/config.yaml"
grep -q '/secrets/ess-' "$out/mas/config.yaml" && { echo "unrewritten secret path left in MAS config" >&2; exit 1; }
grep -q 'svc.cluster.local' "$out/mas/config.yaml" && { echo "unrewritten cluster hostname left in MAS config" >&2; exit 1; }

cp "$KIT/compose.yaml" "$KIT/Caddyfile" "$out/"
yq eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' "$KIT/livekit.yaml" "$work/livekit-keys.yaml" > "$out/livekit.yaml"
python3 - "$out/spindle.toml" <<'PY'
import sys, tomllib
tomllib.load(open(sys.argv[1], "rb"))
PY
yq '.' "$out/mas/config.yaml" > /dev/null
yq '.' "$out/livekit.yaml" > /dev/null

if [ -n "$render_only" ]; then
  echo "rendered into $render_only (secrets inside; remove it when done)"
  trap - EXIT; rm -rf "$work"; exit 0
fi

# ── ship ──────────────────────────────────────────────────────────────────
ssh_opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
rsh() { ssh "${ssh_opts[@]}" "$user@$vps" "$@"; }
rsh 'docker --version >/dev/null && test -d /srv/spindle' || { echo "VPS not bootstrapped (cloud-init.yaml)" >&2; exit 1; }
[ "$(rsh uname -m)" = aarch64 ] || echo "warning: VPS is not aarch64; the compose image is the arm64 build" >&2

# The containers run as their own uids (Spindle 1000, MAS and Caddy others), so the files they read
# are 0644; the secrets stay private because /srv/spindle itself is 0700 for the ssh user.
rsh 'chmod 700 /srv/spindle'
rsync -a -e "ssh ${ssh_opts[*]}" --chmod=D755,F644 "$out/" "$user@$vps:/srv/spindle/"
rsh '{ test -s /srv/spindle/pg_superuser.secret || (umask 077; openssl rand -hex 24 > /srv/spindle/pg_superuser.secret); }'

# ── data ──────────────────────────────────────────────────────────────────
if ! rsh 'test -f /srv/spindle/data/.restored'; then
  echo "streaming the Spindle store (~4 GB)..."
  rsh 'sudo tar xzf - -C /srv/spindle/data --exclude=./store.pre723 --no-same-owner && sudo chown -R 1000:1000 /srv/spindle/data && sudo touch /srv/spindle/data/.restored' < "$DATA_TAR"
fi
rsync -a -e "ssh ${ssh_opts[*]}" "$MAS_DUMP" "$user@$vps:/srv/spindle/import/mas.dump"

# ── database ──────────────────────────────────────────────────────────────
rsh 'cd /srv/spindle && docker compose up -d postgres'
rsh 'cd /srv/spindle && for i in $(seq 1 60); do docker compose exec -T postgres pg_isready -U postgres && break; sleep 2; done'
# Role and database are created only when missing; the password never appears on a command line
# that is logged (it is passed as a psql variable read from the mounted secret on the VPS).
psql_script=$(cat <<'SQL'
SELECT format('CREATE ROLE mas_user LOGIN PASSWORD %L', :'pw') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mas_user') \gexec
SELECT 'CREATE DATABASE mas OWNER mas_user' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'mas') \gexec
SQL
)
printf '%s\n' "$psql_script" | rsh 'cd /srv/spindle && docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -v pw="$(cat mas/secrets/POSTGRES_PASSWORD)"'
rsh 'cd /srv/spindle && { test -f import/.mas-restored || { docker compose exec -T postgres pg_restore -U postgres -d mas --no-owner --role=mas_user /import/mas.dump && touch import/.mas-restored; }; }'

# ── run ───────────────────────────────────────────────────────────────────
rsh 'cd /srv/spindle && docker compose pull && docker compose run --rm mas database migrate --config /config/config.yaml && docker compose up -d && docker compose restart caddy spindle'
echo "up. Point matrix.reilly.asia, auth.reilly.asia, and call.reilly.asia to 92.5.82.232; keep the reilly.asia Worker domain unchanged, then:"
echo "  curl https://matrix.reilly.asia/_matrix/client/versions"
echo "  curl https://auth.reilly.asia/.well-known/openid-configuration"
echo "  curl -i https://call.reilly.asia/sfu/get  # GET should return 405"
