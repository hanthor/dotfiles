from pathlib import Path

from test_github_unit import env
from unit_helpers import calls, run_unit


def test_check_known_hosts_without_github_or_vault_calls(env):
    ssh = Path(env["HOME"], ".ssh")
    ssh.chmod(0o755)
    result = run_unit("github", env, UNITS_CHECK="1")
    assert result.returncode != 0
    assert "would set" in result.stdout and "would add GitHub host key" in result.stdout
    assert "keyring" in result.stdout and "audit events" in result.stdout
    assert not (ssh / "known_hosts").exists()
    assert ssh.stat().st_mode & 0o777 == 0o755 and calls(env) == ""


def test_check_no_secrets_only_inspects_known_hosts(env):
    result = run_unit("github", env, UNITS_CHECK="1", UNITS_NO_SECRETS="1")
    assert result.returncode == 0 and "would add GitHub host key" in result.stdout
    assert calls(env) == "" and not Path(env["HOME"], ".ssh/known_hosts").exists()
