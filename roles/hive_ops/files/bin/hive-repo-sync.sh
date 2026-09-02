#!/usr/bin/env bash
# hive-repo-sync.sh — keep Hive's managed repo list in sync with the tuna-os
# GitHub org, so a newly created repo gets picked up without a manual
# `hive.yaml` edit + apply (which, per docs/src/servers/aws-k8s/cluster.md's
# config-layering notes, wouldn't even take effect — project.repos is owned
# by the dashboard-overlay, not the ConfigMap seed).
#
# WHY THE POD, NOT `gh` ON THE HOST
# ----------------------------------
# The obvious approach is `gh api orgs/tuna-os/repos` from himachal. Rejected:
# this runs unattended under a systemd --user timer, and `gh`'s token here is
# keyring-backed (`gh auth status` -> "Token: gho_... (keyring)") — a login
# keyring that may not be unlocked in a timer's session, an unattended-cron
# footgun this script has no business depending on. The hive pod already has
# a working, correctly-scoped credential for exactly this: its GitHub App key.
# `GET /installation/repositories` (using a fresh installation token, minted
# from the App JWT) returns exactly the repos this hive's App can act on —
# for a repository_selection:"all" install, that IS "every repo in the org",
# with no separate access-check needed, because if it's in this list the App
# already has access by construction.
#
# USAGE
#   hive-repo-sync.sh plan     # show what would be added, no changes
#   hive-repo-sync.sh apply    # add newly discovered repos
#
# Env:
#   HIVE_REPO_SYNC_EXCLUDE   comma-separated bare repo names to never add
#                            (e.g. sandbox/experiment repos hive shouldn't touch)

# Cluster-aware kubeconfig. Running IN the cluster (a CronJob under the
# hive-ops ServiceAccount) there is no kubeconfig at all — kubectl must use the
# in-cluster service account. Defaulting KUBECONFIG to a workstation path there
# makes every kubectl call fail with a missing-file error that reads like the
# hive is down. Note `${VAR:=default}` fires on EMPTY as well as unset, so
# passing KUBECONFIG="" from a pod spec is not enough on its own.
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

set -u

NS=hive
LABEL=app.kubernetes.io/name=hive
API=http://127.0.0.1:3002
EXCLUDE="${HIVE_REPO_SYNC_EXCLUDE:-}"

ACTION="${1:-plan}"
case "$ACTION" in plan|apply) ;; *) echo "usage: $0 plan|apply" >&2; exit 2;; esac

POD=$(kubectl get pods -n "$NS" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$POD" ] || { echo "ERROR: no hive pod found" >&2; exit 1; }

SID=$(kubectl exec -n "$NS" "$POD" -- cat /data/dashboard-sessions.json 2>/dev/null \
      | jq -r '
          to_entries | map(select(.value.Role=="owner"))
          | sort_by(.value.ExpiresAt) | reverse | .[0].key // empty' 2>/dev/null)
if [ -z "$SID" ]; then
  echo "ERROR: no unexpired owner session in the dashboard session store." >&2
  echo "       Log in at https://hive.tunaos.org as an authorized_users member." >&2
  exit 1
fi

hive_api() {
  kubectl exec -n "$NS" "$POD" -- \
    curl -sS -X "$1" --max-time 25 -H "Cookie: hive_session=$SID" -H 'Content-Type: application/json' "$API$2" ${3:+-d "$3"} 2>&1
}

# The App's own view of what it can act on — see header comment for why this
# beats listing the org directly. Runs entirely inside the pod; the App
# private key never leaves it.
installation_repos() {
  kubectl exec -n "$NS" "$POD" -- sh -c '
    APP_ID='"$(kubectl get secret -n hive hive-secrets -o jsonpath='{.data.GH_APP_ID}' | base64 -d)"'
    INST_ID='"$(kubectl get secret -n hive hive-secrets -o jsonpath='{.data.GH_APP_INSTALLATION_ID}' | base64 -d)"'
    PEM=/etc/hive-secrets/gh-app-key.pem
    [ -f "$PEM" ] || PEM=$(find / -maxdepth 4 -iname "gh-app-key.pem" 2>/dev/null | head -1)
    NOW=$(date +%s); IAT=$((NOW-60)); EXP=$((NOW+300))
    B64() { openssl base64 -e -A | tr "+/" "-_" | tr -d "="; }
    HEADER=$(printf "{\"alg\":\"RS256\",\"typ\":\"JWT\"}" | B64)
    PAYLOAD=$(printf "{\"iat\":%s,\"exp\":%s,\"iss\":\"%s\"}" "$IAT" "$EXP" "$APP_ID" | B64)
    SIG=$(printf "%s.%s" "$HEADER" "$PAYLOAD" | openssl dgst -sha256 -sign "$PEM" | B64)
    JWT="$HEADER.$PAYLOAD.$SIG"
    ITOK=$(curl -sS -X POST -H "Authorization: Bearer $JWT" -H "Accept: application/vnd.github+json" \
           "https://api.github.com/app/installations/$INST_ID/access_tokens" | jq -r ".token")
    [ -z "$ITOK" ] || [ "$ITOK" = "null" ] && exit 1
    page=1
    while :; do
      out=$(curl -sS -H "Authorization: Bearer $ITOK" -H "Accept: application/vnd.github+json" \
            "https://api.github.com/installation/repositories?per_page=100&page=$page")
      n=$(printf "%s" "$out" | jq -r ".repositories | length")
      [ "$n" = "0" ] || [ -z "$n" ] && break
      printf "%s" "$out" | jq -r ".repositories[] | select(.archived==false and .disabled==false) | .name"
      [ "$n" -lt 100 ] && break
      page=$((page+1))
    done
  ' 2>/dev/null
}

CONFIG_JSON=$(hive_api GET /api/config)
printf '%s' "$CONFIG_JSON" | jq -e '.repos' >/dev/null 2>&1 \
  || { echo "ERROR: could not read /api/config -> ${CONFIG_JSON:0:200}" >&2; exit 1; }
CURRENT=$(printf '%s' "$CONFIG_JSON" | jq -r '.repos[]')

ORG_REPOS=$(installation_repos)
[ -n "$ORG_REPOS" ] || { echo "ERROR: could not list installation repos (App auth or pod issue)" >&2; exit 1; }

# GitHub repo names are case-insensitive-unique within an owner (tuna-os has
# "tunaOS" on GitHub but hive's list stores it "tunaos") — a case-sensitive
# comparison here would "discover" it as new and add a second, colliding
# entry for the same repo every single run.
CURRENT_LOWER=$(printf '%s\n' "$CURRENT" | tr 'A-Z' 'a-z')
new=""
while IFS= read -r r; do
  [ -z "$r" ] && continue
  case ",$EXCLUDE," in *",$r,"*) continue ;; esac
  rl=$(printf '%s' "$r" | tr 'A-Z' 'a-z')
  printf '%s\n' "$CURRENT_LOWER" | grep -qxF "$rl" && continue
  new="$new$r"$'\n'
done <<< "$ORG_REPOS"
new=$(printf '%s' "$new" | grep -v '^$' || true)

if [ -z "$new" ]; then
  echo "no new repos — fleet already covers everything the App can see"
  exit 0
fi

echo "new repo(s) found:"
printf '%s\n' "$new" | sed 's/^/  + /'

[ "$ACTION" = plan ] && { echo; echo "run '$0 apply' to add them"; exit 0; }

MERGED=$(jq -n --argjson cur "$(printf '%s\n' "$CURRENT" | jq -R . | jq -s .)" \
              --argjson add "$(printf '%s\n' "$new" | jq -R . | jq -s .)" \
              '{repos: ($cur + $add)}')
resp=$(hive_api PUT /api/config/governor/repos "$MERGED")
status=$(printf '%s' "$resp" | jq -r '.status // .error // "unknown"')
if [ "$status" = "updated" ]; then
  echo "added $(printf '%s\n' "$new" | grep -c .) repo(s)"
else
  echo "! update failed: $resp" >&2
  exit 1
fi
