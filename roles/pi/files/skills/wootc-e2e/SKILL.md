---
name: wootc-e2e
description: Run and debug Windows E2E tests for the wootc project using QEMU Guest Agent as the control plane. Covers PowerShell safety rules, QGA primitives, Kanpur VM quirks, and the full test/debug cycle. Use when running wootc E2E tests, debugging Windows OEM failures, working with QGA, or touching setup-wootc.ps1 or autounattend.xml.
---

# wootc E2E Testing

## Quick start

```bash
# On kanpur (KVM host):
cd ~/wootc && just build-deployer    # builds deployer + wubildr
cd tests/e2e && bash run-e2e.sh --keep   # full E2E with QGA control
```

The run takes ~30 min: ~25 min for Windows auto-install, ~5 min for OEM setup + deployer boot. Monitor via `/tmp/wootc-e2e-qga*.log`.

## Secure Boot chainloading

### Problem

`wubildr.efi` (our custom GRUB) is **unsigned**. UEFI Secure Boot rejects it:
```
BdsDxe: skipped Boot0004 ... wubildr.efi: Access Denied
```

### Solution: shim + Fedora signed GRUB

Chain: **UEFI → Windows Boot Manager → bootsequence → shimx64.efi (MS-signed) → grubx64.efi (Fedora-signed) → grub.cfg → deployer**

### Deployment steps (via QGA, on live Windows VM)

1. Extract signed binaries from Fedora 44 container:
   ```bash
   CID=$(podman run -d quay.io/fedora/fedora:44 bash -c "dnf install -y -q shim-x64 grub2-efi-x64 && cp /boot/efi/EFI/fedora/{shim,grub,mm}x64.efi /tmp/ && echo DONE")
   podman wait $CID
   podman cp $CID:/tmp/shimx64.efi .
   podman cp $CID:/tmp/grubx64.efi .
   podman cp $CID:/tmp/mmx64.efi .
   ```

2. Extract GRUB modules (for NTFS support):
   ```bash
   podman exec grub-module-container dnf install -y grub2-efi-x64-modules
   # Copy ntfs.mod, loopback.mod, ntfscomp.mod, ext2.mod out
   ```

3. Copy to Samba share and deploy via QGA:
   ```powershell
   # On Windows VM via QGA guest-exec:
   Copy-Item "\\host.lan\Data\shimx64.efi" "E:\EFI\wootc\shimx64.efi"
   Copy-Item "\\host.lan\Data\grubx64.efi" "E:\EFI\wootc\grubx64.efi"
   Copy-Item "\\host.lan\Data\ntfs.mod" "E:\EFI\wootc\ntfs.mod"
   Copy-Item "\\host.lan\Data\loopback.mod" "E:\EFI\wootc\loopback.mod"
   # Write grub.cfg with insmod ntfs + loopback BEFORE search commands
   # Create new BCD entry pointing to shimx64.efi with one-shot bootsequence
   ```

4. Create snapshot of data.qcow2 before first reboot with shim.

### Critical: GRUB modules on ESP

Fedora's signed `grubx64.efi` does NOT embed ntfs+loopback. Place these
`.mod` files on the FAT32 ESP alongside `grub.cfg`. Without them:
```
error: ../../grub-core/commands/search.c:527:no such device:
error: ../../grub-core/script/lexer.c:352:out of memory.
GRUB version 2.12
Minimal BASH-like line editing is supported.
```

### Snapshot before first deployer boot

```bash
cp storage/data.qcow2 storage/data.qcow2.snap
```

Restore to retry without reinstalling Windows:
```bash
cp storage/data.qcow2.snap storage/data.qcow2
# Then restart with --skip-install --skip-build --keep
```

## QGA control plane

The QEMU Guest Agent replaces WinRM as the E2E control plane. No network, no credentials, no firewall — just a virtio-serial Unix socket at `/run/shm/qga.sock`.

### Primitives

| Primitive | QGA command | Runner helper |
|-----------|------------|---------------|
| Readiness | `guest-ping` | `qga_wait "label" <timeout_sec>` |
| Diagnostics | `guest-info` | `qga_call info` |
| Run command | `guest-exec` + `guest-exec-status` | `qga_powershell "<script>"` |
| Read file | `guest-file-open/read/close` | `qga_read "C:\path"` |
| Reboot wait | `guest-ping` down/up cycle | `qga_wait_reboot "label"` |

### Client

`tests/e2e/qga.py` — 131-line stdlib Python client, copied into the Dockur container. JSON-lines over Unix socket. No pip dependencies.

### Bootstrap

The QGA MSI (`qemu-ga-x86_64.msi`, ~12MB) is cached in `tests/e2e/qga-cache/` (gitignored). It's copied to `C:\OEM\` with the OEM payload, installed silently by the first-logon Scheduled Task (`install.bat`), and started as a SYSTEM service. The runner waits for `guest-ping` before proceeding.

## PowerShell safety rules

Every wootc PowerShell script must pass these rules. Failures here have consumed multiple E2E cycles.

### R1: No trailing backslash in double-quoted strings

```powershell
# BROKEN — PowerShell sees \" as escaped quote, string never terminates
$dir = "C:\OEM\"

# FIXED
$dir = "C:\OEM"
# or use single quotes (literal):
$dir = 'C:\OEM\'
```

The E2E runner has a pre-flight check: `grep -n '\\\\"$' setup-wootc.ps1`.

### R2: No -f format strings or + concatenation inside parenthesized expressions

```powershell
# BROKEN — -f format string: the ) in ({1} GB) closes the outer ( grouping
Write-Host ("  root.disk:   {0} ({1} GB)" -f $diskPath, $DiskSizeGB)
# ALSO BROKEN — + concatenation inside (...) has the same parser issue
Write-Host ("  root.disk:   " + $diskPath + " (" + $DiskSizeGB + " GB)")
# FIXED — variable expansion in double quotes, no operators or grouping needed
Write-Host "  root.disk:   $diskPath ($DiskSizeGB GB)"
```

PowerShell's parser misinterprets the closing parenthesis in strings like
`(nn GB)` as terminating the outer grouped expression. Both `-f` format
strings and `+` concatenation inside `(...)` trigger this. Use plain variable
expansion in double-quoted strings — simplest and most reliable.

### R4: Windows PowerShell 5.1 requires CRLF line endings + UTF-8 BOM

```bash
# ALWAYS convert before staging PowerShell scripts for Windows VMs:
printf '\xEF\xBB\xBF' > "script.ps1.crlf"
sed 's/$/\r/' script.ps1 >> "script.ps1.crlf"
```

PowerShell 5.1's `Get-Content -Raw` and internal script parser both corrupt
UTF-8 files with LF-only line endings. The bytes are misread, causing spurious
parse errors (e.g., "Unexpected token 'GB'" on innocuous variable expansions).
`[System.IO.File]::ReadAllText()` works correctly, proving the file itself is
fine — it's the read path that breaks. CRLF + UTF-8 BOM fixes it.

The E2E runner (`run-e2e.sh`) automatically converts `setup-wootc.ps1` before
copying it to the OEM payload and wootc-files.

### R3: Single-quote here-strings for GRUB config

```powershell
# CORRECT — single quotes, no variable expansion
$grubConfig = @'
if search -s -f -n /wootc/disks/root.disk; then
    ...
fi
'@
```

GRUB config contains `$prefix`, `$root`, `{` etc. Use single-quoted here-strings so PowerShell doesn't try to expand them.

## Kanpur quirks

### PATH for podman-compose

`podman-compose` is installed at `~/.local/bin/podman-compose` but this isn't on the default SSH PATH. Always run with:

```bash
PATH="$HOME/.local/bin:$PATH" bash run-e2e.sh --keep
```

### Root-owned files after Podman runs

Podman Compose creates files in `tests/e2e/` owned by root (or the container UID). Before re-running, fix permissions:

```bash
sudo chown -R james:james ~/wootc/tests/e2e/
```

### Port 3389 cleanup

Stale `rootlessport` processes hold port 3389 across runs. Kill them:

```bash
kill $(pgrep rootlessport) 2>/dev/null
# If QEMU also stale (root-owned from old run):
sudo kill $(pgrep qemu-system) 2>/dev/null
```

### Container name

Always `wootc-e2e-windows`. Stop/rm it before re-running:

```bash
podman stop wootc-e2e-windows && podman rm wootc-e2e-windows
```

## Debug cycle

When a run fails:

1. **Read the log**: `tail -100 /tmp/wootc-e2e-qga*.log`
2. **Check QGA output**: The runner captures OEM logs via `qga_read` in `capture_vm_diagnostics()`
3. **Check the screenshot**: `scp kanpur:/tmp/wootc-e2e-failure.png .`
4. **Live container**: If `--keep` was used, `podman exec -it wootc-e2e-windows bash` and check `/run/shm/qga.sock`
5. **Fix PowerShell**: Apply rules R1-R3, commit, push, re-run
6. **Check for stale state**: Root-owned files, port conflicts, old containers

## Key files

| File | Purpose |
|------|---------|
| `tests/e2e/run-e2e.sh` | Main E2E orchestrator |
| `tests/e2e/qga.py` | QGA JSON-lines client |
| `tests/e2e/compose.yml` | Podman Compose VM definition |
| `tests/e2e/setup-wootc.ps1` | Windows OEM PowerShell payload |
| `tests/e2e/autounattend.xml` | Windows unattended install answer file |
| `tests/e2e/oem/install.bat` | First-logon QGA bootstrap task |
| `tests/e2e/qga-cache/` | Cached QGA MSI (gitignored) |
| `tests/e2e/wootc-files/` | Built deployer artifacts |
| `tests/e2e/storage/` | QCOW2 disk, TPM state, ISO |

## External references

### QGA protocol & downloads
- [QEMU Guest Agent Protocol Reference](https://qemu-project.gitlab.io/qemu/interop/qemu-ga-ref.html) — All QGA commands, arguments, and return types
- [QEMU Guest Agent Overview](https://wiki.qemu.org/Features/GuestAgent) — Protocol, virtio-serial wiring, security model
- [virtio-win Downloads](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/) — Official QGA MSI and virtio driver ISOs

### QGA installation approaches (all equivalent to ours)
- [Schneegans Unattend Generator](https://schneegans.de/windows/unattend-generator/) — Includes QGA install in autounattend.xml FirstLogonCommands
- [Proxmox Windows Guest Best Practices](https://pve.proxmox.com/wiki/Windows_2025_guest_best_practices) — QGA from virtio-win ISO or MSI
- [Proxmox Packer Build (VirtualizationHowto)](https://www.virtualizationhowto.com/2024/11/windows-server-2025-proxmox-packer-build-fully-automated/) — `msiexec /i ... /qn` via FirstLogonCommands
- [OpenShift Windows Golden Image](https://medium.com/@yakovbeder/building-a-windows-server-2025-golden-image-on-openshift-virtualization-7a07a89ee821) — Post-install QGA via pipeline script
- [Automating Windows VM Installation (palant.info)](https://palant.info/2023/02/13/automating-windows-installation-in-a-vm/) — Full unattended setup including QGA

### Container & VM host
- [Dockur Windows](https://github.com/dockur/windows) — The containerized QEMU wrapper used in E2E

## See also

- `HANDOFF.md` — Design rationale for QGA over WinRM
- `CONTEXT.md` — Domain glossary (Phases 1-3, root.disk, wubildr, BCD)
- `docs/adr/0001-phase1-first-architecture.md` — Phase 1 architecture decision

## Deployer-phase debugging (added 2026-07-16)

The deployer initramfs has no console input. Rules learned the hard way:

### Logging & telemetry
- `log()`/`err()` in deploy.sh write through **/dev/kmsg** — stdout of a
  sourced initqueue hook reaches the journal but NOT the serial console.
- Live journal streams to `C:\wootc\logs\live-journal.log` every 15s (with
  sync). Post-mortem after any wedge: read it via `qga read`.
- Heartbeat every 30s on serial: `[wootc] heartbeat phase=… scratch=… mem_avail=…`.
  No heartbeat for 2 min ⇒ wedge, not work.
- qemu-ga runs in the deployer on the same channel as Windows — `qga.py`
  works during deployment (guest-exec df/journalctl, interactive rescue).
- Runner writes `storage/e2e-timeline.log` (timestamped markers per run).

### Initramfs gotchas
- dracut `inst_multiple` fails SILENTLY if ANY entry is missing — one absent
  binary (restorecon) dropped conmon/crun/podman and produced a week of
  `podman … exit status 125`. The Containerfile now asserts critical
  binaries via lsinitrd; keep that list current.
- podman needs conmon+crun for EVERY command including `pull`; without
  policy.json/CA bundle it exits 125 instantly; fisherman's overlay probe
  (`podman info`) also fails without conmon → silent VFS fallback → ENOSPC.
- No `seq` in the initramfs (use `{1..N}`); check every new binary you call.
- fisherman does heavy I/O under `/var/fisherman-tmp` (podman --root, OCI
  cache) and containers/image stages blobs in `/var/tmp` — both must be on
  the ext4 scratch loop, not ramfs.

### Fail-path rules
- The initqueue hook is sourced under `set -e`: `status=0; cmd || status=$?`.
- `reboot -f` = `systemctl reboot -f` = hangs after emergency mode (which
  starts ~45s in via the gpt-auto root timeout). Use `reboot -ff`, sysrq
  fallback; a 45-min watchdog subshell backstops everything.
- Cap `vm.dirty_bytes` (256MB) or the final sync/umount sits in D-state for
  tens of minutes after a multi-GB pull.

### NTFS dirty-bit trap
- Killing QEMU (podman restart/stop) while the deployer has NTFS rw-mounted
  sets the dirty bit. Windows BOOTS FINE with it set and does not clear it;
  every later deployer rw mount fails ("wrong fs type" from ntfs3).
- Recovery: `Repair-Volume -DriveLetter C -OfflineScanAndFix` + reboot
  (autochk), then verify `fsutil dirty query C:` says NOT Dirty.
- Win11 24H2 OOBE auto-enables BitLocker device encryption on TPM+SB
  installs (C: unreadable from Linux). autounattend now sets
  PreventDeviceEncryption; on a live VM: `manage-bde -off C:` and poll.

### Secure Boot chain (working)
BCD one-shot → `\EFI\fedora\shimx64.efi` → signed grubx64 (prefix
`/EFI/fedora` — grub.cfg MUST be there) → deployer kernel from ESP FAT32.
No unsigned modules ever load; `ntfs.mod` is unavailable — Phase-2 boots via
ESP kernel-sync (`EFI/wootc/phase2-*`), never via GRUB-reads-NTFS.

### Fast iteration without rebuilds
Patch initramfs in place on kanpur (no cpio/lsinitrd on host; use bsdtar+zstd):
```bash
# extract once: tail -c +306177 img | zstd -d | bsdtar -xf - -C /tmp/dep-root
# edit files, then:
head -c 306176 img.orig > new.img
(cd /tmp/dep-root && bsdtar --format newc --uid 0 --gid 0 -cf - . | zstd -8 -T0) >> new.img
```
(306176 = end of the early uncompressed cpio segment; recompute with a
zstd-magic scan if the image changes.)

### Milestone + remaining gap (2026-07-16 08:00)
The deployer E2E loop is GREEN end-to-end (Windows → deployer → bootc
install → VERIFICATION_SUMMARY → Windows, clean NTFS). Late-session fixes:
`--network host` on fisherman's podman run (netavark needs nft, absent);
storage redirect only when /var/lib/containers is RAM-backed (otherwise the
OCI-export path lands THREE image copies inside the target → ENOSPC);
qualified `containers-storage:[overlay@ROOT+RUNROOT]ref` for skopeo export
from a redirected root; root.disk ≥25G for yellowfin:gnome; scratch persists
between runs as a containers-storage cache (retries skip the pull).

Remaining: deploy.sh verification is ostree-unaware — it looks for
/etc/os-release at the fs top level, but ostree roots keep it under
/ostree/deploy/default/deploy/<hash>/etc, so dracut inject + BLS args + ESP
kernel-sync silently skip (0.5s "verification"). Detect /ostree and operate
on the deployment path; run ESP sync unconditionally.

## SSH-enabled E2E container (added 2026-07-16)

`tests/e2e/build-ssh-image.sh` bakes sshd into the Dockur windows image
(key-only, dedicated `~/.ssh/wootc_e2e_ed25519` keypair) so debug sessions
can `ssh -i ~/.ssh/wootc_e2e_ed25519 -p 2222 root@localhost` (on kanpur)
straight into the container — no more nested `ssh kanpur → podman exec →
python heredoc` quoting, which caused several real bugs this session
(grub.cfg construction via PowerShell-in-podman-exec-in-ssh, qga_exec
escaping). `compose.yml` uses `localhost/wootc-e2e-windows-ssh:latest` by
default; rebuild the layer any time the base Dockur image updates.
