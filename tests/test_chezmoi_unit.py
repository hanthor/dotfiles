import shutil
import subprocess
from pathlib import Path

from conftest import REPO


def test_missing_chezmoi_fails_with_install_guidance(stub_env):
    bindir, env = stub_env
    # Keep only the utilities used by the shared library, not the host's chezmoi.
    for name in ("cat", "dirname", "hostname"):
        Path(bindir, name).symlink_to(shutil.which(name))
    env = {**env, "PATH": str(bindir), "BREW_PREFIX": "/nonexistent", "DOTFILES_DIR": str(REPO)}

    result = subprocess.run(
        ["/bin/bash", str(REPO / "units/chezmoi.sh")], env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "chezmoi not installed" in result.stdout
    assert any(hint in result.stdout for hint in ("just packages", "pkg install", "apk add"))
