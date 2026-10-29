import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


spec = importlib.util.spec_from_file_location("hardening_file", REPO / "units/server-hardening-file.py")
hardening = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardening)


def test_hardening_replaces_last_match_and_preserves_mode_and_symlink(tmp_path):
    real = tmp_path / "sshd_config"
    link = tmp_path / "sshd_link"
    real.write_text("#MaxStartups 10:30:100\nOtherSetting yes\nMaxStartups 8:30:60\n")
    real.chmod(0o640)
    link.symlink_to(real)
    assert hardening.update(link, r"^#?MaxStartups", "MaxStartups 3:50:10")
    assert real.read_text() == "#MaxStartups 10:30:100\nOtherSetting yes\nMaxStartups 3:50:10\n"
    assert link.is_symlink() and real.stat().st_mode & 0o777 == 0o640
    assert not hardening.update(link, r"^#?MaxStartups", "MaxStartups 3:50:10")


def test_fstab_entry_is_added_once_without_clobbering_existing_lines(tmp_path):
    fstab = tmp_path / "fstab"
    fstab.write_text("/dev/root / ext4 defaults 0 1")
    rule = "/swapfile none swap sw 0 0"
    assert hardening.update(fstab, "^" + rule + "$", rule)
    assert fstab.read_text() == "/dev/root / ext4 defaults 0 1\n" + rule + "\n"
    assert not hardening.update(fstab, "^" + rule + "$", rule)


def run_retired_function(env, scope, path):
    return subprocess.run(["bash", "-c", 'source "$1"; retired_stop "$2" "$3"', "bash",
                           str(REPO / "units/retired-services.sh"), scope, path],
                          env=env, text=True, capture_output=True)


@pytest.mark.parametrize("filename,unit", [("old.container", "old.service"),
                                           ("old.volume", "old-volume.service"),
                                           ("old.network", "old-network.service")])
def test_quadlet_stops_generated_service_without_disabling(stub_env, tmp_path, filename, unit):
    bindir, env = stub_env
    calls = tmp_path / "calls"
    env["CALLS"] = str(calls)
    write_stub(bindir, "systemctl", 'printf "%s\\n" "$*" >> "$CALLS"\nif [[ "$*" == *show* ]]; then echo loaded; fi\n')
    result = run_retired_function(env, "user", filename)
    assert result.returncode == 0
    lines = calls.read_text().splitlines()
    assert lines[-1] == f"--user stop {unit}"
    assert not any("disable" in line for line in lines)


def test_missing_quadlet_is_not_stopped_and_unrelated_services_untouched(stub_env, tmp_path):
    bindir, env = stub_env
    calls = tmp_path / "calls"
    env["CALLS"] = str(calls)
    write_stub(bindir, "systemctl", 'printf "%s\\n" "$*" >> "$CALLS"\necho not-found\n')
    assert run_retired_function(env, "user", "obsolete.container").returncode == 0
    assert calls.read_text().splitlines() == ["--user show --property=LoadState --value obsolete.service"]


def test_systemd_failure_is_not_treated_as_missing(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", "exit 1\n")
    assert run_retired_function(env, "user", "obsolete.container").returncode != 0


def test_cleanup_preserves_unrelated_units_and_files_that_fail_to_stop(stub_env):
    bindir, env = stub_env
    unit_dir = Path(env["HOME"]) / ".config/containers/systemd"
    unit_dir.mkdir(parents=True)
    for name in ("lima-bootc.container", "grafana.container", "my-service.container"):
        (unit_dir / name).write_text(name)
    write_stub(bindir, "systemctl", 'if [[ "$*" == *show* ]]; then echo loaded; exit 0; fi\n'
               'if [[ "$*" == "--user stop grafana.service" ]]; then exit 1; fi\nexit 0\n')
    command = ["bash", "-c", 'source "$1"; retired_cleanup_user lima-bootc.container grafana.container; finish',
               "bash", str(REPO / "units/retired-services.sh")]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert not (unit_dir / "lima-bootc.container").exists()
    assert (unit_dir / "grafana.container").exists()
    assert (unit_dir / "my-service.container").read_text() == "my-service.container"


@pytest.mark.parametrize("unit", ["osquery.sh", "server-hardening.sh", "retired-services.sh"])
@pytest.mark.parametrize("host", ["matrix", "telengana"])
def test_retired_vps_exits_before_any_privileged_operation(stub_env, unit, host):
    bindir, env = stub_env
    env.update(DOTFILES_DIR=str(REPO), DOTFILES_MACHINE=host)
    for binary in ("systemctl", "sudo", "yq"):
        write_stub(bindir, binary, 'echo "must not run" >&2\nexit 99\n')
    result = subprocess.run(["bash", str(REPO / "units" / unit)], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "SKIPPED" in result.stdout
    assert "must not run" not in result.stderr


def test_osquery_archive_checksum_rejects_tampering(tmp_path, stub_env):
    _, env = stub_env
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"authentic release")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    command = ["bash", "-c", 'source "$1"; osquery_verify_archive "$2" "$3"', "bash",
               str(REPO / "units/osquery.sh"), str(archive), checksum]
    assert subprocess.run(command, env=env, capture_output=True).returncode == 0
    archive.write_bytes(b"tampered release")
    assert subprocess.run(command, env=env, capture_output=True).returncode != 0
