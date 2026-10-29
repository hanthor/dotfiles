import shutil
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from unit_helpers import calls, run_unit


def syncthing_repo(tmp_path, host, variables):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars" / f"{host}.yml").write_text(variables)
    (repo / "units").symlink_to(REPO / "units")
    (repo / "inventory.yml").write_text("all:\n  children:\n    vps:\n      hosts:\n        matrix:\n        telengana:\n        vps-host:\n")
    return repo


@pytest.mark.parametrize("host,variables", [("matrix", ""), ("laptop", "skip_syncthing: true\n"), ("vm", "machine_profile: vm-test\n")])
def test_excluded_hosts_never_change_service(stub_env, tmp_path, host, variables):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = syncthing_repo(tmp_path, host, variables)
    unit = Path(env["HOME"]) / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("existing")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE=host)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert unit.read_text() == "existing" and calls(env) == ""


def test_missing_binary_disable_failure_is_reported(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "yq", 'echo false\n')
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\nexit 1\n')
    repo = syncthing_repo(tmp_path, "laptop", "")
    unit = Path(env["HOME"]) / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("existing")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", DOTFILES_SYSTEM_ROOT=str(tmp_path / "system"))
    assert result.returncode != 0
    assert "disable --now syncthing.service" in calls(env)
    assert unit.read_text() == "existing"


def test_missing_binary_stops_system_wide_user_service(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "yq", 'echo false\n')
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\nif [[ "$*" == *"show --property=LoadState"* ]]; then echo loaded; fi\n')
    repo = syncthing_repo(tmp_path, "laptop", "")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", DOTFILES_SYSTEM_ROOT=str(tmp_path / "system"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "disable --now syncthing.service" in calls(env)


def test_service_symlink_is_replaced_without_touching_target(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "yq", 'echo false\n')
    write_stub(bindir, "systemctl", '''\
echo "$*" >> "$HOME/calls"
case "$*" in
  *--property=LoadState*) echo loaded ;;
  *--property=UnitFileState*) echo enabled ;;
  *--property=ActiveState*) echo active ;;
esac
''')
    repo = syncthing_repo(tmp_path, "laptop", "")
    system = tmp_path / "system"
    binary = system / "home/linuxbrew/.linuxbrew/bin/syncthing"
    binary.parent.mkdir(parents=True)
    binary.touch()
    unit = Path(env["HOME"]) / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    target = tmp_path / "user-data"
    target.write_text("do not overwrite\n")
    target.chmod(0o600)
    unit.symlink_to(target)
    args = dict(DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", DOTFILES_SYSTEM_ROOT=str(system))
    check = run_unit("syncthing", env, **args, UNITS_CHECK="1")
    assert check.returncode == 0 and "replace syncthing.service symlink" in check.stdout
    assert unit.is_symlink() and target.read_text() == "do not overwrite\n"
    result = run_unit("syncthing", env, **args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not unit.is_symlink()
    assert unit.read_bytes() == (REPO / "units/syncthing/syncthing.service").read_bytes()
    assert unit.stat().st_mode & 0o777 == 0o644
    assert target.read_text() == "do not overwrite\n" and target.stat().st_mode & 0o777 == 0o600


def test_failed_reload_is_retried_with_unchanged_unit(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "yq", 'echo false\n')
    write_stub(bindir, "systemctl", '''\
echo "$*" >> "$HOME/calls"
if [ "$2" = daemon-reload ]; then exit "${FAIL_RELOAD:-0}"; fi
''')
    repo = syncthing_repo(tmp_path, "laptop", "")
    system = tmp_path / "system"
    binary = system / "home/linuxbrew/.linuxbrew/bin/syncthing"
    binary.parent.mkdir(parents=True)
    binary.touch()
    args = dict(DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop", DOTFILES_SYSTEM_ROOT=str(system))
    first = run_unit("syncthing", env, **args, FAIL_RELOAD="1")
    assert first.returncode != 0 and "enable --now" not in calls(env)
    second = run_unit("syncthing", env, **args)
    assert second.returncode == 0, second.stdout + second.stderr
    assert calls(env).splitlines() == ["--user daemon-reload", "--user daemon-reload", "--user enable --now syncthing.service"]


@pytest.mark.parametrize("host,expected", [("vps-host", "excluded on VPS"), ("laptop", "binary and service not installed")])
def test_inventory_gate_works_before_yq_is_installed(stub_env, tmp_path, host, expected):
    bindir, env = stub_env
    for name in ("bash", "dirname", "sed", "head", "id"):
        (bindir / name).symlink_to(shutil.which(name))
    env["PATH"] = str(bindir)
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\necho not-found\n')
    repo = syncthing_repo(tmp_path, host, "")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE=host,
                      DOTFILES_SYSTEM_ROOT=str(tmp_path / "system"))
    assert result.returncode == 0 and expected in result.stdout, result.stdout + result.stderr
    if host == "vps-host":
        assert calls(env) == ""


def test_inventory_gate_fails_closed_when_inventory_invalid(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "yq", 'exit 1\n')
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = syncthing_repo(tmp_path, "laptop", "")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop")
    assert result.returncode != 0 and "check VPS membership" in result.stdout
    assert calls(env) == ""


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("bad_file", ["directory", "dangling-link"])
def test_syncthing_fails_closed_on_unreadable_host_configuration(stub_env, tmp_path, check, bad_file):
    bindir, env = stub_env
    write_stub(bindir, "yq", 'echo yq >> "$HOME/calls"; echo false\n')
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = syncthing_repo(tmp_path, "laptop", "")
    host_file = repo / "host_vars/laptop.yml"
    host_file.unlink()
    if bad_file == "directory":
        host_file.mkdir()
    else:
        host_file.symlink_to("missing-host-vars")
    unit = Path(env["HOME"]) / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("existing")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop",
                      UNITS_CHECK="1" if check else "0")
    assert result.returncode != 0 and "inspect host variables" in result.stdout
    assert unit.read_text() == "existing" and calls(env) == ""
