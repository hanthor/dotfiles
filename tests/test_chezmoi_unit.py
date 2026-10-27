import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


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


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("failure", ["missing", "malformed", "command"])
def test_unknown_desktop_never_runs_chezmoi(stub_env, tmp_path, check, failure):
    bindir, env = stub_env
    root = tmp_path / "repo"
    (root / "host_vars").mkdir(parents=True)
    log = tmp_path / "chezmoi.log"
    write_stub(bindir, "chezmoi", 'echo "$*" >> "$LOG"\n')
    write_stub(bindir, "yq", '''\
if [ "$1" = --version ]; then echo 'github.com/mikefarah/yq'; exit 0; fi
if [ "$FAILURE" = command ]; then exit 1; fi
if [ "$FAILURE" = malformed ]; then echo '!!seq'; exit 0; fi
exit 1
''')
    env.update(DOTFILES_DIR=str(root), DOTFILES_MACHINE="unknown", LOG=str(log),
               FAILURE=failure, UNITS_CHECK="1" if check else "0")
    result = subprocess.run(["bash", str(REPO / "units/chezmoi.sh")],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "FAIL: cannot" in result.stdout
    assert not log.exists()


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("override,expected", [("true", "1"), ("false", "0")])
def test_explicit_desktop_override_needs_no_inventory(stub_env, tmp_path, check, override, expected):
    bindir, env = stub_env
    log = tmp_path / "chezmoi.log"
    write_stub(bindir, "chezmoi", 'echo "$DOTFILES_IS_DESKTOP $*" >> "$LOG"\n')
    env.update(DOTFILES_DIR=str(tmp_path), DOTFILES_MACHINE="unknown", LOG=str(log),
               DOTFILES_IS_DESKTOP=override, UNITS_CHECK="1" if check else "0")
    result = subprocess.run(["bash", str(REPO / "units/chezmoi.sh")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().startswith(expected + " ")
    assert (" status" if check else " apply --init") in log.read_text()


def test_host_desktop_override_without_inventory(stub_env, tmp_path):
    bindir, env = stub_env
    (tmp_path / "host_vars").mkdir()
    (tmp_path / "host_vars/laptop.yml").write_text("is_desktop: true\n")
    log = tmp_path / "chezmoi.log"
    write_stub(bindir, "chezmoi", 'echo "$DOTFILES_IS_DESKTOP" >> "$LOG"\n')
    env.update(DOTFILES_DIR=str(tmp_path), DOTFILES_MACHINE="laptop", LOG=str(log))
    result = subprocess.run(["bash", str(REPO / "units/chezmoi.sh")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text() == "1\n"


@pytest.mark.parametrize("membership", ["true", "false", "invalid"])
def test_inventory_membership_must_be_boolean(stub_env, tmp_path, membership):
    bindir, env = stub_env
    (tmp_path / "host_vars").mkdir()
    log = tmp_path / "chezmoi.log"
    write_stub(bindir, "chezmoi", 'echo "$DOTFILES_IS_DESKTOP" >> "$LOG"\n')
    write_stub(bindir, "yq", '''\
if [ "$1" = --version ]; then echo 'github.com/mikefarah/yq'; exit 0; fi
case "$*" in *'| tag'*) echo '!!map' ;; *) echo "$MEMBERSHIP" ;; esac
''')
    env.update(DOTFILES_DIR=str(tmp_path), DOTFILES_MACHINE="laptop", LOG=str(log),
               MEMBERSHIP=membership)
    result = subprocess.run(["bash", str(REPO / "units/chezmoi.sh")],
                            env=env, capture_output=True, text=True)
    if membership == "invalid":
        assert result.returncode != 0
        assert not log.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert log.read_text() == ("1\n" if membership == "true" else "0\n")
