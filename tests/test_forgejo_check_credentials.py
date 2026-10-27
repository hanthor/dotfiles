from test_forgejo_registry_unit import env
from unit_helpers import calls, run_unit


def test_check_blocks_credential_helper_and_registry_login(env):
    result = run_unit("forgejo-registry", env, UNITS_CHECK="1")
    assert result.returncode != 0
    assert "credential helpers may prompt" in result.stdout
    assert calls(env) == ""
