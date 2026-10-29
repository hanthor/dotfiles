import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub



def test_bootstrap_runs_second_phase_after_first_fails(stub_env, tmp_path):
    _, env = stub_env
    env["CALLS"] = str(tmp_path / "calls")
    script = r'''
source "$1/bootstrap.sh" --name test --type desktop
for f in ensure_python ensure_git clone_repo get_machine_name get_machine_type register_in_inventory write_machine_name set_hostname ensure_sudo ensure_tailscale setup_bitwarden; do
  eval "$f() { :; }"
done
run_phase1() { echo first >> "$CALLS"; return 7; }
run_phase2() { echo second >> "$CALLS"; return 0; }
main
'''
    result = subprocess.run(["bash", "-c", script, "bash", str(REPO)], env=env, capture_output=True, text=True)
    assert result.returncode == 7
    assert Path(env["CALLS"]).read_text().splitlines() == ["first", "second"]
    assert "Bootstrap complete!" not in result.stdout


@pytest.mark.parametrize("no_secrets", [False, True])
def test_unit_session_respects_no_secrets_and_keeps_session_off_argv(stub_env, tmp_path, no_secrets):
    bindir, env = stub_env
    log = tmp_path / "bw-calls"
    write_stub(bindir, "bw", 'printf "%s\\n" "$*" >> "$CALLS"\n[ "${BW_SESSION:-}" = "test-session" ]\n')
    env.update(BW_SESSION="test-session", CALLS=str(log))
    if no_secrets:
        env["UNITS_NO_SECRETS"] = "1"
    else:
        env.pop("UNITS_NO_SECRETS", None)
    result = subprocess.run(
        ["bash", "-c", 'source "$1/units/lib.sh"; bw_session', "bash", str(REPO)],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0
    if no_secrets:
        assert result.stdout == ""
        assert not log.exists()
    else:
        assert result.stdout == "test-session"
        assert log.read_text().splitlines() == ["unlock --check"]


@pytest.mark.parametrize("local_registered,remote_registered", [(False, False), (True, False)])
def test_bootstrap_refuses_unreviewed_registration(stub_env, tmp_path, local_registered, remote_registered):
    bindir, env = stub_env
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("register-machine.py", "inventory_parser.py"):
        shutil.copy(REPO / "scripts" / name, scripts / name)
    def inventory(registered):
        host = "    newhost:\n      ansible_host: localhost\n" if registered else ""
        member = "        newhost:\n" if registered else ""
        return f"all:\n  hosts:\n{host}  children:\n    desktop:\n      hosts:\n{member}"
    (tmp_path / "inventory.yml").write_text(inventory(local_registered))
    remote = tmp_path / "remote-inventory"
    remote.write_text(inventory(remote_registered))
    env.update(TEST_REPO=str(tmp_path), REMOTE_INVENTORY=str(remote))
    write_stub(bindir, "git", 'case "$*" in *"show refs/remotes/origin/master:inventory.yml"*) cat "$REMOTE_INVENTORY" ;; esac\n')
    script = r'''
source "$1/bootstrap.sh" --name newhost --type desktop
DOTFILES_DIR="$TEST_REPO"
register_in_inventory
'''
    result = subprocess.run(["bash", "-c", script, "bash", str(REPO)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "review" in result.stderr.lower()
    assert (tmp_path / "inventory.yml").read_text() == inventory(local_registered)


def test_existing_checkout_is_not_pulled(stub_env, tmp_path):
    bindir, env = stub_env
    (tmp_path / ".git").mkdir()
    env.update(TEST_REPO=str(tmp_path), CALLS=str(tmp_path / "calls"))
    write_stub(bindir, "git", 'echo touched >> "$CALLS"\n')
    script = 'source "$1/bootstrap.sh" --name test --type desktop; DOTFILES_DIR="$TEST_REPO"; clone_repo'
    result = subprocess.run(["bash", "-c", script, "bash", str(REPO)], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert not Path(env["CALLS"]).exists()


def test_termux_bootstrap_preserves_android_and_propagates_identity(stub_env, tmp_path):
    _, env = stub_env
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = scripts / "run-units.sh"
    runner.write_text('#!/bin/sh\nprintf "%s %s %s\\n" "$DOTFILES_MACHINE" "$DOTFILES_IS_DESKTOP" "$*" >> "$CALLS"\n')
    runner.chmod(0o755)
    env.update(TEST_REPO=str(tmp_path), CALLS=str(tmp_path / "calls"))
    script = r'''
source "$1/bootstrap.sh" --name termux --type termux_hosts
DOTFILES_DIR="$TEST_REPO"
is_termux() { return 0; }
for f in ensure_python ensure_git clone_repo get_machine_name get_machine_type register_in_inventory setup_bitwarden; do
  eval "$f() { :; }"
done
for f in write_machine_name set_hostname ensure_sudo ensure_tailscale; do
  eval "$f() { echo unexpected-root-operation >> \"\$CALLS\"; return 1; }"
done
main
'''
    result = subprocess.run(["bash", "-c", script, "bash", str(REPO)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(env["CALLS"]).read_text().splitlines() == [
        "termux false --no-secrets", "termux false --tags omp,secrets"]


def test_termux_bitwarden_session_does_not_write_tmp_cache(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "bw", '''
case "$1" in status) printf '{"status":"unlocked"}\\n' ;; unlock|sync) exit 0 ;; *) exit 1 ;; esac
''')
    env["BW_SESSION"] = "private-session-sentinel"
    cache = tmp_path / "bw_session"
    bootstrap = tmp_path / "bootstrap.sh"
    bootstrap.write_text((REPO / "bootstrap.sh").read_text().replace("/tmp/bw_session", str(cache)))
    script = 'source "$1" --name termux --type termux_hosts; is_termux() { return 0; }; setup_bitwarden'
    result = subprocess.run(["bash", "-c", script, "bash", str(bootstrap)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not cache.exists()
    assert env["BW_SESSION"] not in result.stdout + result.stderr


@pytest.mark.parametrize("existing", ["insecure", "symlink", "directory"])
def test_bootstrap_cache_is_private_and_never_follows_symlinks(stub_env, tmp_path, existing):
    bindir, env = stub_env
    cache = tmp_path / "bw_session"
    target = tmp_path / "target"
    target.write_text("untouched")
    if existing == "insecure":
        cache.write_text("old")
        cache.chmod(0o666)
    elif existing == "symlink":
        cache.symlink_to(target)
    else:
        cache.mkdir()
    write_stub(bindir, "bw", '''
case "$1" in
  status) printf '{"status":"unlocked"}\\n' ;;
  unlock|sync) exit 0 ;;
  *) exit 1 ;;
esac
''')
    env["BW_SESSION"] = "private-session-sentinel"
    bootstrap = tmp_path / "bootstrap.sh"
    bootstrap.write_text((REPO / "bootstrap.sh").read_text().replace("/tmp/bw_session", str(cache)).replace('dir="/tmp"', f'dir="{tmp_path}"'))
    result = subprocess.run(["bash", "-c", 'source "$1" --name test --type desktop; setup_bitwarden', "bash", str(bootstrap)],
                            env=env, capture_output=True, text=True)
    assert (result.returncode != 0) is (existing == "directory")
    assert target.read_text() == "untouched"
    assert "private-session-sentinel" not in result.stdout + result.stderr
    if existing != "directory":
        assert not cache.is_symlink()
        assert cache.read_text() == env["BW_SESSION"]
        assert cache.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".bw_session.*"))
