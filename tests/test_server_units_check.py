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
    write_stub(bindir, "swapon", '[ "$1" = --show=NAME ] || exit 99\n')
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
