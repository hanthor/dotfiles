#!/usr/bin/env bash
# Consolidate the Matrix stack into Spindle: its built-in OIDC provider replaces MAS, its built-in
# LiveKit minter replaces lk-jwt-service, and the MAS-only Postgres stops. README: "Consolidation".
#
#   ./consolidate.sh --render-only <dir>                     render the consolidated kit; reads no secrets
#   SPINDLE_IMAGE=<ref> ./consolidate.sh <vps> [ssh-user]    cut over (Matrix is down for a few minutes)
#   ./consolidate.sh --smoke [vps] [ssh-user]                run the smoke checks again
#   ./consolidate.sh --rollback <vps> [ssh-user]             back to MAS + lk-jwt-service, as it was
#
# The cutover needs no cluster-state: the secrets it uses (the LiveKit secret and the MAS database
# password) are on the VPS already, and it reads them there. Nothing secret is printed or committed.
# Optional settings:
#   SMOKE_USER, SMOKE_PASSWORD, SMOKE_ROOM  a password login, the transport and a call token for a
#                                           room that SMOKE_USER is joined to (room ID)
#   ALLOW_IMAGE_CHANGE=1                    accept a SPINDLE_IMAGE other than the running one
#   SKIP_STORE_BACKUP=1                     do not copy the store before the import
#   ROLLBACK_FROM=<timestamp>               the cutover to undo (default: the newest)
#   RESTORE_STORE=1                         on rollback, also put back the store copied before the
#                                           import (loses everything written since the cutover)
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRV=/srv/spindle
MATRIX=https://matrix.reilly.asia
AUTH=https://auth.reilly.asia
CALL=https://call.reilly.asia
ISSUER="$AUTH/"
MINTER="$MATRIX/_spindle/rtc/livekit"

mode=cutover
case "${1:-}" in
  --render-only) mode=render; out="${2:?usage: --render-only <dir>}" ;;
  --smoke) mode=smoke; shift ;;
  --rollback) mode=rollback; shift ;;
  ""|-h|--help) sed -n '2,23p' "$0"; exit 2 ;;
esac
[ "$mode" = render ] || { vps="${1:-}"; user="${2:-ubuntu}"; }
case "$mode" in cutover|rollback) [ -n "$vps" ] || { sed -n '2,23p' "$0"; exit 2; } ;; esac
for t in python3 jq curl; do command -v "$t" >/dev/null || { echo "need $t" >&2; exit 1; }; done

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
die() { echo "consolidate: $*" >&2; exit 1; }
ssh_opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
rsh() { ssh "${ssh_opts[@]}" "$user@$vps" "$@"; }
q() { printf '%q' "$1"; }

# ── render (no secrets) ───────────────────────────────────────────────────
render() { # render <dir>
  local dir="$1" image="${SPINDLE_IMAGE:-@SPINDLE_IMAGE@}"
  [[ "$image" =~ ^[A-Za-z0-9./:@_-]+$ ]] || die "SPINDLE_IMAGE is not an image reference: $image"
  mkdir -p "$dir"
  sed "s#\"@SPINDLE_IMAGE@\"#\"$image\"#" "$KIT/consolidated/compose.yaml" > "$dir/compose.yaml"
  cp "$KIT/consolidated/Caddyfile" "$KIT/consolidated/livekit.yaml" "$dir/"
  cp "$KIT/consolidated/spindle.base.toml" "$dir/spindle.toml"
  python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$dir/spindle.toml"
  if command -v yq >/dev/null; then
    yq '.' "$dir/compose.yaml" > /dev/null
    yq '.' "$dir/livekit.yaml" > /dev/null
  fi
}

if [ "$mode" = render ]; then
  render "$out"
  [ -n "${SPINDLE_IMAGE:-}" ] || echo "note: SPINDLE_IMAGE unset; compose.yaml keeps the @SPINDLE_IMAGE@ placeholder"
  echo "rendered into $out (no secrets: @LIVEKIT_SECRET@ is filled on the VPS)"
  exit 0
fi

# ── smoke checks ──────────────────────────────────────────────────────────
b64url() { # decode one base64url JWT segment from stdin
  local s; s="$(tr '_-' '/+')"
  while [ $(( ${#s} % 4 )) -ne 0 ]; do s="$s="; done
  printf '%s' "$s" | base64 -d
}

smoke() { # the consolidated shape: Spindle answers login, the provider and the transport
  local failed=0 body="$work/body" auth="$work/auth" status uid dev svc
  ok() { echo "ok    $1"; }
  bad() { echo "FAIL  $1" >&2; failed=1; }
  code() { curl -s -o "$body" -w '%{http_code}' --max-time 20 "$@"; }

  [ "$(code "$MATRIX/_matrix/client/versions")" = 200 ] &&
    jq -e '.unstable_features | has("org.matrix.msc4143") and has("org.matrix.msc4140")' "$body" > /dev/null &&
    ok "/versions" || bad "/versions"
  [ "$(code "$AUTH/.well-known/openid-configuration")" = 200 ] &&
    jq -e --arg i "$ISSUER" '.issuer == $i and .authorization_endpoint == ($i + "oauth2/authorize") and (has("jwks_uri") | not)' "$body" > /dev/null &&
    ok "auth.reilly.asia is Spindle's provider, issuer $ISSUER" || bad "OIDC discovery on $AUTH"
  [ "$(code "$MATRIX/_matrix/client/v1/auth_metadata")" = 200 ] &&
    jq -e --arg i "$ISSUER" '.issuer == $i' "$body" > /dev/null &&
    ok "auth_metadata names $ISSUER" || bad "auth_metadata"
  [ "$(code "$AUTH/account/login")" = 200 ] && ok "account sign-in page" || bad "$AUTH/account/login"
  [ "$(code "$MATRIX/_matrix/client/v3/login")" = 200 ] &&
    jq -e '[.flows[].type] | index("m.login.password") != null' "$body" > /dev/null &&
    ok "/login offers m.login.password" || bad "/login flows"
  [ "$(code -X POST -H 'Content-Type: application/json' --data '{}' "$MATRIX/_matrix/client/v3/register")" = 401 ] &&
    jq -e '[.flows[].stages[]] | index("m.login.registration_token") != null and index("m.login.dummy") == null' "$body" > /dev/null &&
    ok "registration needs a token" || bad "registration is not token-gated"
  [ "$(code "$MINTER/sfu/get")" = 405 ] && ok "minter routed on matrix.reilly.asia" || bad "$MINTER/sfu/get"
  [ "$(code "$CALL/sfu/get")" = 405 ] && ok "call.reilly.asia/sfu/get reaches the minter" || bad "$CALL/sfu/get"
  [ "$(code -X POST "$CALL/delegate_delayed_leave")" = 404 ] && ok "transport delegation probe: 404" || bad "$CALL/delegate_delayed_leave"
  [ "$(code "$CALL/")" = 200 ] && ok "LiveKit answers on call.reilly.asia" || bad "LiveKit on $CALL"

  if [ -n "${vps:-}" ]; then
    rsh "cd $SRV && docker compose exec -T caddy wget -S -O /dev/null --post-data '{}' http://spindle:8008/_spindle/rtc/livekit/sfu/webhook 2>&1 || true" |
      grep -q ' 401' && ok "SFU webhook reachable on the compose network (unsigned: 401)" || bad "SFU webhook"
  fi

  if [ -n "${SMOKE_USER:-}" ] && [ -n "${SMOKE_PASSWORD:-}" ] && [ -n "${SMOKE_ROOM:-}" ]; then
    status="$(jq -n --arg u "$SMOKE_USER" --arg p "$SMOKE_PASSWORD" \
      '{type: "m.login.password", identifier: {type: "m.id.user", user: $u}, password: $p, initial_device_display_name: "consolidate.sh smoke"}' |
      code -X POST -H 'Content-Type: application/json' --data @- "$MATRIX/_matrix/client/v3/login" || true)"
    if [ "$status" = 200 ]; then
      ok "password login"
      printf 'Authorization: Bearer %s\n' "$(jq -r .access_token "$body")" > "$auth"
      uid="$(jq -r .user_id "$body")"; dev="$(jq -r .device_id "$body")"
      [ "$(code -H @"$auth" "$MATRIX/_matrix/client/v1/rtc/transports")" = 200 ] &&
        jq -e --arg u "$MINTER" '.rtc_transports[0] == {type: "livekit", livekit_service_url: $u}' "$body" > /dev/null &&
        ok "rtc/transports names $MINTER first" || bad "rtc/transports"
      if [ "$(code -X POST -H @"$auth" -H 'Content-Type: application/json' --data '{}' \
        "$MATRIX/_matrix/client/v3/user/$(jq -rn --arg u "$uid" '$u | @uri')/openid/request_token")" = 200 ]; then
        cp "$body" "$work/openid"
        for svc in "$MINTER" "$CALL"; do
          jq -n --arg room "$SMOKE_ROOM" --arg dev "$dev" --slurpfile o "$work/openid" \
            '{room: $room, openid_token: $o[0], device_id: $dev}' |
            code -X POST -H 'Content-Type: application/json' --data @- "$svc/sfu/get" > "$work/status"
          if [ "$(cat "$work/status")" = 200 ] && jq -e '.url == "wss://call.reilly.asia"' "$body" > /dev/null &&
            jq -r .jwt "$body" | cut -d. -f2 | b64url |
              jq -e --arg room "$SMOKE_ROOM" '.video.roomJoin and .video.canPublish and .video.room != $room' > /dev/null; then
            ok "call token from $svc/sfu/get (publish, hashed room)"
          else
            bad "call token from $svc/sfu/get"
          fi
        done
      else
        bad "openid/request_token"
      fi
      [ "$(code -X POST -H @"$auth" -H 'Content-Type: application/json' --data '{}' "$MATRIX/_matrix/client/v3/logout")" = 200 ] &&
        ok "logout" || bad "logout"
      rm -f "$auth" "$body"
      if [ -n "${vps:-}" ]; then
        rsh "cd $SRV && docker compose logs --since 10m spindle 2>&1" | grep -q "the SFU refused to create a call's room" &&
          bad "the minter could not create the room on the SFU (hairpin to call.reilly.asia?)" || ok "the SFU created the call's room"
      fi
    else
      bad "password login (HTTP $status)"
    fi
  else
    echo "skip  login and call token: set SMOKE_USER, SMOKE_PASSWORD and SMOKE_ROOM"
  fi
  return "$failed"
}

smoke_previous() { # the shape the rollback restores: MAS and lk-jwt-service
  local failed=0 body="$work/body"
  code() { curl -s -o "$body" -w '%{http_code}' --max-time 20 "$@"; }
  [ "$(code "$MATRIX/_matrix/client/versions")" = 200 ] && echo "ok    /versions" || { echo "FAIL  /versions" >&2; failed=1; }
  [ "$(code "$AUTH/.well-known/openid-configuration")" = 200 ] && jq -e 'has("jwks_uri")' "$body" > /dev/null &&
    echo "ok    auth.reilly.asia is MAS again" || { echo "FAIL  MAS discovery" >&2; failed=1; }
  [ "$(code "$CALL/sfu/get")" = 405 ] && echo "ok    call.reilly.asia/sfu/get (lk-jwt-service)" || { echo "FAIL  $CALL/sfu/get" >&2; failed=1; }
  return "$failed"
}

wait_versions() {
  for _ in $(seq 1 150); do # five minutes: a cold start loads the store
    curl -fs --max-time 5 -o /dev/null "$MATRIX/_matrix/client/versions" && return 0
    sleep 2
  done
  return 1
}

if [ "$mode" = smoke ]; then smoke; exit; fi

# ── rollback ──────────────────────────────────────────────────────────────
if [ "$mode" = rollback ]; then
  from="${ROLLBACK_FROM:-$(rsh "ls -1 $SRV/consolidation 2>/dev/null | sort | tail -n 1")}"
  [[ "$from" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "no cutover to undo under $SRV/consolidation"
  b="$SRV/consolidation/$from/backup"
  rsh "test -s $b/compose.yaml && test -s $b/Caddyfile && test -s $b/spindle.toml && test -s $b/livekit.yaml" ||
    die "$b does not hold the previous configuration"
  echo "rolling back to the configuration saved at $from"
  rsh "cd $SRV && docker compose stop spindle"
  if [ "${RESTORE_STORE:-}" = 1 ]; then
    rsh "test -d $b/store" || die "$b/store missing (SKIP_STORE_BACKUP was set); the store stays as it is"
    rsh "sudo mv $SRV/data/store $SRV/data/store.after-consolidation-$from && sudo cp -a $b/store $SRV/data/store"
  fi
  # MAS, its Postgres and lk-jwt-service come back with the old compose file; their data never changed.
  rsh "cd $SRV && cp -p $b/compose.yaml $b/Caddyfile $b/spindle.toml $b/livekit.yaml $SRV/ && rm -f .consolidated &&
    docker compose up -d --remove-orphans && docker compose restart livekit caddy"
  wait_versions || die "/versions does not answer after the rollback"
  smoke_previous || die "the previous stack is not back; inspect: cd $SRV && docker compose ps"
  echo "rolled back. Users sign in through MAS again; the imported accounts stay in the store, unused."
  exit 0
fi

# ── cutover: preflight ────────────────────────────────────────────────────
: "${SPINDLE_IMAGE:?set SPINDLE_IMAGE to the arm64 image built with FEATURES=mas-import (README, Consolidation)}"
image="$SPINDLE_IMAGE"
render "$work/new"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
stage="$SRV/consolidation/$ts"

rsh "test -d $SRV && test ! -e $SRV/.consolidated" || die "$SRV is missing or already consolidated"
rsh "cd $SRV && docker compose ps --services --status running" > "$work/running"
for s in spindle mas postgres livekit matrixrtc-auth caddy; do
  grep -qx "$s" "$work/running" || die "$s is not running; the cutover starts from the running MAS stack"
done
rsh "docker network inspect spindle_default > /dev/null" || die "no spindle_default network"
rsh "docker pull -q $(q "$image") > /dev/null" || die "cannot pull $image"
rsh "docker run --rm $(q "$image") import-mas 2>&1 || true" | grep -q 'usage: spindle import-mas' ||
  die "$image has no import-mas: build it with FEATURES=mas-import"
running="$(rsh "docker inspect --format '{{.Image}}' \$(cd $SRV && docker compose ps -q spindle)")"
wanted="$(rsh "docker image inspect --format '{{.Id}}' $(q "$image")")"
if [ "$running" != "$wanted" ] && [ "${ALLOW_IMAGE_CHANGE:-}" != 1 ]; then
  die "the running Spindle is not $image. Upgrade first (its own change), so this cutover changes configuration only; or set ALLOW_IMAGE_CHANGE=1"
fi
if [ "${SKIP_STORE_BACKUP:-}" != 1 ]; then
  need="$(rsh "sudo du -sk $SRV/data/store | cut -f1")"
  free="$(rsh "df -Pk $SRV | awk 'NR == 2 { print \$4 }'")"
  [ "$free" -gt $(( need * 2 )) ] || die "not enough disk to copy the store ($need KiB, $free KiB free); free some or set SKIP_STORE_BACKUP=1"
fi

# ── stage the new configuration; fill its secrets on the VPS ──────────────
rsh "mkdir -p $stage/new $stage/backup $stage/reports"
rsync -a -e "ssh ${ssh_opts[*]}" --chmod=D755,F644 "$work/new/" "$user@$vps:$stage/new/"
rsh "python3 - $stage/new" <<'PY'
import json, pathlib, sys, tomllib, yaml
stage = pathlib.Path(sys.argv[1])
# The secret the SFU runs with now, so the key pair does not change.
secret = yaml.safe_load(open("/srv/spindle/livekit.yaml"))["keys"]["matrix-rtc"]
assert isinstance(secret, str) and secret, "no matrix-rtc key in the live livekit.yaml"
for name in ("spindle.toml", "livekit.yaml"):
    path = stage / name
    text = path.read_text()
    assert text.count('"@LIVEKIT_SECRET@"') == 1, f"{name}: placeholder missing"
    path.write_text(text.replace('"@LIVEKIT_SECRET@"', json.dumps(secret)))
config = tomllib.loads((stage / "spindle.toml").read_text())
assert config["rtc"]["livekit"]["secret"] == secret and "delegated" not in config["auth"]
assert yaml.safe_load((stage / "livekit.yaml").read_text())["keys"]["matrix-rtc"] == secret
print("staged configuration filled")
PY
rsh "cd $SRV && docker compose -f $stage/new/compose.yaml --project-directory $SRV config -q"

# ── backup, stop ──────────────────────────────────────────────────────────
rsh "cd $SRV && cp -p compose.yaml Caddyfile spindle.toml livekit.yaml $stage/backup/"
echo "stopping Spindle, MAS and lk-jwt-service: the outage starts"
rsh "cd $SRV && docker compose stop spindle mas matrixrtc-auth"
abort() {
  echo "consolidate: $*; restarting the previous stack (nothing switched)" >&2
  rsh "cd $SRV && docker compose up -d"
  exit 1
}
rsh "cd $SRV && docker compose exec -T postgres pg_dump -U postgres -Fc mas > $stage/backup/mas.dump" || abort "pg_dump of MAS failed"
if [ "${SKIP_STORE_BACKUP:-}" != 1 ]; then
  echo "copying the store to $stage/backup/store"
  rsh "sudo cp -a $SRV/data/store $stage/backup/store" || abort "store copy failed"
fi

# ── import ────────────────────────────────────────────────────────────────
import_mas() { # import_mas <report> [--dry-run]
  local report="$1"; shift
  rsh "cd $SRV && SPINDLE_MAS_DB_PASSWORD=\"\$(cat mas/secrets/POSTGRES_PASSWORD)\" docker run --rm \
    --network spindle_default -e SPINDLE_MAS_DB_PASSWORD \
    -v $SRV/data:/var/lib/spindle-data -v $stage/new/spindle.toml:/etc/spindle/spindle.toml:ro -v $SRV/mas:/config:ro \
    $(q "$image") import-mas /etc/spindle/spindle.toml \
    --mas-database 'host=postgres port=5432 user=mas_user dbname=mas' --mas-config /config/config.yaml $* \
    > $stage/reports/$report.json"
  local status=$?
  echo "── $report report ($stage/reports/$report.json)"
  rsh "cat $stage/reports/$report.json"
  return "$status"
}
import_mas dry-run --dry-run || abort "the dry run refused something or failed; see the report"
import_mas import || abort "the import refused something or failed; see the report (a rerun continues it)"

# ── switch, start ─────────────────────────────────────────────────────────
rsh "cd $SRV && cp $stage/new/compose.yaml $stage/new/Caddyfile $stage/new/spindle.toml $stage/new/livekit.yaml $SRV/ &&
  echo $ts > .consolidated && docker compose up -d --remove-orphans && docker compose restart livekit caddy"
echo "switched; MAS, Postgres and lk-jwt-service are stopped, their data in $SRV/mas and $SRV/pg"
wait_versions || die "/versions does not answer. Roll back: ./consolidate.sh --rollback $vps $user"
if ! smoke; then
  echo "smoke checks failed. Roll back: ROLLBACK_FROM=$ts ./consolidate.sh --rollback $vps $user" >&2
  exit 1
fi
echo "consolidated ($ts). Backups and reports: $SRV/consolidation/$ts. Everyone signs in again once."
