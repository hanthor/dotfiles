# AWS deployment archive

The executable AWS OpenTofu root module, its tests, manual `just` recipes and
AWS KubeVirt node startup helper have been retired from this checkout.
Historical deployment material is preserved at
[`dcbbfbc`](https://github.com/hanthor/dotfiles/tree/dcbbfbc/aws), not as an
active deployment path. Restoring and applying it can recreate paid resources.

Final deletion on **2026-10-29** removed the AWS S3 backups (including the
OpenTofu state backend), Punjab's root volume and all owned snapshots.
Existing off-AWS migration data and vault notes were not deleted; no new
complete archive of the deleted S3 history is claimed. Exact scope and evidence
are documented in the [AWS handbook](../docs/src/servers/aws/README.md).

The ignore rules remain to protect local credentials, variables, state and
plans left from the former deployment. Those local files are not an active
root module and must not be committed.
