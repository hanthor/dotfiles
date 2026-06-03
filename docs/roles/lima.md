# lima

**Tags:** `services`, `lima`  
**Secrets needed:** No  
**Runs on:** Desktops and bihar

Manages Lima VM instances for local development environments.

## What It Does

1. Creates Lima data directories
2. Deploys Lima instance configurations
3. Manages VM startup

## Notes

- Lima provides lightweight VMs using QEMU with automatic file sharing
- Skip with `skip_lima: true`
- Requires KVM to be available on the host
