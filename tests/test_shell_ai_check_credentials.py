from conftest import write_stub
from test_shell_ai_unit import env, home, run


def test_check_inspects_modes_without_reading_vault_or_writing_files(env):
    sh = home(env) / ".config/shell/secrets.sh"
    sh.parent.mkdir(parents=True)
    sh.write_text("private-test-value\n")
    sh.chmod(0o644)
    write_stub(env["PATH"].split(":")[0], "bw", 'touch "$HOME/bw-called"; exit 1\n')
    result = run(env, UNITS_CHECK="1")
    assert result.returncode != 0
    assert "mode differs from 0600" in result.stdout
    assert "audit events" in result.stdout
    assert "private-test-value" not in result.stdout + result.stderr
    assert sh.read_text() == "private-test-value\n" and sh.stat().st_mode & 0o777 == 0o644
    assert not (home(env) / "bw-called").exists()
    assert not (home(env) / ".config/fish").exists()


def test_check_with_secrets_disabled_skips_vault(env):
    result = run(env, UNITS_CHECK="1", UNITS_NO_SECRETS="1")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not (home(env) / ".config").exists()
