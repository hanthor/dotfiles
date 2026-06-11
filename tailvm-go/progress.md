# Corral Testing Progress

## Pure logic tests
- [x] pkg/catalog/catalog_test.go — 6 tests, all pass
- [x] pkg/config/config_test.go — 7 tests, all pass
- [ ] pkg/doctor/doctor_test.go

## Web handler tests
- [ ] pkg/web/server_test.go — VM lifecycle handlers
- [ ] pkg/web/features_test.go — images, datavolumes, capabilities, scale, snapshots, doctor

## E2E tests
- [ ] test/e2e/ — Playwright against live cluster

## Foundation
- [x] pkg/shell/fake.go — Runner interface + RealRunner + FakeRunner
- [x] pkg/kubevirt/client.go — Client.Runner field + key methods use runner
- [x] pkg/web/server.go — defaultRunner for vmiIndex/handleNodes/handleExport
- [x] pkg/web/testutil_test.go — TestFixture helper for handler tests
