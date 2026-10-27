import stat
from pathlib import Path

from test_kube_unit import env
from unit_helpers import calls, run_unit


def test_check_reports_local_drift_without_accessing_vault(env):
    home = Path(env["HOME"])
    config = home / ".kube/config"
    config.parent.mkdir()
    config.write_text("test-private-config\n")
    config.chmod(0o644)
    result = run_unit("kube", env, UNITS_CHECK="1")
    assert result.returncode != 0
    assert "mode differs from 0600" in result.stdout and "audit events" in result.stdout
    assert "test-private-config" not in result.stdout + result.stderr
    assert config.read_text() == "test-private-config\n" and stat.S_IMODE(config.stat().st_mode) == 0o644
    assert not (home / ".talos").exists()
    assert calls(env) == ""


def test_check_without_secrets_has_no_vault_or_filesystem_effects(env):
    result = run_unit("kube", env, UNITS_CHECK="1", UNITS_NO_SECRETS="1")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert calls(env) == "" and not Path(env["HOME"], ".kube").exists()
