import os
import subprocess
from pathlib import Path

from conftest import write_stub
from test_laptop_services_migration import laptop_repo
from test_system_services_migration import setup_system_services
from unit_helpers import run_unit


def systemctl_stub(bindir):
    write_stub(bindir, "systemctl", '''echo "$*" >> "$CONTROL_LOG"
[ "$1" != --user ] || shift
case "$1" in
  is-enabled)
    if [ "${INSPECTION_ERROR:-0}" = 1 ]; then exit 1; fi
    echo "${ENABLED_STATE:-enabled}"
    [ "${ENABLED_STATE:-enabled}" = enabled ] && exit 0
    exit "${ENABLED_RC:-1}" ;;
  is-active)
    echo "${ACTIVE_STATE:-active}"
    [ "${ACTIVE_STATE:-active}" = active ] && exit 0
    exit "${ACTIVE_RC:-3}" ;;
  *) [ "${CHECK_GUARD:-0}" != 1 ] || exit 99 ;;
esac
''')


def snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if path.is_symlink():
            value = ("link", os.readlink(path))
        elif path.is_file():
            value = ("file", path.read_bytes())
        else:
            value = ("dir",)
        result[str(path.relative_to(root))] = (info.st_mode, value)
    return result


def run_script(program, env):
    return subprocess.run(["bash", str(program)], env=env, text=True, capture_output=True)


def check_env(tmp_path, env):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return {**env, "CONTROL_LOG": str(tmp_path / "systemctl.log"),
            "TMPDIR": str(scratch), "UNITS_CHECK": "1", "CHECK_GUARD": "1"}


def assert_read_only_calls(env):
    log = Path(env["CONTROL_LOG"])
    for call in log.read_text().splitlines() if log.exists() else []:
        words = call.split()
        if words and words[0] == "--user":
            words.pop(0)
        assert words and words[0] in {"is-enabled", "is-active"}, call
    assert list(Path(env["TMPDIR"]).iterdir()) == []


def test_laptop_clean_check_and_optout_drift_are_nonmutating(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    repo = laptop_repo(tmp_path, "himachal", "is_laptop: true\n")
    env = check_env(tmp_path, original_env)
    args = {"DOTFILES_DIR": str(repo), "DOTFILES_MACHINE": "himachal"}
    applied = run_unit("laptop-services", {**env, "UNITS_CHECK": "0", "CHECK_GUARD": "0"}, **args)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    Path(env["CONTROL_LOG"]).unlink()
    home = Path(env["HOME"])
    before = snapshot(home)
    clean = run_unit("laptop-services", env, **args)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "would " not in clean.stdout
    assert snapshot(home) == before
    assert_read_only_calls(env)

    (repo / "host_vars/himachal.yml").write_text(
        "is_laptop: true\ndotfiles_auto_update: false\nphone_apply_enabled: false\n"
    )
    units = home / ".config/systemd/user"
    (units / "dotfiles-update.timer").write_text("obsolete")
    (units / "atuin-daemon.service").chmod(0o600)
    (home / ".local/bin/system-mitigator.py").chmod(0o600)
    before = snapshot(home)
    Path(env["CONTROL_LOG"]).unlink()
    drift = run_unit("laptop-services", {**env, "ENABLED_STATE": "disabled", "ACTIVE_STATE": "inactive"}, **args)
    assert drift.returncode == 0, drift.stdout + drift.stderr
    for expected in ("would disable and remove", "dotfiles-update.timer", "dotfiles-update.service",
                     "phone-apply.timer", "would remove", "phone-apply.service", "would set mode 644",
                     "would set mode 755", "would enable atuin-daemon.service", "would start atuin-daemon.service"):
        assert expected in drift.stdout
    assert snapshot(home) == before
    assert_read_only_calls(env)


def test_laptop_missing_units_and_inspection_failures(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    repo = laptop_repo(tmp_path, "kanpur", "is_laptop: true\n")
    env = check_env(tmp_path, original_env)
    home = Path(env["HOME"])
    before = snapshot(home)
    args = {"DOTFILES_DIR": str(repo), "DOTFILES_MACHINE": "kanpur"}
    result = run_unit("laptop-services", {**env, "ENABLED_STATE": "not-found", "ENABLED_RC": "4", "ACTIVE_STATE": "inactive", "ACTIVE_RC": "4"}, **args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "would install" in result.stdout and "would start atuin-daemon.service" in result.stdout
    assert snapshot(home) == before
    assert_read_only_calls(env)
    result = run_unit("laptop-services", {**env, "INSPECTION_ERROR": "1"}, **args)
    assert result.returncode != 0
    assert "Cannot inspect enabled state" in result.stderr
    assert snapshot(home) == before
    assert_read_only_calls(env)


def test_laptop_comparison_error_is_not_reported_as_drift(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    repo = laptop_repo(tmp_path, "kanpur", "is_laptop: true\n")
    env = check_env(tmp_path, original_env)
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "atuin-daemon.service").write_text("existing")
    write_stub(bindir, "cmp", "exit 2\n")
    before = snapshot(Path(env["HOME"]))
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="kanpur")
    assert result.returncode != 0 and "Cannot compare" in result.stderr
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)


def test_system_user_service_check_reports_drift_and_missing_template(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    program, env, _ = setup_system_services(tmp_path, env, "server", "", False)
    home = Path(env["HOME"])
    before = snapshot(home)
    result = run_script(program, {**env, "ENABLED_STATE": "disabled", "ACTIVE_STATE": "inactive"})
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in ("would install", "dotfiles-update.service", "dotfiles-update.timer",
                     "atuin-daemon.service", "would enable dotfiles-update.timer", "would start atuin-daemon.service"):
        assert expected in result.stdout
    assert snapshot(home) == before
    assert_read_only_calls(env)
    (Path(env["DOTFILES_DIR"]) / "units/system-services").unlink()
    result = run_script(program, env)
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    assert snapshot(home) == before
    assert_read_only_calls(env)


def test_system_check_handles_absent_unit_but_rejects_manager_error(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    program, env, _ = setup_system_services(tmp_path, env, "server", "", False)
    missing = run_script(program, {**env, "ENABLED_STATE": "not-found", "ENABLED_RC": "4", "ACTIVE_STATE": "inactive", "ACTIVE_RC": "4"})
    assert missing.returncode == 0, missing.stdout + missing.stderr
    assert "would start dotfiles-update.timer" in missing.stdout
    failed = run_script(program, {**env, "ACTIVE_STATE": "inactive", "ACTIVE_RC": "4"})
    assert failed.returncode != 0
    assert "Cannot inspect active state" in failed.stderr
    assert_read_only_calls(env)


def test_system_clean_check_and_manager_error(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    program, env, _ = setup_system_services(tmp_path, env, "server", "", False)
    applied = run_script(program, {**env, "UNITS_CHECK": "0", "CHECK_GUARD": "0"})
    assert applied.returncode == 0, applied.stdout + applied.stderr
    Path(env["CONTROL_LOG"]).unlink()
    before = snapshot(Path(env["HOME"]))
    clean = run_script(program, env)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "would " not in clean.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)
    failed = run_script(program, {**env, "INSPECTION_ERROR": "1"})
    assert failed.returncode != 0 and "Cannot inspect enabled state" in failed.stderr
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)


def test_podman_check_plans_group_dropin_and_restart_without_mutation(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    write_stub(bindir, "id", '''case "$1" in
-u) echo 1000 ;;
-un) echo tester ;;
-nG) echo users ;;
esac
''')
    write_stub(bindir, "getent", 'exit "${GROUP_RC:-2}"\n')
    for name in ("sudo", "groupadd", "usermod", "install", "chmod"):
        write_stub(bindir, name, 'echo "$0 $*" >> "$MUTATION_LOG"\nexit 99\n')
    env = check_env(tmp_path, original_env)
    env["MUTATION_LOG"] = str(tmp_path / "mutations")
    program, env, dropin = setup_system_services(tmp_path, env, "laptop", "is_laptop: true\n", True)
    home_before = snapshot(Path(env["HOME"]))
    result = run_script(program, env)
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in ("would create podman group", "would add tester to podman group", "would create",
                     "group-access.conf", "would reload system systemd", "would restart podman.socket"):
        assert expected in result.stdout
    assert not dropin.exists() and not Path(env["MUTATION_LOG"]).exists()
    assert snapshot(Path(env["HOME"])) == home_before
    assert_read_only_calls(env)
    error = run_script(program, {**env, "GROUP_RC": "3"})
    assert error.returncode != 0 and "FAIL  configure system podman socket" in error.stdout
    assert not dropin.exists() and not Path(env["MUTATION_LOG"]).exists()
    assert_read_only_calls(env)


def test_podman_clean_check_and_socket_inspection_error(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    write_stub(bindir, "id", '''case "$1" in
-u) echo 1000 ;;
-un) echo tester ;;
-nG) echo "users podman" ;;
esac
''')
    write_stub(bindir, "getent", "exit 0\n")
    env = check_env(tmp_path, original_env)
    program, env, dropin = setup_system_services(tmp_path, env, "laptop", "is_laptop: true\n", True)
    dropin.mkdir(parents=True)
    dropin.chmod(0o755)
    conf = dropin / "group-access.conf"
    conf.write_text("[Socket]\nSocketGroup=podman\nSocketMode=0660\nDirectoryMode=0710\n")
    conf.chmod(0o644)
    before = snapshot(tmp_path / "systemd")
    result = run_script(program, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "would " not in result.stdout
    assert snapshot(tmp_path / "systemd") == before
    assert_read_only_calls(env)
    result = run_script(program, {**env, "INSPECTION_ERROR": "1"})
    assert result.returncode != 0 and "Cannot inspect enabled state of podman.socket" in result.stderr
    assert snapshot(tmp_path / "systemd") == before
    assert_read_only_calls(env)


def test_laptop_render_error_fails_without_mutation(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    write_stub(bindir, "cat", '[ "$#" -gt 0 ] || exit 2\nexec /usr/bin/cat "$@"\n')
    repo = laptop_repo(tmp_path, "kanpur", "is_laptop: true\n")
    env = check_env(tmp_path, original_env)
    before = snapshot(Path(env["HOME"]))
    result = run_unit("laptop-services", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="kanpur")
    assert result.returncode != 0 and "FAIL  render dotfiles update service" in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)


def test_system_comparison_error_is_not_treated_as_file_drift(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    program, env, _ = setup_system_services(tmp_path, env, "server", "", False)
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "dotfiles-update.timer").write_text("existing")
    write_stub(bindir, "cmp", "exit 2\n")
    before = snapshot(Path(env["HOME"]))
    result = run_script(program, env)
    assert result.returncode != 0 and "Cannot compare" in result.stderr
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)


def test_retired_hosts_skip_check_without_service_access(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    program, env, dropin = setup_system_services(tmp_path, env, "matrix", "is_laptop: true\n", True)
    before = snapshot(Path(env["HOME"]))
    laptop = run_unit("laptop-services", env, DOTFILES_DIR=env["DOTFILES_DIR"], DOTFILES_MACHINE="matrix")
    system = run_script(program, env)
    assert laptop.returncode == system.returncode == 0
    assert "SKIPPED" in laptop.stdout and "SKIPPED" in system.stdout
    assert not Path(env["CONTROL_LOG"]).exists() and not dropin.exists()
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)


def test_unreadable_host_variables_fail_both_checks(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    program, env, dropin = setup_system_services(tmp_path, env, "laptop", "is_laptop: true\n", True)
    hostvars = Path(env["DOTFILES_DIR"]) / "host_vars/laptop.yml"
    hostvars.unlink()
    hostvars.symlink_to(tmp_path / "missing-host-vars")
    before = snapshot(Path(env["HOME"]))
    laptop = run_unit("laptop-services", env, DOTFILES_DIR=env["DOTFILES_DIR"], DOTFILES_MACHINE="laptop")
    system = run_script(program, env)
    assert laptop.returncode != 0 and system.returncode != 0
    assert "FAIL  inspect host variables" in laptop.stdout
    assert "FAIL  inspect host variables" in system.stdout
    assert not Path(env["CONTROL_LOG"]).exists() and not dropin.exists()
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)


def test_service_drift_does_not_disclose_file_contents(stub_env, tmp_path):
    bindir, original_env = stub_env
    systemctl_stub(bindir)
    env = check_env(tmp_path, original_env)
    _, env, _ = setup_system_services(tmp_path, env, "laptop", "is_laptop: true\n", False)
    units = Path(env["HOME"]) / ".config/systemd/user"
    units.mkdir(parents=True)
    secret = "sensitive-unit-content-example"
    (units / "atuin-daemon.service").write_text(secret)
    before = snapshot(Path(env["HOME"]))
    result = run_unit("laptop-services", env, DOTFILES_DIR=env["DOTFILES_DIR"], DOTFILES_MACHINE="laptop")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "would update" in result.stdout
    assert secret not in result.stdout + result.stderr
    assert snapshot(Path(env["HOME"])) == before
    assert_read_only_calls(env)
