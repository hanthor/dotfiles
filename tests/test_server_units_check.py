"""Read-only checks for the native server/service units, using a private fake system."""
import json
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


UNITS = ("server-hardening", "retired-services", "proxy", "tailscale-cert", "bst-dashboard", "kirocrew")


@pytest.fixture
def check_system(stub_env, tmp_path):
    bindir, env = stub_env
    root = tmp_path / "system"
    repo = tmp_path / "repo"
    units = repo / "units"
    units.mkdir(parents=True)
    (repo / "host_vars").mkdir()
    (repo / "group_vars").mkdir()
    (repo / "host_vars/workstation.yml").write_text("kirocrew_enabled: true\n")
    (repo / "group_vars/all.yml").write_text("tailscale_domain: example.ts.net\n")
    (repo / "inventory.yml").write_text(json.dumps({"all": {"children": {
        "server": {"hosts": {"workstation": {}}}, "vps": {"hosts": {}}
    }}}))
    for name in ("lib.sh", "osquery_native_inventory.py", "server-hardening-file.py",
                 "service-templates.py", "kirocrew-sockets.py", "retired-services", "proxy",
                 "tailscale-cert", "bst-dashboard"):
        (units / name).symlink_to(REPO / "units" / name)
    for name in UNITS:
        text = (REPO / "units" / f"{name}.sh").read_text()
        for path in ("/etc", "/var/home/james/dev", "/run/systemd/system",
                     "/usr/lib/systemd/systemd-timesyncd", "/swapfile", "/var/run/reboot-required"):
            text = text.replace(path, str(root / path.lstrip("/")))
        (units / f"{name}.sh").write_text(text)
    for directory in ("etc/systemd", "etc/ssh", "run/systemd/system", "var/home/james/dev/dakota",
                      "etc/kirocrew", "etc/systemd/system", "usr/lib/systemd"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "etc/systemd/journald.conf").write_text("#SystemMaxUse=1G\n")
    (root / "etc/ssh/sshd_config").write_text("#MaxStartups 10:30:100\n")
    (root / "etc/fstab").write_text("/dev/root / ext4 defaults 0 1\n")
    (root / "usr/lib/systemd/systemd-timesyncd").touch()
    (root / "etc/systemd/system/kirocrew.service").touch()
    (root / "etc/kirocrew/kirocrew.env").write_text("DO_NOT_PRINT=this-is-a-secret\n")
    (root / "etc/kirocrew/kirocrew.env").chmod(0o600)
    home = Path(env["HOME"])
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/kirocrew").touch()
    old = home / ".config/containers/systemd/grafana.container"
    old.parent.mkdir(parents=True)
    old.write_text("retired\n")
    env.update(DOTFILES_DIR=str(repo), DOTFILES_MACHINE="workstation", UNITS_CHECK="1",
               CALLS=str(tmp_path / "calls"))
    write_stub(bindir, "sudo", '[ "$1" = -n ] && shift\nexec "$@"\n')
    write_stub(bindir, "yq", '''
case "$*" in
  *retired_services_system_units*) ;;
  *retired_services_user_units*) echo grafana.container ;;
  *children.vps.hosts*) echo false ;;
  *web_services*) echo '[]' ;;
  *tailscale_domain*) echo example.ts.net ;;
  *) exit 2 ;;
esac
''')
    write_stub(bindir, "systemctl", '''
echo "systemctl $*" >> "$CALLS"
[[ "$*" == *show* ]] || exit 99
[ "${FAIL_SYSTEMCTL:-0}" != 1 ] || exit 1
if [[ "$*" == *--value* ]]; then echo loaded; else
  printf 'LoadState=loaded\\nActiveState=inactive\\nUnitFileState=disabled\\n'
fi
''')
    write_stub(bindir, "tailscale", '''
echo "tailscale $*" >> "$CALLS"
[ "$1 $2" = "serve status" ] || exit 99
''')
    write_stub(bindir, "loginctl", 'echo "loginctl $*" >> "$CALLS"\n[ "$1" = show-user ] || exit 99\necho no\n')
    write_stub(bindir, "journalctl", '[ "$1" = --disk-usage ] || exit 99\necho 1G\n')
    write_stub(bindir, "findmnt", '[ "${FAIL_FINDMNT:-0}" != 1 ] || exit 1\nprintf "%s\\n" "${ROOT_OPTIONS:-rw,relatime}"\n')
    write_stub(bindir, "swapon", '[ "$1" = --show=NAME ] || exit 99\n[ "${FAIL_SWAPON:-0}" != 1 ] || exit 1\nprintf "%s\\n" "${ACTIVE_SWAP:-}"\n')
    write_stub(bindir, "ufw", '[ "$1" = status ] || exit 99\necho "Status: inactive"\n')
    write_stub(bindir, "pro", '[ "$1" = status ] || exit 99\necho \'{"livepatch": "enabled"}\'\n')
    write_stub(bindir, "ss", 'printf "%s\\n" "${SOCKETS:-}"\n')
    for command in ("dd", "mkswap", "install", "chown", "chmod"):
        write_stub(bindir, command, 'echo "FORBIDDEN $0 $*" >> "$CALLS"\nexit 99\n')
    return repo, root, env, old


def run_check(check_system, name, **extra):
    repo, _, env, _ = check_system
    return subprocess.run(["bash", str(repo / "units" / f"{name}.sh")],
                          env={**env, **extra}, capture_output=True, text=True)


def prepare_hardening_commands(check_system):
    _, _, env, _ = check_system
    bindir = Path(env["PATH"].split(":", 1)[0])
    write_stub(bindir, "systemctl", '''
echo "systemctl $*" >> "$CALLS"
if [[ "$*" == *show* ]]; then
  printf 'LoadState=loaded\\nActiveState=inactive\\nUnitFileState=disabled\\n'
elif [ "$1" = is-active ]; then
  exit 1
fi
''')
    write_stub(bindir, "journalctl", 'echo "journalctl $*" >> "$CALLS"\n')
    write_stub(bindir, "swapon", '''
echo "swapon $*" >> "$CALLS"
if [ "$1" = --show=NAME ]; then
  [ "${FAIL_SWAPON:-0}" != 1 ] || exit 1
  printf "%s\\n" "${ACTIVE_SWAP:-}"
fi
''')
    write_stub(bindir, "dd", '''
echo "dd $*" >> "$CALLS"
for arg in "$@"; do case "$arg" in of=*) : > "${arg#of=}" ;; esac; done
''')
    for command in ("chown", "chmod", "mkswap"):
        write_stub(bindir, command, f'echo "{command} $*" >> "$CALLS"\n')


@pytest.mark.parametrize("check", [True, False])
def test_missing_journald_dropin_directory(check_system, check):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    (root / "etc/systemd/journald.conf").unlink()
    directory = root / "etc/systemd/journald.conf.d"
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0")
    assert result.returncode == 0, (result.stdout, result.stderr)
    calls = Path(env["CALLS"]).read_text().splitlines()
    if check:
        assert "would update journald limit" in result.stdout
        assert not directory.exists()
        assert "systemctl restart systemd-journald" not in calls
    else:
        assert (directory / "90-dotfiles-server-hardening.conf").read_text() == "[Journal]\nSystemMaxUse=500M\n"
        assert calls.count("systemctl restart systemd-journald") == 1


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("existing", ["absent", "current", "outdated"])
def test_missing_journald_main_uses_preserving_dropin(check_system, check, existing):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    (root / "etc/systemd/journald.conf").unlink()
    vendor = root / "usr/lib/systemd/journald.conf"
    vendor.write_text("[Journal]\nSystemMaxUse=2G\n")
    directory = root / "etc/systemd/journald.conf.d"
    directory.mkdir()
    other = directory / "20-other.conf"
    other.write_text("[Journal]\nStorage=persistent\n")
    managed = directory / "90-dotfiles-server-hardening.conf"
    if existing != "absent":
        managed.write_text("[Journal]\n# keep this setting\nStorage=auto\nSystemMaxUse=" +
                           ("500M\n" if existing == "current" else "1G\n"))
        managed.chmod(0o640)
    before = managed.read_bytes() if managed.exists() else None
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0")
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert vendor.read_text() == "[Journal]\nSystemMaxUse=2G\n"
    assert other.read_text() == "[Journal]\nStorage=persistent\n"
    assert not (root / "etc/systemd/journald.conf").exists()
    calls = Path(env["CALLS"]).read_text().splitlines()
    restarts = [line for line in calls if line == "systemctl restart systemd-journald"]
    if check:
        assert ("ok    journald limit" if existing == "current" else "would update journald limit") in result.stdout
        assert (managed.read_bytes() if managed.exists() else None) == before
        assert not restarts
    else:
        assert managed.read_text() == ("[Journal]\nSystemMaxUse=500M\n" if existing == "absent" else
                                       "[Journal]\n# keep this setting\nStorage=auto\nSystemMaxUse=500M\n")
        assert managed.stat().st_mode & 0o777 == (0o644 if existing == "absent" else 0o640)
        assert len(restarts) == (0 if existing == "current" else 1)
        result = run_check(check_system, "server-hardening", UNITS_CHECK="0",
                           ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0")
        assert result.returncode == 0, (result.stdout, result.stderr)
        calls = Path(env["CALLS"]).read_text().splitlines()
        assert len([line for line in calls if line == "systemctl restart systemd-journald"]) == len(restarts)


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("invalid", ["missing_section", "wrong_section", "limit_before_section", "directory", "symlink"])
def test_invalid_journald_dropin_fails_without_stopping_hardening(check_system, check, invalid):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    (root / "etc/systemd/journald.conf").unlink()
    directory = root / "etc/systemd/journald.conf.d"
    if invalid == "directory":
        directory.write_text("not a directory\n")
        original = directory.read_bytes()
    else:
        directory.mkdir()
        managed = directory / "90-dotfiles-server-hardening.conf"
        if invalid == "symlink":
            vendor = root / "usr/lib/systemd/journald.conf"
            vendor.write_text("[Journal]\nSystemMaxUse=1G\n")
            managed.symlink_to(vendor)
        else:
            content = {"missing_section": "SystemMaxUse=1G\n", "wrong_section": "[Other]\nSystemMaxUse=1G\n",
                       "limit_before_section": "SystemMaxUse=1G\n[Journal]\n"}[invalid]
            managed.write_text(content)
        original = managed.read_bytes()
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0")
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "FAIL" in result.stdout and "journald limit" in result.stdout
    assert (directory if invalid == "directory" else managed).read_bytes() == original
    if invalid == "symlink":
        assert managed.is_symlink() and vendor.read_bytes() == original
    assert "systemctl restart systemd-journald" not in Path(env["CALLS"]).read_text().splitlines()
    if check:
        assert "would update SSH limit MaxSessions" in result.stdout
    else:
        assert "MaxSessions 10" in (root / "etc/ssh/sshd_config").read_text()


def test_existing_journald_main_remains_the_managed_file(check_system):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    main = root / "etc/systemd/journald.conf"
    directory = root / "etc/systemd/journald.conf.d"
    directory.mkdir()
    other = directory / "20-other.conf"
    other.write_text("[Journal]\nStorage=persistent\n")
    for _ in range(2):
        result = run_check(check_system, "server-hardening", UNITS_CHECK="0",
                           ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0")
        assert result.returncode == 0, (result.stdout, result.stderr)
    assert main.read_text() == "SystemMaxUse=500M\n"
    assert other.read_text() == "[Journal]\nStorage=persistent\n"
    assert not (directory / "90-dotfiles-server-hardening.conf").exists()
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert calls.count("systemctl restart systemd-journald") == 1


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("existing_swapfile", [True, False])
@pytest.mark.parametrize("active", [True, False])
def test_readonly_root_preserves_swap_and_continues_hardening(check_system, check, existing_swapfile, active):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    swapfile = root / "swapfile"
    if existing_swapfile:
        swapfile.write_text("existing swapfile\n")
        swapfile.chmod(0o640)
    fstab = root / "etc/fstab"
    if existing_swapfile:
        fstab.write_text(fstab.read_text() + "/swapfile none swap sw 0 0\n")
    original_fstab = fstab.read_bytes()
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="ro,relatime", ACTIVE_SWAP="/dev/zram0" if active else "  ")
    assert result.returncode == (0 if active else 1), (result.stdout, result.stderr)
    assert ("active swap preserved on read-only root" if active else
            "FAIL  active swap required on read-only root") in result.stdout
    assert fstab.read_bytes() == original_fstab
    assert swapfile.exists() == existing_swapfile
    if existing_swapfile:
        assert swapfile.read_text() == "existing swapfile\n"
        assert swapfile.stat().st_mode & 0o777 == 0o640
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert [line for line in calls if line.startswith("swapon ")] == ["swapon --show=NAME --noheadings"]
    assert not any(line.startswith(("dd ", "chown ", "chmod ", "mkswap ")) for line in calls)
    if check:
        assert "would update SSH limit MaxSessions" in result.stdout
    else:
        assert "MaxSessions 10" in (root / "etc/ssh/sshd_config").read_text()


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("failure", ["swap", "mount", "unknown_mount"])
def test_swap_inspection_failures_are_reported_without_blocking_hardening(check_system, check, failure):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    extra = {"ROOT_OPTIONS": "ro,relatime"}
    if failure == "swap":
        extra["FAIL_SWAPON"] = "1"
        expected = "FAIL  inspect active swap on read-only root"
    else:
        extra.update({"FAIL_FINDMNT": "1"} if failure == "mount" else {"ROOT_OPTIONS": "noexec"})
        expected = "FAIL  inspect root mount options"
    fstab = root / "etc/fstab"
    original_fstab = fstab.read_bytes()
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0", **extra)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert expected in result.stdout
    assert fstab.read_bytes() == original_fstab
    assert not (root / "swapfile").exists()
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert not any(line.startswith(("dd ", "chown ", "chmod ", "mkswap ")) for line in calls)
    if check:
        assert "would update SSH limit MaxSessions" in result.stdout
    else:
        assert "MaxSessions 10" in (root / "etc/ssh/sshd_config").read_text()


@pytest.mark.parametrize("check", [True, False])
def test_writable_root_still_manages_swapfile(check_system, check):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="rw,relatime", ACTIVE_SWAP="/dev/zram0")
    assert result.returncode == 0, (result.stdout, result.stderr)
    swapfile = root / "swapfile"
    fstab = (root / "etc/fstab").read_text()
    calls = Path(env["CALLS"]).read_text().splitlines()
    if check:
        assert "would create 2 GiB" in result.stdout
        assert "would format and enable" in result.stdout
        assert "would update swap fstab" in result.stdout
        assert not swapfile.exists() and str(swapfile) not in fstab
    else:
        assert swapfile.exists()
        assert f"{swapfile} none swap sw 0 0" in fstab
        assert any(line.startswith("dd ") for line in calls)
        assert f"chown root:root {swapfile}" in calls
        assert f"chmod 0600 {swapfile}" in calls
        assert f"mkswap {swapfile}" in calls
        assert f"swapon {swapfile}" in calls


@pytest.mark.parametrize("check", [True, False])
def test_writable_root_preserves_active_swapfile(check_system, check):
    _, root, env, _ = check_system
    prepare_hardening_commands(check_system)
    swapfile = root / "swapfile"
    swapfile.write_text("existing swapfile\n")
    result = run_check(check_system, "server-hardening", UNITS_CHECK="1" if check else "0",
                       ROOT_OPTIONS="rw,relatime", ACTIVE_SWAP=str(swapfile))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert swapfile.read_text() == "existing swapfile\n"
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert not any(line.startswith(("dd ", "mkswap ")) for line in calls)
    assert [line for line in calls if line.startswith("swapon ")] == ["swapon --show=NAME --noheadings"]
    if check:
        assert "ok    swap enabled" in result.stdout
        assert str(swapfile) not in (root / "etc/fstab").read_text()
    else:
        assert f"chown root:root {swapfile}" in calls
        assert f"chmod 0600 {swapfile}" in calls
        assert f"{swapfile} none swap sw 0 0" in (root / "etc/fstab").read_text()


@pytest.mark.parametrize("unit,expected", [
    ("server-hardening", "would update journald limit"),
    ("retired-services", "would stop grafana.service"),
    ("proxy", "would deploy"),
    ("tailscale-cert", "would provision Tailscale certificate"),
    ("bst-dashboard", "would deploy dashboard user service"),
    ("kirocrew", "would start kirocrew"),
])
def test_check_reports_drift_without_mutation(check_system, unit, expected):
    _, root, env, old = check_system
    original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = run_check(check_system, unit)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert expected in result.stdout
    assert "this-is-a-secret" not in result.stdout + result.stderr
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
    assert old.read_text() == "retired\n"
    calls = Path(env["CALLS"])
    if calls.exists():
        for call in calls.read_text().splitlines():
            assert (call.startswith("systemctl ") and "show" in call or
                    call == "tailscale serve status" or call.startswith("loginctl show-user "))


@pytest.mark.parametrize("unit", UNITS)
def test_check_fails_when_systemd_inspection_fails(check_system, unit):
    result = run_check(check_system, unit, FAIL_SYSTEMCTL="1")
    assert result.returncode != 0
    assert "FAIL" in result.stdout


@pytest.mark.parametrize("unit", UNITS)
def test_retired_vps_remain_untouched_in_check(check_system, unit):
    result = run_check(check_system, unit, DOTFILES_MACHINE="matrix")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not Path(check_system[2]["CALLS"]).exists()


def test_kirocrew_rejects_non_loopback_listener(check_system):
    line = 'LISTEN 0 128 0.0.0.0:8000 0.0.0.0:* users:(("kirocrew",pid=7,fd=5))'
    result = run_check(check_system, "kirocrew", SOCKETS=line)
    assert result.returncode != 0
    assert "listening beyond localhost" in result.stderr


def test_hardening_line_check_never_writes(tmp_path):
    config = tmp_path / "sshd_config"
    config.write_text("#MaxSessions 20\n")
    command = ["python3", str(REPO / "units/server-hardening-file.py"), "--check", str(config),
               "^#?MaxSessions", "MaxSessions 10"]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 10
    assert config.read_text() == "#MaxSessions 20\n"
