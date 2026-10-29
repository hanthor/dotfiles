"""Focused parity and safety regressions for the server application units."""
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from test_server_units_check import check_system, prepare_hardening_commands, run_check


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("signature,valid", [("swap", True), ("ext4", False), ("", False)])
def test_existing_inactive_swap_is_never_reformatted(check_system, check, signature, valid):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    bindir = Path(env["PATH"].split(":", 1)[0])
    write_stub(bindir, "blkid", 'printf "%s\\n" "$SWAP_SIGNATURE"\n[ -n "$SWAP_SIGNATURE" ]\n')
    swap = root / "swapfile"
    swap.write_text("existing data")
    fstab = root / "etc/fstab"
    before = fstab.read_bytes()
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="rw,relatime", ACTIVE_SWAP="/dev/zram0", SWAP_SIGNATURE=signature)
    assert result.returncode == (0 if valid else 1), (result.stdout, result.stderr)
    assert swap.read_text() == "existing data"
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert not any(line.startswith(("dd ", "mkswap ")) for line in calls)
    if not valid:
        assert "refusing to format" in result.stdout
        assert fstab.read_bytes() == before
        assert not any(line.startswith(("chown ", "chmod ")) for line in calls)
    elif check:
        assert "would enable existing swapfile" in result.stdout
        assert fstab.read_bytes() == before
    else:
        assert f"swapon {swap}" in calls
        assert f"{swap} none swap sw 0 0" in fstab.read_text()


@pytest.mark.parametrize("check", [True, False])
def test_symlink_swap_is_rejected_without_touching_target(check_system, check):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    target = root / "other-data"
    target.write_text("keep")
    (root / "swapfile").symlink_to(target)
    fstab = root / "etc/fstab"
    before = fstab.read_bytes()
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="rw,relatime", ACTIVE_SWAP="/dev/zram0")
    assert result.returncode == 1
    assert "must be a regular file, not a symlink" in result.stdout
    assert target.read_text() == "keep" and fstab.read_bytes() == before
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert not any(line.startswith(("dd ", "chown ", "chmod ", "mkswap ")) for line in calls)


def test_privileged_firewall_and_pro_status_checks(check_system):
    _, _, env, _ = check_system
    prepare_hardening_commands(check_system)
    bindir = Path(env["PATH"].split(":", 1)[0])
    write_stub(bindir, "id", 'if [ "$1" = -u ]; then echo 1000; else exec /usr/bin/id "$@"; fi\n')
    write_stub(bindir, "sudo", '[ "$1" = -n ] && shift\nexport FROM_SUDO=1\nexec "$@"\n')
    write_stub(bindir, "ufw", '''
echo "ufw $* ${FROM_SUDO:-no}" >> "$CALLS"
[ "${FROM_SUDO:-}" = 1 ] || exit 1
if [ "$1" = status ]; then echo 'Status: active'; fi
''')
    write_stub(bindir, "pro", '''
echo "pro $* ${FROM_SUDO:-no}" >> "$CALLS"
[ "${FROM_SUDO:-}" = 1 ] || exit 1
if [ "$1" = status ]; then echo '{"livepatch":"disabled"}'; fi
''')
    result = run_check(check_system, "server-hardening", UNITS_CHECK="0", ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0")
    assert result.returncode == 0, (result.stdout, result.stderr)
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert "ufw status 1" in calls and "ufw logging on 1" in calls
    assert "pro status --format json 1" in calls and "pro enable livepatch 1" in calls


def test_ssh_limits_precede_includes_and_match_without_losing_configuration(tmp_path):
    config = tmp_path / "sshd_config"
    original = "Include /etc/ssh/sshd_config.d/*.conf\nMaxSessions 25\nMatch User deploy\n    MaxSessions 2\n"
    config.write_text(original)
    script = str(REPO / "units/server-hardening-file.py")
    check = subprocess.run([sys.executable, script, "--check", "--ssh", str(config)], capture_output=True, text=True)
    assert check.returncode == 10 and config.read_text() == original
    result = subprocess.run([sys.executable, script, "--ssh", str(config)], capture_output=True, text=True)
    assert result.returncode == 10
    updated = config.read_text()
    assert updated.startswith("# BEGIN dotfiles server-hardening\nMaxStartups 3:50:10\nMaxSessions 10\nClientAliveCountMax 3\n")
    assert updated.endswith(original)
    assert subprocess.run([sys.executable, script, "--ssh", str(config)], capture_output=True).returncode == 0


def test_malformed_ssh_managed_block_is_not_replaced(tmp_path):
    config = tmp_path / "sshd_config"
    original = "# BEGIN dotfiles server-hardening\nMaxSessions 30\n"
    config.write_text(original)
    result = subprocess.run([sys.executable, str(REPO / "units/server-hardening-file.py"), "--ssh", str(config)], capture_output=True)
    assert result.returncode != 0 and config.read_text() == original


def test_dashboard_changed_unit_restarts_only_after_reload(check_system):
    _, _, env, _ = check_system
    prepare_hardening_commands(check_system)
    bindir = Path(env["PATH"].split(":", 1)[0])
    write_stub(bindir, "install", 'exec /usr/bin/install "$@"\n')
    write_stub(bindir, "loginctl", 'echo "loginctl $*" >> "$CALLS"\nif [ "$1" = show-user ]; then echo no; fi\n')
    service = Path(env["HOME"]) / ".config/systemd/user/bst-dashboard.service"
    service.parent.mkdir(parents=True, exist_ok=True)
    service.write_text("[Service]\nExecStart=/old/dashboard\n")
    check = run_check(check_system, "bst-dashboard", UNITS_CHECK="1")
    assert check.returncode == 0 and "start or restart dashboard" in check.stdout
    assert service.read_text() == "[Service]\nExecStart=/old/dashboard\n"
    Path(env["CALLS"]).unlink()
    result = run_check(check_system, "bst-dashboard", UNITS_CHECK="0")
    assert result.returncode == 0, (result.stdout, result.stderr)
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert calls.index("systemctl --user daemon-reload") < calls.index("systemctl --user restart bst-dashboard.service")
    assert "--target oci/dakota.bst" in service.read_text()
    Path(env["CALLS"]).unlink()
    result = run_check(check_system, "bst-dashboard", UNITS_CHECK="0")
    assert result.returncode == 0
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert "systemctl --user restart bst-dashboard.service" not in calls
    assert "systemctl --user daemon-reload" not in calls

def test_dashboard_enable_failure_does_not_restart(check_system):
    _, _, env, _ = check_system
    prepare_hardening_commands(check_system)
    bindir = Path(env["PATH"].split(":", 1)[0])
    write_stub(bindir, "install", 'exec /usr/bin/install "$@"\n')
    write_stub(bindir, "loginctl", 'exit 0\n')
    write_stub(bindir, "systemctl", '''
echo "systemctl $*" >> "$CALLS"
if [ "$1 $2" = "--user enable" ]; then exit 1; fi
''')
    result = run_check(check_system, "bst-dashboard", UNITS_CHECK="0")
    assert result.returncode != 0 and "FAIL  enable dashboard" in result.stdout
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert "systemctl --user restart bst-dashboard.service" not in calls
