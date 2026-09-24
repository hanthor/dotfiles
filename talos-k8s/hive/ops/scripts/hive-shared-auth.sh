#!/usr/bin/env bash
# hive-shared-auth.sh — keep ONE credential store working across every spoke.
#
# WHY THIS EXISTS
# ---------------
# The fleet shares one Claude/Gemini/codex login so a single device-flow sign-in
# covers every hive. That sharing is assembled from hand-carved hostPath PVs and
# symlinks, and it has failed silently three separate ways in one week:
#
#   1. A mount that LOOKS fine but is not the shared directory. On this node the
#      same hostPath string can resolve to a different filesystem for a freshly
#      created mount (an existing PV lands on device 0:66, a new one on 0:59 with
#      an empty DirectoryOrCreate). `ls` shows a plausible directory either way.
#      Only writing a file in one spoke and reading it from another proves it.
#   2. Permissions. Token refresh REWRITES the credential file. If the shared dir
#      is not group-writable by `node`, refresh fails and every agent on that
#      backend dies with a login error that looks like an expired subscription.
#   3. `.claude.json` with `theme: null`. hasCompletedOnboarding is true, so
#      nothing looks wrong, but the CLI stops at the theme picker on every launch
#      and the watchdog kill+restarts it forever. Cost reef a whole rotation
#      cycle on 2026-09-06.
#
# So: verify by WRITE-THROUGH, not by looking. Repair what is repairable. Say
# loudly what is not.
#
# USAGE
#   hive-shared-auth.sh check     # verify + report, change nothing
#   hive-shared-auth.sh reconcile # verify, then repair perms/theme

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

set -u

LABEL=app.kubernetes.io/name=hive
NAMESPACES="${HIVE_SHARED_AUTH_NAMESPACES:-hive hive-reef hive-hanthor}"
# Directories under $HOME expected to be the SAME storage in every namespace.
SHARED_DIRS="${HIVE_SHARED_AUTH_DIRS:-.claude .gemini .codex}"
PRIMARY="${HIVE_SHARED_AUTH_PRIMARY:-hive}"
# The agents' home, spelled out. Do NOT use $HOME here: `kubectl exec` runs as
# root and $HOME is /root, so every check silently inspects the wrong directory
# and reports a healthy fleet as broken (and a broken one as repaired).
AHOME="${HIVE_AGENT_HOME:-/data/home}"
ACTION="${1:-check}"
case "$ACTION" in check|reconcile) ;; *) echo "usage: $0 check|reconcile" >&2; exit 2;; esac

rc=0
pod_of() { kubectl get pods -n "$1" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null; }

PPOD=$(pod_of "$PRIMARY")
[ -n "$PPOD" ] || { echo "ERROR: no hive pod in primary namespace $PRIMARY" >&2; exit 1; }

for d in $SHARED_DIRS; do
  # A marker written in the primary must appear in every other spoke. Anything
  # else means that spoke has its own private copy and a login there will not
  # propagate — the exact failure this script exists to catch.
  marker=".shared-auth-probe"
  stamp="probe-$$-$(od -An -N4 -tu4 < /dev/urandom 2>/dev/null | tr -d ' ' || echo fixed)"
  if ! kubectl exec -n "$PRIMARY" "$PPOD" -- sh -c \
        "printf '%s' '$stamp' > $AHOME/$d/$marker" 2>/dev/null; then
    printf '%-10s %-9s PRIMARY NOT WRITABLE — cannot verify\n' "$d" "$PRIMARY"
    rc=1; continue
  fi

  for ns in $NAMESPACES; do
    [ "$ns" = "$PRIMARY" ] && continue
    pod=$(pod_of "$ns")
    if [ -z "$pod" ]; then
      printf '%-10s %-14s no hive pod — skipped\n' "$d" "$ns"
      continue
    fi
    seen=$(kubectl exec -n "$ns" "$pod" -- sh -c "cat $AHOME/$d/$marker 2>/dev/null" 2>/dev/null)
    if [ "$seen" = "$stamp" ]; then
      printf '%-10s %-14s SHARED ok\n' "$d" "$ns"
    else
      printf '%-10s %-14s NOT SHARED — this spoke has a private copy; a login here will not propagate\n' "$d" "$ns"
      rc=1
    fi
  done
  kubectl exec -n "$PRIMARY" "$PPOD" -- sh -c "rm -f $AHOME/$d/$marker" 2>/dev/null || true
done

# ── credential health + the repairs ─────────────────────────────────────
for ns in $NAMESPACES; do
  pod=$(pod_of "$ns"); [ -n "$pod" ] || continue

  tok=$(kubectl exec -n "$ns" "$pod" -- sh -c \
    'jq -r "if ((.claudeAiOauth.accessToken // \"\") == \"\") then \"EMPTY\" else \"ok\" end" \
       '"$AHOME"'/.claude/.credentials.json 2>/dev/null' 2>/dev/null)
  case "$tok" in
    ok)    printf '%-10s %-14s claude token present\n' "creds" "$ns" ;;
    EMPTY) printf '%-10s %-14s CLAUDE TOKEN EMPTY — needs `claude auth login` (one login covers the fleet)\n' "creds" "$ns"; rc=1 ;;
    *)     printf '%-10s %-14s claude credential unreadable\n' "creds" "$ns"; rc=1 ;;
  esac

  # theme:null stops the CLI at the picker forever. Cheap to detect, cheap to fix.
  theme=$(kubectl exec -n "$ns" "$pod" -- sh -c \
    "jq -r '.theme // \"null\"' $AHOME/.claude.json 2>/dev/null" 2>/dev/null)
  if [ "$theme" = "null" ] || [ -z "$theme" ]; then
    if [ "$ACTION" = reconcile ]; then
      # A MISSING .claude.json is not "fine" — the CLI creates one on first run
      # with no theme and stops at the picker, which is the same wedge. Create it.
      # `exit 0` on a missing file would report a repair that never happened.
      kubectl exec -n "$ns" "$pod" -- sh -c "
        f=$AHOME/.claude.json
        if [ ! -f \"\$f\" ]; then
          printf '%s' '{\"theme\":\"dark\",\"hasCompletedOnboarding\":true}' > \"\$f\" || exit 3
          chgrp node \"\$f\" 2>/dev/null; chmod 664 \"\$f\" 2>/dev/null
          exit 0
        fi
        t=\$(mktemp) && jq '.theme = \"dark\" | .hasCompletedOnboarding = true' \"\$f\" > \"\$t\" \\
          && cat \"\$t\" > \"\$f\" && rm -f \"\$t\"" 2>/dev/null \
        && printf '%-10s %-14s theme was unset -> set to dark (was wedging the CLI at the picker)\n' "theme" "$ns" \
        || { printf '%-10s %-14s theme unset and REPAIR FAILED\n' "theme" "$ns"; rc=1; }
    else
      printf '%-10s %-14s THEME UNSET — CLI will stop at the picker; run reconcile\n' "theme" "$ns"
      rc=1
    fi
  fi

  # Token refresh rewrites these files; without group write the refresh fails and
  # presents as an expired subscription.
  if [ "$ACTION" = reconcile ]; then
    kubectl exec -n "$ns" "$pod" -- sh -c '
      for d in '"$SHARED_DIRS"'; do
        p='"$AHOME"'/$d; [ -e "$p" ] || continue
        chgrp -R node "$p" 2>/dev/null || true
        chmod -R g+rwX "$p" 2>/dev/null || true
      done' 2>/dev/null || true
  fi
done

[ "$rc" = 0 ] && echo "shared-auth: all spokes consistent" || echo "shared-auth: PROBLEMS ABOVE"
exit $rc
