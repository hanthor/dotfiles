"""Shared harness for the bash-unit tests: run units/<name>.sh with stubs and a throwaway HOME."""
import subprocess
from pathlib import Path

from conftest import REPO


def run_unit(name, env, **extra):
    env = {**env, "DOTFILES_DIR": str(REPO), "BREW_PREFIX": "/nonexistent", **extra}
    return subprocess.run(["bash", str(REPO / "units" / f"{name}.sh")], env=env, capture_output=True, text=True)


def calls(env):
    p = Path(env["HOME"], "calls")
    return p.read_text() if p.exists() else ""


UNLOCKED_BW = """\
echo "bw $*" >> "$HOME/calls"
[ "$1 $2" = "unlock --check" ] && exit "${STUB_UNLOCK_RC:-0}"
%s
exit 1
"""
