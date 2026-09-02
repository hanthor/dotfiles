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
ORG="${HIVE_REPO_SYNC_ORG:-tuna-os}"

# The org is served by SEVERAL hives, each owning a subject area. A new repo
# has to be routed to exactly one of them — adding it everywhere would have two
# fleets opening competing PRs on the same repo, which is the thing the split
# exists to prevent.
#   name:namespace:one-line charter used as the classifier prompt
HIVES="${HIVE_ROUTER_HIVES:-\
tunaos:hive:the operating system itself — bootable container images, the BuildStream desktop image build, installers, bootc tooling, branding, and OS package/repo publishing (RPM, DEB, Homebrew, Scoop)\
|reef:hive-reef:end-user applications and their distribution — GTK/libadwaita and Rust desktop apps, editors, VM and terminal tools, app indexes and Flatpak distribution, plus developer tooling and docs}"

hive_names() { printf '%s' "$HIVES" | tr '|' '\n' | cut -d: -f1; }
hive_ns()    { printf '%s' "$HIVES" | tr '|' '\n' | awk -F: -v n="$1" '$1==n{print $2}'; }
hive_charter() { printf '%s' "$HIVES" | tr '|' '\n' | awk -F: -v n="$1" '$1==n{sub(/^[^:]*:[^:]*:/,""); print}'; }

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

# ── Per-hive helpers (the API lives in each hive's own pod) ─────────────
pod_for() { kubectl get pods -n "$1" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null; }

sid_for() {
  kubectl exec -n "$1" "$2" -- cat /data/dashboard-sessions.json 2>/dev/null \
    | jq -r 'to_entries | map(select(.value.Role=="owner"))
             | sort_by(.value.ExpiresAt) | reverse | .[0].key // empty' 2>/dev/null
}

api_for() {  # <ns> <pod> <sid> <METHOD> <path> [body]
  kubectl exec -n "$1" "$2" -- curl -sS -X "$4" --max-time 30 \
    -H "Cookie: hive_session=$3" -H 'Content-Type: application/json' \
    "$API$5" ${6:+-d "$6"} 2>&1
}

# ── Classify a new repo into exactly one hive ───────────────────────────
# Asks an AI, because the only durable signal is what the repo IS — its
# description, language and topics — and that is a judgement call no keyword
# list survives. The prompt carries each hive's charter so adding a third hive
# is a config change, not a code change.
#
# Runs headlessly through a hive pod's own agy CLI: no extra credential, no
# extra provider, and it reuses the shared auth the fleet already has. A single
# short prompt per NEW repo only — this is not in any hot path.
classify_repo() {
  local repo="$1" meta desc lang topics prompt out choice names
  names=$(hive_names | tr '\n' ' ')
  meta=$(kubectl exec -n "$NS" "$POD" -- sh -c \
    "curl -sS --max-time 20 -H 'Authorization: Bearer \$(cat /var/run/hive-metrics/gh-app-token.cache 2>/dev/null)' \
     -H 'Accept: application/vnd.github+json' https://api.github.com/repos/$ORG/$repo" 2>/dev/null)
  desc=$(printf '%s' "$meta" | jq -r '.description // ""' 2>/dev/null)
  lang=$(printf '%s' "$meta" | jq -r '.language // "unknown"' 2>/dev/null)
  topics=$(printf '%s' "$meta" | jq -r '(.topics // [])|join(", ")' 2>/dev/null)

  prompt="You are routing a new GitHub repository to exactly one maintenance fleet.
Repository: $repo
Language: $lang
Topics: $topics
Description: $desc

Fleets:"
  local h
  for h in $(hive_names); do
    prompt="$prompt
- $h: $(hive_charter "$h")"
  done
  prompt="$prompt

Answer with ONLY the fleet name, lowercase, nothing else."

  # Try each CLI in turn. A classifier tied to ONE backend stops routing the
  # moment that provider hits a cap — observed immediately: agy answered
  # "Individual quota reached" and every new repo fell through as unroutable.
  # The fleet already keeps several backends authenticated; use them.
  local q; q=$(printf '%q' "$prompt")
  for cli in "agy --print $q --output-format text" \
             "claude -p $q --model claude-haiku-4-5" ; do
    out=$(kubectl exec -n "$NS" "$POD" -- su -s /bin/sh hive-supervisor -c \
          "HOME=/data/home timeout 90 $cli" 2>/dev/null | tr -d '\r' | tr 'A-Z' 'a-z')
    # A quota/auth refusal is not an answer — keep trying the next backend.
    case "$out" in *"quota reached"*|*"usage limit"*|*"please run /login"*|*"not logged in"*) continue ;; esac
    [ -n "$out" ] && break
  done
  # Take the first fleet name that appears, so a chatty model still routes.
  for h in $(hive_names); do
    printf '%s' "$out" | grep -qw "$h" && { echo "$h"; return 0; }
  done
  return 1
}

# ── Gather what every hive already manages ─────────────────────────────
declare -A HPOD HSID HREPOS
ALL_MANAGED=""
for h in $(hive_names); do
  ns=$(hive_ns "$h")
  pod=$(pod_for "$ns"); [ -z "$pod" ] && { echo "WARN: no pod for hive '$h' (ns $ns) — skipping" >&2; continue; }
  sid=$(sid_for "$ns" "$pod")
  # READ with the internal token, which every hive accepts and which needs no
  # browser login. Only WRITES need an owner cookie.
  #
  # Skipping a session-less hive entirely was actively dangerous: its repos
  # then looked unmanaged, and the router would have "discovered" all 18 of
  # reef's repos and added them to tunaos — the exact double-assignment the
  # split exists to prevent. A hive we cannot write to must still be counted.
  tok=$(kubectl get secret -n "$ns" hive-secrets -o jsonpath='{.data.HIVE_DASHBOARD_TOKEN}' 2>/dev/null | base64 -d)
  cfg=$(kubectl exec -n "$ns" "$pod" -- curl -sS --max-time 30 -H "X-Hive-Internal: $tok" "$API/api/config" 2>&1)
  printf '%s' "$cfg" | jq -e '.repos' >/dev/null 2>&1 || { echo "WARN: could not read config for '$h'" >&2; continue; }
  HPOD[$h]=$pod; HSID[$h]=$sid
  [ -z "$sid" ] && echo "  (read-only: no owner session for '$h'; it will be counted but not written to)" >&2
  HREPOS[$h]=$(printf '%s' "$cfg" | jq -r '.repos[]')
  ALL_MANAGED="$ALL_MANAGED"$'\n'"${HREPOS[$h]}"
  printf '%-8s %s repos\n' "$h" "$(printf '%s' "${HREPOS[$h]}" | grep -c . )"
done
[ ${#HPOD[@]} -eq 0 ] && { echo "ERROR: no reachable hives" >&2; exit 1; }

ORG_REPOS=$(installation_repos)
[ -n "$ORG_REPOS" ] || { echo "ERROR: could not list installation repos (App auth or pod issue)" >&2; exit 1; }

# GitHub repo names are case-insensitive-unique within an owner (tuna-os has
# "tunaOS" on GitHub but hive's list stores it "tunaos") — a case-sensitive
# comparison here would "discover" it as new and add a second, colliding
# entry for the same repo every single run.
MANAGED_LOWER=$(printf '%s\n' "$ALL_MANAGED" | tr 'A-Z' 'a-z' | grep -v '^$' | sort -u)
new=""
while IFS= read -r r; do
  [ -z "$r" ] && continue
  case ",$EXCLUDE," in *",$r,"*) continue ;; esac
  rl=$(printf '%s' "$r" | tr 'A-Z' 'a-z')
  printf '%s\n' "$MANAGED_LOWER" | grep -qxF "$rl" && continue
  new="$new$r"$'\n'
done <<< "$ORG_REPOS"

# SHARED repos are deliberate, not drift. `hive` is managed by BOTH hives so
# each fleet can file feedback on the tool it runs on — the OS hive and the app
# hive hit different parts of it and notice different things. The router must
# not "discover" a shared repo as new for the hive that lacks it and re-route
# it away.
#
# The cost is real and bounded: hive's duplicate-PR claim ledger is persisted
# PER HIVE, so it cannot dedupe across hives and both fleets can open
# near-identical PRs. reef sits at ACMM L5, where every PR is held behind a
# `hold` label, so a duplicate is a review-queue annoyance rather than two
# competing auto-merges. Adding more shared repos without that asymmetry would
# not be safe.
SHARED="${HIVE_REPO_SYNC_SHARED:-hive}"
new=$(printf '%s' "$new" | grep -v '^$' || true)

if [ -z "$new" ]; then
  echo "no new repos — the fleet already covers everything the App can see"
  exit 0
fi

echo
echo "new repo(s):"
declare -A ADD
while IFS= read -r r; do
  [ -z "$r" ] && continue
  target=$(classify_repo "$r") || target=""
  if [ -z "$target" ]; then
    # Unroutable is NOT a reason to guess. A repo added to the wrong hive gets
    # a fleet of agents working the wrong backlog, which is worse than a repo
    # nobody has picked up yet.
    printf '  ? %-26s could not classify — left unassigned\n' "$r"
    continue
  fi
  printf '  + %-26s -> %s\n' "$r" "$target"
  ADD[$target]="${ADD[$target]:-}$r"$'\n'
done <<< "$new"

[ ${#ADD[@]} -eq 0 ] && { echo; echo "nothing routable"; exit 0; }
[ "$ACTION" = plan ] && { echo; echo "run '$0 apply' to add them"; exit 0; }

echo
for h in "${!ADD[@]}"; do
  ns=$(hive_ns "$h")
  add=$(printf '%s' "${ADD[$h]}" | grep -v '^$')
  MERGED=$(jq -n --argjson cur "$(printf '%s\n' "${HREPOS[$h]}" | grep -v '^$' | jq -R . | jq -s .)" \
                --argjson add "$(printf '%s\n' "$add" | jq -R . | jq -s .)" \
                '{repos: ($cur + $add)}')
  if [ -z "${HSID[$h]}" ]; then
    printf '%-8s ! cannot write (no owner session) — log in at that hive first\n' "$h" >&2
    continue
  fi
  resp=$(api_for "$ns" "${HPOD[$h]}" "${HSID[$h]}" PUT /api/config/governor/repos "$MERGED")
  status=$(printf '%s' "$resp" | jq -r '.status // .error // "unknown"')
  if [ "$status" = "updated" ]; then
    printf '%-8s added %s repo(s)\n' "$h" "$(printf '%s\n' "$add" | grep -c .)"
  else
    printf '%-8s ! update failed: %s\n' "$h" "$resp" >&2
  fi
done
