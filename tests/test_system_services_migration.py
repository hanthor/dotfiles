import subprocess
from pathlib import Path

from conftest import REPO, write_stub
from unit_helpers import calls


def setup_system_services(tmp_path, env, host, variables, podman):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars" / f"{host}.yml").write_text(variables)
    (repo / "units").mkdir()
    (repo / "units/system-services").symlink_to(REPO / "units/system-services")
    units = tmp_path / "units"
    units.mkdir()
    (units / "lib.sh").symlink_to(REPO / "units/lib.sh")
    binary = tmp_path / "podman"
    if podman:
        binary.touch()
    dropin = tmp_path / "systemd/podman.socket.d"
    script = (REPO / "units/system-services.sh").read_text()
    script = script.replace("/usr/bin/podman", str(binary))
    script = script.replace("/etc/systemd/system/podman.socket.d", str(dropin))
    program = units / "system-services.sh"
    program.write_text(script)
    environment = {**env, "DOTFILES_DIR": str(repo), "DOTFILES_MACHINE": host, "STUB_STATE": str(tmp_path)}
    return program, environment, dropin


def run(program, env):
    return subprocess.run(["bash", str(program)], env=env, text=True, capture_output=True)


def systemctl_stub(bindir):
    write_stub(bindir, "systemctl", 'echo "$*" >> "$HOME/calls"\nif [ "$1" = is-active ]; then exit "${SOCKET_ACTIVE:-0}"; fi\n')


def test_nonlaptop_daily_timer_and_user_service_are_idempotent(stub_env, tmp_path):
    bindir, env = stub_env
    systemctl_stub(bindir)
    program, env, _ = setup_system_services(tmp_path, env, "server", "dotfiles_update_delay_seconds: 45\n", False)
    result = run(program, env)
    assert result.returncode == 0, result.stdout + result.stderr
    units = Path(env["HOME"]) / ".config/systemd/user"
    service = (units / "dotfiles-update.service").read_text()
    timer = (units / "dotfiles-update.timer").read_text()
    assert "ExecStartPre=/bin/sleep 45" in service
    assert "WantedBy=default.target" in service
    assert "graphical-session" not in service
    assert "apply-nosecrets" in service
    assert "OnCalendar=daily" in timer and "RandomizedDelaySec=30min" in timer
    assert "--user enable --now dotfiles-update.timer" in calls(env)
    assert "--user enable --now atuin-daemon.service" in calls(env)
    (Path(env["HOME"]) / "calls").unlink()
    result = run(program, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "daemon-reload" not in calls(env)
    assert "restart" not in calls(env)


def test_missing_template_does_not_start_stale_update_timer(stub_env, tmp_path):
    bindir, env = stub_env
    systemctl_stub(bindir)
    program, env, _ = setup_system_services(tmp_path, env, "server", "", False)
    (Path(env["DOTFILES_DIR"]) / "units/system-services").unlink()
    result = run(program, env)
    assert result.returncode != 0
    assert "enable --now dotfiles-update.timer" not in calls(env)


def test_podman_group_membership_socket_and_no_redundant_restart(stub_env, tmp_path):
    bindir, env = stub_env
    systemctl_stub(bindir)
    write_stub(bindir, "id", '''case "$1" in
-u) echo 0 ;;
-un) echo tester ;;
-nG) if [ -e "$STUB_STATE/member" ]; then echo "users podman"; else echo users; fi ;;
esac
''')
    write_stub(bindir, "getent", '[ -e "$STUB_STATE/group" ] || exit 2\n')
    write_stub(bindir, "groupadd", 'echo "groupadd $*" >> "$HOME/calls"\ntouch "$STUB_STATE/group"\n')
    write_stub(bindir, "usermod", 'echo "usermod $*" >> "$HOME/calls"\ntouch "$STUB_STATE/member"\n')
    program, env, dropin = setup_system_services(tmp_path, env, "laptop", "is_laptop: true\n", True)
    result = run(program, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (dropin / "group-access.conf").read_text() == "[Socket]\nSocketGroup=podman\nSocketMode=0660\nDirectoryMode=0710\n"
    assert "groupadd --system podman" in calls(env)
    assert "usermod -a -G podman tester" in calls(env)
    assert "restart podman.socket" in calls(env)
    assert "--user" not in calls(env)
    (Path(env["HOME"]) / "calls").unlink()
    result = run(program, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "groupadd" not in calls(env) and "usermod" not in calls(env)
    assert "restart podman.socket" not in calls(env)


def test_podman_privilege_failure_does_not_suppress_user_services(stub_env, tmp_path):
    bindir, env = stub_env
    systemctl_stub(bindir)
    write_stub(bindir, "id", '''case "$1" in
-u) echo 1000 ;;
-un) echo tester ;;
-nG) echo users ;;
esac
''')
    write_stub(bindir, "getent", "exit 2\n")
    write_stub(bindir, "sudo", "exit 1\n")
    program, env, _ = setup_system_services(tmp_path, env, "server", "", True)
    result = run(program, env)
    assert result.returncode != 0
    assert "FAIL  configure system podman socket" in result.stdout
    assert "--user enable --now dotfiles-update.timer" in calls(env)
    assert "--user enable --now atuin-daemon.service" in calls(env)


def test_retired_vps_and_skip_systemd_never_touch_services(stub_env, tmp_path):
    bindir, env = stub_env
    systemctl_stub(bindir)
    program, env, dropin = setup_system_services(tmp_path, env, "matrix", "", True)
    result = run(program, env)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert calls(env) == "" and not dropin.exists()
    (Path(env["DOTFILES_DIR"]) / "host_vars/server.yml").write_text("skip_systemd: true\n")
    result = run(program, {**env, "DOTFILES_MACHINE": "server"})
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert calls(env) == "" and not dropin.exists()
