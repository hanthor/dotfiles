import subprocess

import pytest

from conftest import REPO, write_stub


@pytest.mark.parametrize("tags", ["", ",git", "git,", "git,,shell", "not-a-real-tag"])
def test_invalid_selection_never_runs_units(stub_env, tmp_path, tags):
    bindir, env = stub_env
    marker = tmp_path / "mise-called"
    write_stub(bindir, "mise", 'touch "$MARKER"\n')
    env["MARKER"] = str(marker)
    result = subprocess.run(["bash", str(REPO / "scripts/run-units.sh"), "--tags", tags],
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert not marker.exists()
