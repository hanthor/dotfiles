# Pure logic tests — complete

## Files created

- `pkg/catalog/catalog_test.go` (6 tests)
- `pkg/config/config_test.go` (7 tests)

## Results

```
go test ./pkg/catalog/ ./pkg/config/ -count=1
ok  github.com/hanthor/corral/pkg/catalog  0.002s
ok  github.com/hanthor/corral/pkg/config   0.002s
```

## Catalog tests

| Test | What it checks | Result |
|---|---|---|
| TestFind_Found | Find("fedora") returns non-nil, correct fields | ✅ |
| TestFind_NotFound | Find("nonexistent-os") returns nil | ✅ |
| TestFind_EmptyName | Find("") returns nil | ✅ |
| TestCatalog_NotEmpty | Images slice has entries, all have name/disk/user | ✅ |
| TestCatalog_AllFindable | Every image in Images is Find()-able | ✅ |
| TestFind_CaseSensitive | "Fedora" ≠ "fedora" (case-sensitive lookup) | ✅ |

## Config tests

| Test | What it checks | Result |
|---|---|---|
| TestAuthKey_FromEnv | TS_AUTHKEY env var is returned | ✅ |
| TestAuthKey_FromFile | Load() reads auth_key from YAML | ✅ |
| TestAuthKey_EnvOverFile | AuthKey() returns env value over file value | ✅ |
| TestAuthKey_None | Returns "" when nothing is set | ✅ |
| TestLoad_Empty | Load of nonexistent file returns empty config, no error | ✅ |
| TestLoad_InvalidYAML | Load of malformed YAML returns error | ✅ |
| TestDefaultPath | DefaultPath() uses HOME/.config/tailvm/config.yaml | ✅ |

## Notes

- `TestAuthKey_EnvOverFile` documents that `AuthKey()` checks environment
  variable before config file (env takes precedence).
- All tests use only Go's standard `testing` package — zero dependencies.
- Env vars are isolated via `t.Setenv()` so tests don't interfere with each
  other or the host environment.
