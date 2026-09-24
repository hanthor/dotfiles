#!/usr/bin/env bash
# Run the mock-provider tests (aws/tests/*.tftest.hcl) without touching AWS.
#
# `tofu test` can't run in aws/ directly: mock providers panic on import
# blocks (imports.tf), and a local .terraform/ initialised against the S3
# backend makes init try to reach it. So test a scratch copy of the module
# minus imports.tf, with no backend and no terraform.tfvars.
set -euo pipefail

src="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$src"/*.tf "$src/.terraform.lock.hcl" "$work"/
rm "$work/imports.tf"
cp -r "$src/tests" "$work"/

cd "$work"
tofu init -backend=false -input=false </dev/null >/dev/null
tofu test "$@" </dev/null
