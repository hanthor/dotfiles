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
