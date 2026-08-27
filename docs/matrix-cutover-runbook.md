# Matrix/ESS cutover runbook (Hetzner `matrix` → AWS Talos cluster)

Status 2026-08-27: **CUTOVER COMPLETE.** Downtime 08:47:27Z → 09:05:55Z (~18.5 min).
Federation identity preserved (`ed25519:a_qMqD`), Synapse `v1.156.0`, 1371 users, 4.6GB media.

## Ingress deviation discovered during cutover — READ THIS

The new cluster's Traefik Service is `type: LoadBalancer` and sits **`<pending>` forever** — Talos on EC2 has
no cloud-controller-manager to provision an ELB. Public traffic works only because the Traefik *Deployment*
binds **hostPorts 80/443**, on whatever node it happens to run.

Consequences, all live now:
- Traefik runs on the **control-plane node** `ip-10-20-1-10` / **`13.63.243.56`**, so the four Matrix A records
  point there — *not* at `13.62.161.5` as originally planned. `hive.tunaos.org` already depended on Traefik
  being on that node, so moving Traefik would have broken it.
- Traefik was a single unpinned replica: a reschedule would have silently broken all ingress. It is now pinned
  with `nodeSelector: kubernetes.io/hostname=ip-10-20-1-10` and `strategy: Recreate` (a RollingUpdate cannot
  work with hostPorts — the new pod can't bind ports the old one holds, and hangs `Pending`).
- **This patch is not in the Traefik Helm values** — a `helm upgrade` of Traefik will revert it. Fold the
  nodeSelector + Recreate strategy into the release's values, or convert Traefik to a DaemonSet (better: both
  node IPs then serve, removing the single point of failure).
- Both nodes carry the `migration-matrix-public` SG, so either IP is publicly reachable on 80/443/8448/RTC.
- Port **8448 is not exposed** and does not need to be: `.well-known/matrix/server` delegates federation to
  `matrix.reilly.asia:443`. Federation was verified working on 443.

Chart `matrix-stack 26.8.1` (OCI `ghcr.io/element-hq/ess-helm/matrix-stack`), release `ess`, namespace `ess`.

## Key facts

| Thing | Value |
|---|---|
| `server_name` | `reilly.asia` (apex, delegated via `.well-known`) |
| **`key_id` baseline** | **`ed25519:a_qMqD`** — must match after cutover |
| `.well-known/matrix/server` | `{"m.server": "matrix.reilly.asia:443"}` |
| Old host public IPv4 | `37.27.84.201` |
| New worker EIP | `13.62.161.5` (`ip-10-20-1-11`, `workload-role=matrix`) |
| Cloudflare zone ID | `a0635f63d8d945d51db9aa20a967f666` |
| Synapse DB | 16GB, `C`/`C`, PG 16.15, user **`synapse_user`**, db `synapse` |
| MAS DB | 22MB, `en_US.UTF-8`, user **`mas_user`**, db **`mas`** |
| Synapse image | **pinned `v1.156.0`** — chart default is v1.159.0. Keep the pin: avoids a schema migration inside the window. |
| Dump+restore | ~7m41s measured end-to-end |

**AWS auth**: the ambient `login`-type session expires. Use the IAM keys in Bitwarden item `aws-james-admin`
(`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in its notes), and `unset AWS_SESSION_TOKEN`.

## THE critical procedure: pre-seed `ess-generated` with the right labels

`ess-generated` holds MAS's encryption secret and RSA/ECDSA keys. It is **not** Helm-managed — it is created by
the `init-secrets` job. Its 7 keys are *not* in the Helm values, so a fresh install would mint new ones and MAS
could no longer decrypt the restored `mas` database.

Verified empirically (twice, in throwaway namespaces):

- Pre-creating the Secret **without** the ownership labels → `init-secrets` **hard-fails** with
  `secret ... is not managed by this matrix-tools-init-secrets`, the job retries forever and the install
  **hangs**. This would strand the cutover past the point of no return.
- Pre-creating it **with** the labels below → job completes in ~7s and **all 7 keys are preserved**.

```yaml
metadata:
  labels:
    app.kubernetes.io/component: matrix-tools
    app.kubernetes.io/instance: ess-init-secrets        # <release>-init-secrets
    app.kubernetes.io/managed-by: matrix-tools-init-secrets
    app.kubernetes.io/name: init-secrets
    app.kubernetes.io/part-of: matrix-stack
    app.kubernetes.io/version: 0.8.1
```
Keys to seed from Bitwarden `ess-secret-ess-generated`: `MAS_ENCRYPTION_SECRET`, `MAS_RSA_PRIVATE_KEY`,
`MAS_ECDSA_PRIME256V1_PRIVATE_KEY`, `MAS_SYNAPSE_OIDC_CLIENT_SECRET`, `MAS_SYNAPSE_SHARED_SECRET`,
`ELEMENT_CALL_LIVEKIT_SECRET`, `SYNAPSE_EXTRA`.

`init-secrets` only fills in keys that are *absent*, so seeding all 7 means it generates nothing.

**`ess-synapse` and `ess-matrix-authentication-service` must NOT be pre-created.** They are Helm-managed and
fully reconstructed from the values file (`MACAROON`, `SIGNING_KEY`, `REGISTRATION_SHARED_SECRET`,
`POSTGRES_PASSWORD`, `user-99-cache-tuning`, `user-0-adminClient` all come from values).

## Values substitutions (base = Bitwarden `ess-helm-values`)

| Path | Old | New |
|---|---|---|
| `synapse.postgres.host` | `37.27.84.201` | `postgres.postgres.svc.cluster.local` |
| `matrixAuthenticationService.postgres.host` | `37.27.84.201` | `postgres.postgres.svc.cluster.local` |
| `matrixRTC.sfu.manualIP` | `37.27.84.201` | `13.62.161.5` |
| `matrixRTC.hostAliases[0].ip` | `37.27.84.201` | `13.62.161.5` |
| `certManager.clusterIssuer` | `letsencrypt-prod` | `letsencrypt-cloudflare` |
| `postgres.enabled` | (unset) | `false` |
| `synapse.media.storage.existingClaim` | (unset) | `synapse-media-preseed` |
| `ingress.className` | (unset) | `traefik` |

Never write the populated values file to disk unencrypted and never `cat`/`head` it — the fields are long
single lines and will spill the signing key into logs. Pipe Bitwarden → python → `helm -f -`.

`helm template` with these values was diffed against production: identical resource set apart from the
intended changes. No PVC is rendered (correct — `existingClaim` reuses the pre-seeded one).

## DNS: five records, not three

All currently `37.27.84.201`, all TTL now 60s, all DNS-only (grey cloud — required for 8448 federation).

| Record | ID | Serves |
|---|---|---|
| `matrix.reilly.asia` | `14af8e9f1579505c91f6554786da76ee` | Synapse |
| `auth.reilly.asia` | `17f217f8c543008c2f7f0a40c5e6462e` | MAS |
| `call.reilly.asia` | `1c93410562a522cc5f07ff79849cee77` | MatrixRTC |
| `matrixadmin.reilly.asia` | `70e0db68dc4d618751c961651c9b7866` | elementAdmin (in ESS chart) |
| `chat.reilly.asia` | `34b243e04cab932c558bb90c2c0e7a3e` | **cinny — NOT in the ESS chart** |

## Decisions taken

1. **cinny / `chat.reilly.asia`** — retired at James's direction ("no state saved there"). The DNS record was
   deleted at cutover. The Deployment still exists on the old box and dies with it in Phase 6.
2. **Window** — executed 2026-08-27 08:47–09:06Z.

## Post-cutover result (verified)

- `federationtester.matrix.org`: **FederationOK: True**, `13.63.243.56:443`, `AllChecksOK: true`
- `key_id` `ed25519:a_qMqD` — **unchanged**, federation identity intact
- Synapse `v1.156.0` (pinned version preserved; no schema migration occurred)
- Data: 176 tables, 1371 users, 247 rooms, 1,467,646 events, `C`/`C` collation; MAS 34 tables / 5 users
- Media: 4.6GB mounted at `/media`; delta rsync transferred 0 files (pre-sync was complete)
- All 9 ESS pods Running incl. redis + all three Synapse workers
- cert-manager issued/renewed **all five** certs via Cloudflare DNS-01 (`Ready=True`)
- `ess-generated` retained exactly the 7 original keys — MAS can decrypt the restored database

## Cutover sequence

Downtime spans steps 2→7. Expect 10–20 min.

1. **Pre-flight**: `auto-upgrade.timer` still disabled on `matrix`; new cluster nodes Ready; Bitwarden unlocked;
   AWS creds loaded from `aws-james-admin`.
2. **Point of no return — scale old Synapse to zero, never restart:**
   ```
   kubectl scale statefulset ess-synapse-main ess-synapse-fed-sender ess-synapse-sliding-sync -n ess --replicas=0
   kubectl scale deployment ess-matrix-authentication-service -n ess --replicas=0
   ```
3. **Pre-seed `ess-generated`** on the new cluster with the labels + 7 keys above.
4. **Recreate target DBs empty, matching source collation**, then dump+restore direct pod-to-pod:
   ```
   DROP DATABASE synapse; CREATE DATABASE synapse ENCODING 'UTF8' LC_COLLATE='C' LC_CTYPE='C' TEMPLATE template0 OWNER synapse_user;
   DROP DATABASE mas;     CREATE DATABASE mas     ENCODING 'UTF8' LC_COLLATE='en_US.UTF-8' LC_CTYPE='en_US.UTF-8' TEMPLATE template0 OWNER mas_user;
   ```
   (`synapse_user` / `mas_user` must exist with the passwords from the values file.)
5. **Delta rsync** media into `synapse-media-preseed` — pod → `james@37.27.84.201`, `--rsync-path="sudo rsync"`.
   Requires the UFW pinhole for `13.62.161.5` *inserted before* the broad `22/tcp DENY` rule (first-match-wins).
6. **`helm install ess`** chart 26.8.1 with the substituted values.
7. **Verify before flipping DNS** — `curl --resolve` against `13.62.161.5`: Synapse `/health`, MAS `/health`,
   and `/_matrix/key/v2/server` returning **`ed25519:a_qMqD`**. Abort here if anything is off; this is the last
   clean rollback point.
8. **Flip DNS** — PATCH all five A records to `13.62.161.5`.
9. **Post-cutover verification** (all must pass): federationtester clean; `key_id` matches; 8448 reachable
   externally; `.well-known` server+client resolve; live message round-trip with a matrix.org user.
10. **Close out**: remove the UFW pinhole, delete `transfer-ssh-key` Secret, revoke the throwaway key from
    `authorized_keys` on `matrix`/`telengana`.

## Rollback reality

"Power off, don't destroy" holds **only until the new instance serves its first client write.** After that,
rollback loses everything written to the new server. The real rollback plan is *abort before step 8*.

## Completed prep

- [x] `auto-upgrade.timer` disabled on `matrix` (it ran `helm upgrade --install ess` daily → split-brain risk)
- [x] Rehearsal install validated on the new cluster; `init-secrets` behaviour proven with sentinel values
- [x] SG `sg-09803bdbcc7b9273a`: 80, 443, 8448, 30001/tcp, 30002/udp, **32700-32767/udp** (RTC range)
- [x] Media pre-synced — 4.6GB / 95,370 files → PVC `synapse-media-preseed` (only a delta needed at cutover)
- [x] TLS certs for matrix/auth/call copied (valid to Sep 27 / Nov 1 2026)
- [x] cert-manager + `ClusterIssuer/letsencrypt-cloudflare` (DNS-01), **validated end-to-end** with a real cert
- [x] All five DNS TTLs at 60s
- [x] ESS secrets verified complete in Bitwarden

## Follow-ups (deliberately deferred)

- **`matrix` nightly backups are broken** — `synapse_db_*.sql.gz` 0 bytes since ~Aug 5; `mas_db` stopped
  May 15. `just backup` pipes `sudo -u postgres pg_dump` to gzip; the pipe creates the file even when the dump
  fails, so it failed silently. Real DR gap, independent of this migration.
- `external-dns` — deliberately **not** installed pre-cutover: it would flip DNS the instant the ESS Ingress
  appeared, pre-empting step 7 verification. Install after, with `--policy=upsert-only`.
- Rotate `ess-synapse-certmanager-tls` key, the two ESS Postgres passwords, and the registration shared secret
  (all exposed in a session transcript). **Do NOT rotate the Synapse signing key** — it is the federation identity.
- EBS snapshot lifecycle (DLM) on the Postgres volume + `pg_dump` to S3.
- 50GB gp3 volume `vol-01ff00a316340f0ad` is EC2-attached but **not mounted by Talos**; Postgres currently runs
  on `local-path` on the node root volume. Architectural deviation worth resolving.
- Kubernetes API OIDC + finer-grained RBAC (deferred from Phase 3).
