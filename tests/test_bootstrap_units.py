import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub



def test_bootstrap_runs_second_phase_after_first_fails(stub_env, tmp_path):
    _, env = stub_env
    env["CALLS"] = str(tmp_path / "calls")
    script = r'''
source "$1/bootstrap.sh" --name test --type desktop
for f in ensure_python ensure_git clone_repo get_machine_name get_machine_type register_in_inventory write_machine_name set_hostname ensure_sudo ensure_tailscale setup_bitwarden push_inventory_changes; do
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


@pytest.mark.parametrize("failure", ["remote", "add", "diff", "commit", "push"])
def test_inventory_push_propagates_git_failures_inside_or(stub_env, tmp_path, failure):
    bindir, env = stub_env
    env.update(CALLS=str(tmp_path / "git-calls"), FAIL_GIT=failure, TEST_REPO=str(tmp_path))
    write_stub(bindir, "git", '''
printf '%s\\n' "$1" >> "$CALLS"
if [ "$1" = "$FAIL_GIT" ]; then exit 7; fi
if [ "$1" = diff ]; then exit 1; fi
''')
    script = r'''
source "$1/bootstrap.sh" --name newhost --type desktop
DOTFILES_DIR="$TEST_REPO"
INVENTORY_MODIFIED=true
rc=0
push_inventory_changes || rc=$?
exit "$rc"
'''
    result = subprocess.run(["bash", "-c", script, "bash", str(REPO)], env=env, capture_output=True, text=True)
    assert result.returncode == 7
    calls = Path(env["CALLS"]).read_text().splitlines()
    assert calls[-1] == failure
    assert "Inventory pushed" not in result.stdout


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
    result = subprocess.run(["bash", "-c", 'source "$1"; setup_bitwarden', "bash", str(bootstrap)],
                            env=env, capture_output=True, text=True)
    assert (result.returncode != 0) is (existing == "directory")
    assert target.read_text() == "untouched"
    assert "private-session-sentinel" not in result.stdout + result.stderr
    if existing != "directory":
        assert not cache.is_symlink()
        assert cache.read_text() == env["BW_SESSION"]
        assert cache.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".bw_session.*"))
