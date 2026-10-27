import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


def run(unit, env, **extra):
    return subprocess.run(
        ["bash", str(REPO / "units" / f"{unit}.sh")],
        env={**env, "DOTFILES_DIR": str(REPO), "BREW_PREFIX": "/nonexistent",
             "UNITS_CHECK": "1", "DOTFILES_IS_DESKTOP": "1", **extra},
        capture_output=True, text=True,
    )


def test_fonts_check_reports_install_without_creating_directory(stub_env):
    bindir, env = stub_env
    for command in ("curl", "unzip", "fc-cache"):
        write_stub(bindir, command, 'echo "unexpected mutation" >&2; exit 99\n')
    result = run("fonts", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "create font directory" in result.stdout
    assert "install JetBrains" in result.stdout
    assert list(Path(env["HOME"]).iterdir()) == []


def test_fonts_check_detects_existing_font_and_nondirectory_error(stub_env):
    _, env = stub_env
    root = Path(env["HOME"])
    font = root / ".local/share/fonts/JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"font")
    result = run("fonts", env)
    assert result.returncode == 0
    assert "already installed" in result.stdout
    font.unlink()
    font.parent.rmdir()
    font.parent.parent.rmdir()
    font.parent.parent.write_text("blocked")
    result = run("fonts", env)
    assert result.returncode != 0
    assert "not a directory" in result.stdout
    assert font.parent.parent.read_text() == "blocked"


def test_fonts_check_handles_nondesktop_and_inventory_errors(stub_env):
    bindir, env = stub_env
    result = run("fonts", env, DOTFILES_IS_DESKTOP="0")
    assert result.returncode == 0
    assert "create font directory" in result.stdout
    assert "not a desktop" in result.stdout
    assert "download" not in result.stdout
    write_stub(bindir, "yq", "exit 5\n")
    result = run("fonts", env, DOTFILES_IS_DESKTOP="", DOTFILES_MACHINE="unknown-test-host")
    assert result.returncode != 0
    assert "cannot inspect desktop membership" in result.stdout
    assert list(Path(env["HOME"]).iterdir()) == []


def test_chezmoi_check_uses_dry_status_without_exposing_file_contents(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "chezmoi", '''\
case " $* " in
  *" --init "*) echo 'unsafe init' >&2; exit 99 ;;
  *" --dry-run "*" status "*) printf ' M .gitconfig\\n R .chezmoiscripts/example\\n' ;;
  *) echo 'unsafe invocation' >&2; exit 99 ;;
esac
''')
    target = Path(env["HOME"], ".gitconfig")
    target.write_text("private token\n")
    result = run("chezmoi", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ".gitconfig" in result.stdout and " R " in result.stdout
    assert "private token" not in result.stdout + result.stderr
    assert target.read_text() == "private token\n"
    assert sorted(p.name for p in Path(env["HOME"]).iterdir()) == [".gitconfig"]


def test_chezmoi_check_propagates_inspection_error(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "chezmoi", "exit 7\n")
    result = run("chezmoi", env)
    assert result.returncode != 0
    assert "status inspection failed" in result.stdout
    assert list(Path(env["HOME"]).iterdir()) == []


def test_unsupported_atuin_and_omp_checks_fail_before_running_them(stub_env):
    bindir, env = stub_env
    for command in ("atuin", "omp"):
        write_stub(bindir, command, 'echo "unsafe invocation" >&2; exit 99\n')
    for unit in ("atuin", "omp"):
        result = run(unit, env)
        assert result.returncode != 0
        assert "cannot be inspected safely" in result.stdout
        assert "unsafe invocation" not in result.stderr
        assert list(Path(env["HOME"]).iterdir()) == []


def home_snapshot(home):
    result = {}
    for path in home.rglob("*"):
        stat = path.lstat()
        if path.is_symlink():
            contents = ("link", os.readlink(path))
        elif path.is_file():
            contents = ("file", path.read_bytes())
        else:
            contents = ("directory",)
        result[str(path.relative_to(home))] = (stat.st_mode, stat.st_mtime_ns, contents)
    return result


@pytest.mark.parametrize("existing_state", [False, True])
def test_real_chezmoi_check_preserves_absent_or_existing_state(stub_env, existing_state):
    binary = shutil.which("chezmoi")
    if not binary:
        pytest.skip("chezmoi not installed")
    _, env = stub_env
    home = Path(env["HOME"])
    env = {**env, "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_CACHE_HOME": str(home / ".cache"),
           "XDG_DATA_HOME": str(home / ".local/share"),
           "DOTFILES_MACHINE": "test-host", "DOTFILES_IS_DESKTOP": "1"}
    if existing_state:
        setup = subprocess.run(
            [binary, "--source", str(REPO), "--force", "--no-tty", "apply", "--init", "--exclude=scripts"],
            env=env, capture_output=True, text=True,
        )
        assert setup.returncode == 0, setup.stdout + setup.stderr
        assert (home / ".config/chezmoi/chezmoistate.boltdb").is_file()
    before = home_snapshot(home)
    result = run("chezmoi", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert home_snapshot(home) == before
