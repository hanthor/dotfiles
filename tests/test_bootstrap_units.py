import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


@pytest.fixture
def phase_env(stub_env, tmp_path):
    bindir, env = stub_env
    repo = tmp_path / "checkout"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    log = tmp_path / "calls"
    write_stub(bindir, "ansible-playbook", 'printf "ansible %s\\n" "$*" >> "$CALLS"\nexit "${ANSIBLE_RC:-0}"\n')
    write_stub(scripts, "run-units.sh", 'printf "units %s\\n" "$*" >> "$CALLS"\nexit "${UNITS_RC:-0}"\n')
    env.update(CALLS=str(log), TEST_REPO=str(repo), BW_SESSION="test-session")
    return env, log


def run_phase(env, phase):
    return subprocess.run(
        ["bash", "-c", 'source "$1/bootstrap.sh" --name test --type desktop; DOTFILES_DIR="$TEST_REPO"; MACHINE_NAME=test; MACHINE_TYPE=desktop; "$2"',
         "bash", str(REPO), phase],
        env=env, capture_output=True, text=True,
    )


@pytest.mark.parametrize("phase,unit_args", [("run_phase1", "--no-secrets"), ("run_phase2", "--tags omp,secrets")])
@pytest.mark.parametrize("ansible_rc,units_rc,expected", [(0, 0, 0), (7, 0, 7), (0, 9, 9), (7, 9, 7)])
def test_bootstrap_phases_continue_and_combine_errors(phase_env, phase, unit_args, ansible_rc, units_rc, expected):
    env, log = phase_env
    env.update(ANSIBLE_RC=str(ansible_rc), UNITS_RC=str(units_rc))
    result = run_phase(env, phase)
    assert result.returncode == expected
    calls = log.read_text().splitlines()
    assert len(calls) == 2
    assert calls[0].startswith("ansible ")
    assert calls[1] == f"units {unit_args}"
    assert "test-session" not in "\n".join(calls)
    if phase == "run_phase1":
        assert "--skip-tags secrets" in calls[0]
    else:
        assert "--tags secrets" in calls[0]


def test_bootstrap_runs_second_phase_after_first_fails(stub_env, tmp_path):
    _, env = stub_env
    env["CALLS"] = str(tmp_path / "calls")
    script = r'''
source "$1/bootstrap.sh" --name test --type desktop
for f in ensure_python ensure_git ensure_uv ensure_ansible clone_repo get_machine_name get_machine_type register_in_inventory write_machine_name set_hostname ensure_sudo ensure_tailscale install_collections setup_bitwarden push_inventory_changes; do
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
