"""Read-only checks for the native sudo and SSH daemon units."""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import write_stub
from test_platform_native_units import platform_env  # noqa: F401


def run_check(fixture, name, **updates):
    root, _, _, env, _ = fixture
    return subprocess.run(
        ["bash", str(root / "units" / f"{name}.sh")],
        env={**env, "UNITS_CHECK": "1", **updates}, text=True, capture_output=True,
    )


def snapshot(path):
    return {
        str(p.relative_to(path)): (
            "link", os.readlink(p)
        ) if p.is_symlink() else (
            "file", p.read_bytes(), p.stat().st_mode
        ) if p.is_file() else ("dir", p.stat().st_mode)
        for p in path.rglob("*")
    }


def test_sudo_check_reports_install_and_legacy_removal_without_writes(platform_env):
    _, system, _, env, log = platform_env
    directory = system / "etc/sudoers.d"
    (directory / "james").write_text("old policy\n")
    (directory / "zz-james").symlink_to("missing")
    before = snapshot(system)
    temp_before = set(Path(env["TMPDIR"]).iterdir())
    result = run_check(platform_env, "sudo")
    assert result.returncode == 0, result.stderr
    assert "would validate sudo policy" in result.stdout
    assert "would install sudo policy" in result.stdout
    assert "would remove legacy sudo policy" in result.stdout
    assert snapshot(system) == before
    assert set(Path(env["TMPDIR"]).iterdir()) == temp_before
    assert not log.exists()


def test_sudo_check_detects_clean_policy_and_inspection_failures(platform_env):
    _, system, bindir, _, _ = platform_env
    dest = system / "etc/sudoers.d/zz-james"
    dest.write_text("james ALL=(ALL) NOPASSWD:ALL\n")
    dest.chmod(0o440)
    result = run_check(platform_env, "sudo")
    assert result.returncode == 0 and "ok    sudo policy" in result.stdout
    assert "would install" not in result.stdout
    write_stub(bindir, "sudo", 'echo "inspection denied" >&2\nexit 1\n')
    result = run_check(platform_env, "sudo")
    assert result.returncode != 0 and "inspect sudo policy" in result.stdout
    assert "would install" not in result.stdout


def test_sudo_check_rejects_unreadable_comparison(platform_env):
    _, system, bindir, _, _ = platform_env
    dest = system / "etc/sudoers.d/zz-james"
    dest.write_text("policy\n")
    write_stub(bindir, "cmp", 'exit 2\n')
    result = run_check(platform_env, "sudo")
    assert result.returncode != 0
    assert "Cannot read sudo policy" in result.stderr


def test_sudo_apply_uses_privileged_inspection_and_preserves_old_rules_on_error(platform_env):
    root, system, bindir, env, log = platform_env
    directory = system / "etc/sudoers.d"
    dest = directory / "zz-james"
    dest.write_text("james ALL=(ALL) NOPASSWD:ALL\n")
    dest.chmod(0o440)
    write_stub(bindir, "sudo", '''\
[ "$1" = -n ] || exit 1
shift
case "$1" in
  /usr/sbin/visudo) exit 0 ;;
  bash) shift; SUDO_INSPECT=1 exec bash "$@" ;;
  *) echo "$*" >> "$LOG"; exec "$@" ;;
esac
''')
    write_stub(bindir, "stat", '''\
[ "${SUDO_INSPECT:-0}" = 1 ] || exit 2
mode=$(/usr/bin/stat -c %a "$3") || exit 1
echo "$mode:0:0"
''')
    write_stub(bindir, "cmp", '''\
[ "${SUDO_INSPECT:-0}" = 1 ] || exit 2
[ "${CMP_ERROR:-0}" = 0 ] || exit 2
exec /usr/bin/cmp "$@"
''')
    command = ["bash", str(root / "units/sudo.sh")]
    clean = subprocess.run(command, env=env, text=True, capture_output=True)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert not any(line.startswith(("install ", "mv ")) for line in log.read_text().splitlines())
    old = directory / "99-james"
    old.write_text("keep this rule\n")
    failed = subprocess.run(command, env={**env, "CMP_ERROR": "1"}, text=True, capture_output=True)
    assert failed.returncode != 0 and "Cannot read sudo policy" in failed.stderr
    assert old.read_text() == "keep this rule\n" and dest.read_text() == "james ALL=(ALL) NOPASSWD:ALL\n"


@pytest.mark.parametrize("name", ["sudo", "sshd"])
@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("bad_file", ["directory", "dangling-link"])
def test_access_units_fail_closed_on_unreadable_host_configuration(platform_env, name, check, bad_file):
    root, system, _, env, log = platform_env
    host_file = root / "host_vars/laptop.yml"
    if bad_file == "directory":
        host_file.mkdir()
    else:
        host_file.symlink_to("missing-host-vars")
    before = snapshot(system)
    result = subprocess.run(["bash", str(root / "units" / f"{name}.sh")],
                            env={**env, "UNITS_CHECK": "1" if check else "0"},
                            text=True, capture_output=True)
    assert result.returncode != 0 and f"read {name} host configuration" in result.stdout
    assert snapshot(system) == before and not log.exists()


def test_sshd_check_reports_both_dropins_and_reload_without_writes(platform_env):
    root, system, _, env, log = platform_env
    (root / "host_vars/laptop.yml").write_text("sshd_harden: true\n")
    directory = system / "etc/ssh/sshd_config.d"
    (directory / "99-bw-env.conf").write_text("obsolete\n")
    before = snapshot(system)
    temp_before = set(Path(env["TMPDIR"]).iterdir())
    result = run_check(platform_env, "sshd")
    assert result.returncode == 0, result.stderr
    assert "would install sshd drop-in" in result.stdout
    assert "99-bw-env.conf" in result.stdout and "10-hardening.conf" in result.stdout
    assert "would validate sshd drop-in" in result.stdout
    assert "would reload sshd" in result.stdout
    assert snapshot(system) == before
    assert set(Path(env["TMPDIR"]).iterdir()) == temp_before
    assert not log.exists()


def test_sshd_check_clean_and_inspection_error(platform_env):
    root, system, bindir, _, log = platform_env
    directory = system / "etc/ssh/sshd_config.d"
    dest = directory / "99-bw-env.conf"
    dest.write_text("AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET\n")
    dest.chmod(0o644)
    clean = run_check(platform_env, "sshd")
    assert clean.returncode == 0 and "ok    sshd drop-in" in clean.stdout
    assert "would install" not in clean.stdout and "would reload" not in clean.stdout
    dest.write_text("out of date\n")
    write_stub(bindir, "cmp", 'exit 2\n')
    failed = run_check(platform_env, "sshd")
    assert failed.returncode != 0 and "Cannot read sshd drop-in" in failed.stderr


def test_sshd_check_absent_dropin_directory_matches_apply_skip(platform_env):
    _, system, _, _, _ = platform_env
    (system / "etc/ssh/sshd_config.d").rmdir()
    result = run_check(platform_env, "sshd")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
