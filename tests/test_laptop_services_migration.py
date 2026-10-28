import shlex
import subprocess

from pathlib import Path

from conftest import REPO, write_stub
from unit_helpers import calls, run_unit


def laptop_repo(tmp_path, host, variables):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars" / f"{host}.yml").write_text(variables)
    (repo / "units").symlink_to(REPO / "units")
    return repo


def test_laptop_login_service_and_idempotent_reload(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "kanpur", "is_laptop: true\ndotfiles_update_delay_seconds: 90\n")
    args = dict(DOTFILES_DIR=str(repo), DOTFILES_MACHINE="kanpur")
    first = run_unit("laptop-services", env, **args)
    assert first.returncode == 0, first.stdout + first.stderr
    home = Path(env["HOME"])
    update = (home / ".config/systemd/user/dotfiles-update.service").read_text()
    assert "ExecStartPre=/bin/sleep 90" in update
    assert "WantedBy=graphical-session.target" in update
    assert "apply-nosecrets" in update
    assert "ExecStart=/usr/bin/env just " in update
    assert "ExecStart=/usr/bin/env atuin daemon start --force" in (home / ".config/systemd/user/atuin-daemon.service").read_text()
    assert "enable dotfiles-update.service" in calls(env)
    assert "enable --now dotfiles-update.service" not in calls(env)
    assert "enable --now atuin-daemon.service" in calls(env)
    (home / "calls").unlink()
    second = run_unit("laptop-services", env, **args)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "daemon-reload" not in calls(env)


def test_himachal_optouts_disable_only_owned_timers(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\ndotfiles_auto_update: false\nphone_apply_enabled: false\n")
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    for name in ("dotfiles-update.service", "dotfiles-update.timer", "phone-apply.service", "phone-apply.timer", "unrelated.service"):
        (units / name).write_text("old")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="himachal")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (units / "unrelated.service").read_text() == "old"
    assert not (units / "phone-apply.timer").exists()
    assert not (units / "phone-apply.service").exists()
    assert not (units / "dotfiles-update.service").exists()
    assert not (units / "dotfiles-update.timer").exists()
    assert "disable --now phone-apply.timer" in calls(env)
    assert "enable --now system-mitigator.service" in calls(env)
    assert "unrelated.service" not in calls(env)


def test_failed_disable_preserves_timer_and_reports_failure(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n[[ "$*" != *"disable --now phone-apply.timer"* ]]\n')
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\nphone_apply_enabled: false\n")
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "phone-apply.timer").write_text("old")
    (units / "phone-apply.service").write_text("old")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="himachal")
    assert result.returncode != 0
    assert (units / "phone-apply.timer").exists()
    assert (units / "phone-apply.service").exists()
    assert "enable --now system-mitigator.service" in calls(env)


def test_failed_old_timer_disable_does_not_enable_login_update(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n[[ "$*" != *"disable --now dotfiles-update.timer"* ]]\n')
    repo = laptop_repo(tmp_path, "kanpur", "is_laptop: true\n")
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "dotfiles-update.timer").write_text("old")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="kanpur")
    assert result.returncode != 0
    assert (units / "dotfiles-update.timer").read_text() == "old"
    assert "enable dotfiles-update.service" not in calls(env)
    assert "enable --now atuin-daemon.service" in calls(env)


def test_himachal_phone_schedule_is_preserved_when_enabled(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\nphone_apply_enabled: true\n")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="himachal")
    assert result.returncode == 0, result.stdout + result.stderr
    units = Path(env["HOME"]) / ".config/systemd/user"
    assert "OnCalendar=*-*-* 00/2:00:00" in (units / "phone-apply.timer").read_text()
    assert "enable --now phone-apply.timer" in calls(env)


def test_phone_push_uses_remote_machine_identity_and_cleans_up(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", "exit 0\n")
    git = write_stub(bindir, "phone-git", "printf archive\n")
    ssh = write_stub(
        bindir, "phone-ssh",
        'host="$3"; shift 3\n'
        '[ "${OFFLINE_HOST:-}" != "$host" ] || exit 255\n'
        'export HOME="$REMOTE_HOMES/$host"\n'
        'export DOTFILES_MACHINE=localhost\nbash -c "$1"\n',
    )
    write_stub(bindir, "tar", 'mkdir -p "$4/scripts"\ncp "$STUB_RUNNER" "$4/scripts/run-units.sh"\n')
    runner = tmp_path / "runner.sh"
    runner.write_text('printf "%s %s\\n" "$DOTFILES_MACHINE" "$*" >> "$RECORD"\n')
    remote_homes = tmp_path / "phones"
    for host in ("termux", "mumbai"):
        (remote_homes / host).mkdir(parents=True)
    env.update(REMOTE_HOMES=str(remote_homes), STUB_RUNNER=str(runner), RECORD=str(tmp_path / "record"))
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\nphone_apply_enabled: true\n")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="himachal")
    assert result.returncode == 0, result.stdout + result.stderr
    service = (Path(env["HOME"]) / ".config/systemd/user/phone-apply.service").read_text()
    starts = [line for line in service.splitlines() if line.startswith("ExecStart=")]
    assert len(starts) == 2 and all(line.startswith("ExecStart=-:/bin/bash") for line in starts)
    commands = [line.removeprefix("ExecStart=-:") for line in starts]
    for command in commands:
        command = command.replace("/usr/bin/git", str(git)).replace("/usr/bin/ssh", str(ssh))
        completed = subprocess.run(shlex.split(command), env=env, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "record").read_text().splitlines() == ["termux --no-secrets", "mumbai --no-secrets"]
    for host in ("termux", "mumbai"):
        assert list((remote_homes / host / ".cache").iterdir()) == []
    (tmp_path / "record").unlink()
    statuses = []
    for command in commands:
        command = command.replace("/usr/bin/git", str(git)).replace("/usr/bin/ssh", str(ssh))
        result = subprocess.run(shlex.split(command), env={**env, "OFFLINE_HOST": "termux"}, capture_output=True, text=True)
        statuses.append(result.returncode)
    assert statuses == [255, 0]
    assert (tmp_path / "record").read_text().splitlines() == ["mumbai --no-secrets"]


def test_missing_phone_timer_source_never_starts_stale_timer(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\nphone_apply_enabled: true\n")
    (repo / "units").unlink()
    sources = repo / "units/laptop-services"
    sources.mkdir(parents=True)
    for name in ("system-mitigator.py", "system-mitigator.service"):
        (sources / name).symlink_to(REPO / "units/laptop-services" / name)
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "phone-apply.timer").write_text("old")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="himachal")
    assert result.returncode != 0
    assert (units / "phone-apply.timer").read_text() == "old"
    assert "enable --now phone-apply.timer" not in calls(env)
    assert "enable --now system-mitigator.service" in calls(env)


def test_missing_mitigator_script_never_starts_stale_service(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\nphone_apply_enabled: false\n")
    (repo / "units").unlink()
    sources = repo / "units/laptop-services"
    sources.mkdir(parents=True)
    (sources / "system-mitigator.service").symlink_to(REPO / "units/laptop-services/system-mitigator.service")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="himachal")
    assert result.returncode != 0
    assert "enable --now system-mitigator.service" not in calls(env)
    assert "enable --now atuin-daemon.service" in calls(env)


def test_laptop_removes_only_managed_old_default_target_link(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "kanpur", "is_laptop: true\n")
    units = Path(env["HOME"]) / ".config/systemd/user"
    link = units / "default.target.wants/dotfiles-update.service"
    link.parent.mkdir(parents=True)
    link.symlink_to("../dotfiles-update.service")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="kanpur")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not link.is_symlink()
    link.symlink_to("/opt/custom/dotfiles-update.service")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="kanpur")
    assert result.returncode == 0, result.stdout + result.stderr
    assert link.is_symlink() and link.readlink() == Path("/opt/custom/dotfiles-update.service")


def test_retired_vps_is_never_touched(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\n')
    repo = laptop_repo(tmp_path, "telengana", "is_laptop: true\n")
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="telengana")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert calls(env) == ""
