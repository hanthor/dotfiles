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
    (repo / "inventory.yml").write_text("all:\n  children:\n    vps:\n      hosts:\n        matrix: {}\n        telengana: {}\n")
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


@pytest.mark.skipif(shutil.which("yq") is None or Path("/home/linuxbrew/.linuxbrew/bin/syncthing").exists(), reason="requires yq and no installed syncthing")
def test_missing_binary_disable_failure_is_reported(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\nexit 1\n')
    repo = syncthing_repo(tmp_path, "laptop", "")
    unit = Path(env["HOME"]) / ".config/systemd/user/syncthing.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("existing")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop")
    assert result.returncode != 0
    assert "disable --now syncthing.service" in calls(env)
    assert unit.read_text() == "existing"


@pytest.mark.skipif(shutil.which("yq") is None or Path("/home/linuxbrew/.linuxbrew/bin/syncthing").exists(), reason="requires yq and no installed syncthing")
def test_missing_binary_stops_system_wide_user_service(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\nif [[ "$*" == *"show --property=LoadState"* ]]; then echo loaded; fi\n')
    repo = syncthing_repo(tmp_path, "laptop", "")
    result = run_unit("syncthing", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "disable --now syncthing.service" in calls(env)
