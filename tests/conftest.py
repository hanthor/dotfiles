import os
import stat
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def write_stub(bindir, name, body):
    """Drop an executable bash stub `name` into bindir."""
    p = Path(bindir) / name
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


@pytest.fixture
def stub_env(tmp_path):
    """(bindir, env): stubs in bindir shadow the real PATH; HOME is a tmp dir."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("BW_")}
    env.update(PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(home))
    return bindir, env
