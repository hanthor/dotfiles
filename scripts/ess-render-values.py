#!/usr/bin/env python3
"""Render the production ESS Helm values for the AWS cluster.

Reads the `ess-helm-values` secure note from Bitwarden on stdin, applies the
cutover substitutions, and writes the result to stdout for `helm ... -f -`.

Deliberately never touches disk: the values contain the Synapse signing key and
Postgres passwords inline (this chart takes literal values, not existingSecret
refs). Pipe it, don't save it.

    bw get notes <ess-helm-values-id> \
      | scripts/ess-render-values.py \
      | helm upgrade --install ess oci://ghcr.io/element-hq/ess-helm/matrix-stack \
          --version 26.8.1 -n ess -f -
"""
import sys

import yaml

# New cluster's matrix-role worker EIP.
NEW_IP = "13.62.161.5"
PG_HOST = "postgres.postgres.svc.cluster.local"
CLUSTER_ISSUER = "letsencrypt-cloudflare"
MEDIA_CLAIM = "synapse-media-preseed"


def main() -> int:
    values = yaml.safe_load(sys.stdin.read())

    # Postgres moves from the old host's local instance to in-cluster.
    values["synapse"]["postgres"]["host"] = PG_HOST
    values["matrixAuthenticationService"]["postgres"]["host"] = PG_HOST
    values.setdefault("postgres", {})["enabled"] = False

    # The SFU advertises its public IP to clients; hostAliases pins the
    # homeserver name for the SFU's own lookups. Both were the old box.
    values["matrixRTC"]["sfu"]["manualIP"] = NEW_IP
    for alias in values["matrixRTC"].get("hostAliases", []):
        alias["ip"] = NEW_IP

    # Issuer name differs on the new cluster (DNS-01 via Cloudflare).
    values["certManager"]["clusterIssuer"] = CLUSTER_ISSUER

    # Reuse the pre-synced media PVC instead of provisioning an empty one.
    values["synapse"].setdefault("media", {}).setdefault("storage", {})[
        "existingClaim"
    ] = MEDIA_CLAIM

    values.setdefault("ingress", {})["className"] = "traefik"

    yaml.safe_dump(values, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
