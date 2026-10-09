# platform_detect

Detects libc flavor once per run and publishes `is_musl` / `is_termux` facts
for other roles to gate on, instead of each role re-implementing the same
`stat` checks.

- **Runs on:** every host, first in the play (tagged `always`)
- **Tags:** `always`
- **Sets:** `is_musl`, `is_termux`

| Fact | How it's detected |
|---|---|
| `is_musl` | `/lib/ld-musl-{x86_64,aarch64}.so.1` exists |
| `is_termux` | `/data/data/com.termux/files/usr` exists |

Consumed by `apk_packages` (musl-only), `homebrew` (unsupported on musl or
Termux), and `termux_packages`.
