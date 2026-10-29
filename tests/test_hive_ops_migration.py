import shutil
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from unit_helpers import calls, run_unit

pytestmark = pytest.mark.skipif(shutil.which("yq") is None, reason="yq is required")


def hive_repo(tmp_path, host, variables):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars" / f"{host}.yml").write_text(variables)
    (repo / "units").symlink_to(REPO / "units")
    (repo / "inventory.yml").write_text("all:\n  children:\n    vps:\n      hosts:\n        matrix: {}\n        telengana: {}\n")
    return repo


def test_opt_in_deploys_aws_dropins_and_timers_without_restart(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = hive_repo(tmp_path, "laptop", "hive_ops_enabled: true\n")
    args = dict(DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop")
    home = Path(env["HOME"])
    (home / ".kube").mkdir()
    (home / ".kube/config").write_text("offline home cluster")
    result = run_unit("hive-ops", env, **args)
    assert result.returncode == 0, result.stdout + result.stderr
    units = home / ".config/systemd/user"
    dropin = (units / "hive-watchdog.service.d/kubeconfig.conf").read_text()
    assert f"KUBECONFIG={home}/.kube/config-aws-migration" in dropin
    assert "/home/linuxbrew/.linuxbrew/bin" in dropin
    assert (home / ".kube/config").read_text() == "offline home cluster"
    assert (home / ".local/bin/hive-rotate.sh").stat().st_mode & 0o111
    assert "enable --now hive-watchdog.timer" in calls(env)
    assert "restart" not in calls(env)
    (home / "calls").unlink()
    second = run_unit("hive-ops", env, **args)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "daemon-reload" not in calls(env)


def test_opt_out_preserves_unrelated_dropins(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = hive_repo(tmp_path, "laptop", "hive_ops_enabled: false\n")
    units = Path(env["HOME"]) / ".config/systemd/user"
    dropins = units / "hive-watchdog.service.d"
    dropins.mkdir(parents=True)
    (units / "hive-watchdog.timer").write_text("old")
    (units / "hive-watchdog.service").write_text("old")
    (dropins / "kubeconfig.conf").write_text("old")
    (dropins / "custom.conf").write_text("unrelated")
    result = run_unit("hive-ops", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (units / "hive-watchdog.timer").exists()
    assert not (dropins / "kubeconfig.conf").exists()
    assert (dropins / "custom.conf").read_text() == "unrelated"
    assert "disable --now hive-watchdog.timer" in calls(env)


def test_disable_failure_does_not_remove_live_timer_or_helpers(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n[[ "$*" != *"disable --now hive-watchdog.timer"* ]]\n')
    repo = hive_repo(tmp_path, "laptop", "hive_ops_enabled: false\n")
    home = Path(env["HOME"])
    units = home / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "hive-watchdog.timer").write_text("old")
    helpers = home / ".local/bin"
    helpers.mkdir(parents=True)
    (helpers / "hive-rotate.sh").write_text("old")
    result = run_unit("hive-ops", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="laptop")
    assert result.returncode != 0
    assert (units / "hive-watchdog.timer").exists()
    assert (helpers / "hive-rotate.sh").exists()


def test_retired_vps_keeps_old_hive_units(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = hive_repo(tmp_path, "telengana", "hive_ops_enabled: false\n")
    timer = Path(env["HOME"]) / ".config/systemd/user/hive-watchdog.timer"
    timer.parent.mkdir(parents=True)
    timer.write_text("old")
    result = run_unit("hive-ops", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="telengana")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert timer.read_text() == "old" and calls(env) == ""
