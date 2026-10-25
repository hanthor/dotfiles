import shutil
import subprocess

import pytest
import yaml

from conftest import REPO, write_stub

pytestmark = pytest.mark.skipif(shutil.which("yq") is None, reason="yq not installed")

BROKER_URL = "http://100.78.73.8:8765"

OMP_STUB = """\
case "$1 $2" in
  "--version "*) echo omp/0 ;;
  "plugin list") echo '["omp-kiro-provider"]' ;;
  "auth-broker status") echo "OK stub" ;;
esac
exit 0
"""


def run_unit(env):
    env = {**env, "DOTFILES_DIR": str(REPO), "UNITS_NO_SECRETS": "1"}
    return subprocess.run(
        ["bash", str(REPO / "units/omp.sh")], env=env, capture_output=True, text=True
    )


def broker_url(home):
    cfg = yaml.safe_load((home / ".omp/agent/config.yml").read_text())
    return cfg["auth"]["broker"]["url"]


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "omp", OMP_STUB)
    return env


def snapshot(home):
    paths = [".omp/agent/config.yml", ".config/omp/kiro.json", ".local/bin/omp-route"]
    return {p: (home / p).read_bytes() for p in paths}


def test_fresh_home_is_configured(env, tmp_path):
    home = tmp_path / "home"
    r = run_unit(env)
    assert r.returncode == 0, r.stdout + r.stderr
    # himachal regression: ~/.config did not exist and the role aborted.
    assert (home / ".config/omp/kiro.json").is_file()
    assert (home / ".local/bin/omp-route").stat().st_mode & 0o111
    assert broker_url(home) == BROKER_URL
    assert (home / ".omp/agent/config.yml").stat().st_mode & 0o777 == 0o600
    assert "PARTIAL:" in r.stdout


def test_second_run_changes_nothing(env, tmp_path):
    home = tmp_path / "home"
    assert run_unit(env).returncode == 0
    before = snapshot(home)
    assert run_unit(env).returncode == 0
    assert snapshot(home) == before


def test_failing_step_does_not_stop_later_steps(env, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").write_text("not a directory")
    r = run_unit(env)
    assert r.returncode == 1
    assert "FAIL  claude skill links" in r.stdout
    assert (home / ".config/omp/kiro.json").is_file()
    assert broker_url(home) == BROKER_URL
