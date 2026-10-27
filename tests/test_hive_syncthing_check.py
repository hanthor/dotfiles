from pathlib import Path

import pytest

from conftest import REPO, write_stub
from unit_helpers import run_unit


def repo_for(tmp_path, variables):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars/laptop.yml").write_text(variables)
    (repo / "units").symlink_to(REPO / "units")
    (repo / "inventory.yml").write_text("inventory")
    return repo


def snapshot(home):
    return {str(p.relative_to(home)): (p.stat().st_mode, p.read_bytes() if p.is_file() else None)
            for p in home.rglob("*")}


def stub_yq(bindir):
    write_stub(bindir, "yq", '''
case "$*" in
  *'.hive_ops_timers[]'*) echo hive-watchdog ;;
  *) echo false ;;
esac
''')


def test_hive_check_reports_file_and_service_drift_without_changes(stub_env, tmp_path):
    bindir, env = stub_env
    stub_yq(bindir)
    log = tmp_path / "systemctl-calls"
    env["SYSTEMCTL_LOG"] = str(log)
    write_stub(bindir, "systemctl", '''
echo "$*" >> "$SYSTEMCTL_LOG"
case "$*" in
  *--property=LoadState*) echo loaded ;;
  *--property=UnitFileState*) echo disabled ;;
  *--property=ActiveState*) echo inactive ;;
  *) exit 99 ;;
esac
''')
    repo = repo_for(tmp_path, "hive_ops_enabled: true\n")
    home = Path(env["HOME"])
    dest = home / ".local/bin/hive-peak.sh"
    dest.parent.mkdir(parents=True)
    dest.write_text("old helper")
    before = snapshot(home)
    result = run_unit("hive-ops", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", UNITS_CHECK="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGE: update" in result.stdout and "hive-peak.sh" in result.stdout
    assert "CHANGE: enable hive-watchdog.timer" in result.stdout
    assert "CHANGE: start hive-watchdog.timer" in result.stdout
    assert snapshot(home) == before
    assert all(" show " in f" {line} " for line in log.read_text().splitlines())


def test_hive_check_reports_opt_out_and_keeps_files(stub_env, tmp_path):
    bindir, env = stub_env
    stub_yq(bindir)
    write_stub(bindir, "systemctl", 'exit 99\n')
    repo = repo_for(tmp_path, "hive_ops_enabled: false\n")
    home = Path(env["HOME"])
    timer = home / ".config/systemd/user/hive-watchdog.timer"
    timer.parent.mkdir(parents=True)
    timer.write_text("old")
    before = snapshot(home)
    result = run_unit("hive-ops", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", UNITS_CHECK="1")
    assert result.returncode == 0
    assert "CHANGE: disable and stop hive-watchdog.timer" in result.stdout
    assert "CHANGE: remove" in result.stdout
    assert snapshot(home) == before


def test_hive_check_service_inspection_failure_is_error(stub_env, tmp_path):
    bindir, env = stub_env
    stub_yq(bindir)
    write_stub(bindir, "systemctl", 'exit 1\n')
    repo = repo_for(tmp_path, "hive_ops_enabled: true\n")
    home = Path(env["HOME"])
    before = snapshot(home)
    result = run_unit("hive-ops", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", UNITS_CHECK="1")
    assert result.returncode != 0 and "FAIL  check hive-watchdog.timer" in result.stdout
    assert snapshot(home) == before


@pytest.mark.skipif(Path("/home/linuxbrew/.linuxbrew/bin/syncthing").exists(), reason="requires missing system syncthing")
def test_syncthing_check_plans_disable_without_mutation(stub_env, tmp_path):
    bindir, env = stub_env
    stub_yq(bindir)
    write_stub(bindir, "systemctl", 'exit 99\n')
    repo = repo_for(tmp_path, "")
    home = Path(env["HOME"])
    unit = home / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("old")
    before = snapshot(home)
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", UNITS_CHECK="1")
    assert result.returncode == 0
    assert "CHANGE: disable and stop syncthing.service" in result.stdout
    assert snapshot(home) == before


@pytest.mark.skipif(Path("/home/linuxbrew/.linuxbrew/bin/syncthing").exists(), reason="requires missing system syncthing")
def test_syncthing_check_reports_systemctl_error(stub_env, tmp_path):
    bindir, env = stub_env
    stub_yq(bindir)
    write_stub(bindir, "systemctl", 'exit 1\n')
    repo = repo_for(tmp_path, "")
    home = Path(env["HOME"])
    before = snapshot(home)
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", UNITS_CHECK="1")
    assert result.returncode != 0 and "FAIL  check syncthing service" in result.stdout
    assert snapshot(home) == before


@pytest.mark.skipif(not Path("/home/linuxbrew/.linuxbrew/bin/syncthing").exists(), reason="requires installed system syncthing")
def test_syncthing_check_reports_file_and_service_drift(stub_env, tmp_path):
    bindir, env = stub_env
    stub_yq(bindir)
    write_stub(bindir, "systemctl", '''
case "$*" in
  *--property=LoadState*) echo loaded ;;
  *--property=UnitFileState*) echo disabled ;;
  *--property=ActiveState*) echo inactive ;;
  *) exit 99 ;;
esac
''')
    repo = repo_for(tmp_path, "")
    home = Path(env["HOME"])
    unit = home / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("old")
    before = snapshot(home)
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", UNITS_CHECK="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGE: update syncthing.service" in result.stdout
    assert "CHANGE: enable syncthing.service" in result.stdout
    assert "CHANGE: start syncthing.service" in result.stdout
    assert snapshot(home) == before
