# Progress

## Status
Done — test suite complete and CI-ready

## Tasks
- [x] Hermetic unit tests for every package (no cluster/kubectl/virtctl needed)
- [x] doctor: refactored onto shell.Runner seam; tests no longer touch the live cluster
- [x] qemu: fixed journalctl-follow test hang; fake binaries via temp PATH (not /home/linuxbrew)
- [x] kubevirt: features_test.go (migrate, scale live/offline, volumes, snapshots, clone, DV library, capabilities, CreateVM paths) — 47.7% → 75.3%
- [x] CI: race detector, bootc tag set, coverage report + artifact

## Files Changed
- pkg/doctor/doctor.go, doctor_test.go (runner seam + hermetic tests, 100% cover)
- pkg/qemu/qemu.go (findQEMU checks PATH first), qemu_test.go
- pkg/kubevirt/client.go (ExposedPorts → runPkg), features_test.go (new)
- .github/workflows/ci.yml (race, bootc tag, coverage summary)
- HANDOFF.md (test-suite section)

## Notes
- Suite verified green against an empty PATH (CI-equivalent: no kubectl/virtctl).
- `-race` cannot run on this Pi (TSan VMA 47-bit limitation) — runs in CI on amd64.
- Live e2e remains behind `-tags integration` + scripts/smoke-web.sh.
