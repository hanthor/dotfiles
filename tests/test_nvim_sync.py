import subprocess
from pathlib import Path

from conftest import REPO, write_stub


SCRIPT = REPO / "home/.chezmoiscripts/run_after_20-nvim-sync.sh"


def run(env):
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)


def calls(home):
    log = Path(home, "nvim-sync-calls")
    return log.read_text().splitlines() if log.exists() else []


def test_sync_runs_on_bootstrap_and_config_change_only(stub_env):
    bindir, env = stub_env
    home = Path(env["HOME"])
    config = home / ".config/nvim"
    config.mkdir(parents=True)
    (config / "init.lua").write_text("return 1\n")
    write_stub(bindir, "git", 'echo clone >> "$HOME/nvim-sync-calls"\nmkdir -p "${@: -1}"\n')
    write_stub(bindir, "nvim", 'echo sync >> "$HOME/nvim-sync-calls"\n')

    assert run(env).returncode == 0
    assert calls(home) == ["clone", "sync"]
    assert run(env).returncode == 0
    assert calls(home) == ["clone", "sync"]

    plugin = config / "lua/plugins/new.lua"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("return {}\n")
    assert run(env).returncode == 0
    assert calls(home) == ["clone", "sync", "sync"]
    plugin.unlink()
    assert run(env).returncode == 0
    assert calls(home) == ["clone", "sync", "sync", "sync"]


def test_failed_sync_is_retried(stub_env):
    bindir, env = stub_env
    home = Path(env["HOME"])
    config = home / ".config/nvim"
    config.mkdir(parents=True)
    (config / "init.lua").write_text("return 1\n")
    lazy = home / ".local/share/nvim/lazy/lazy.nvim"
    lazy.mkdir(parents=True)
    write_stub(bindir, "nvim", 'echo sync >> "$HOME/nvim-sync-calls"\nexit "${NVIM_RC:-0}"\n')

    assert run({**env, "NVIM_RC": "1"}).returncode == 0
    assert run(env).returncode == 0
    assert run(env).returncode == 0
    assert calls(home) == ["sync", "sync"]
