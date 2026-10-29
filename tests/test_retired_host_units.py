import subprocess

import pytest

from conftest import REPO, write_stub


@pytest.mark.parametrize("machine", ["matrix", "telengana"])
@pytest.mark.parametrize("unit", sorted((REPO / "units").glob("*.sh")), ids=lambda p: p.stem)
def test_retired_hosts_never_apply_units(stub_env, tmp_path, machine, unit):
    bindir, env = stub_env
    log = tmp_path / "mutations"
    for command in ("sudo", "systemctl", "brew", "flatpak", "tailscale", "apk", "pkg", "chezmoi"):
        write_stub(bindir, command, 'printf "%s\\n" "$0" >> "$MUTATIONS"\nexit 1\n')
    env.update(DOTFILES_MACHINE=machine, DOTFILES_SYSTEM_ROOT=str(tmp_path / "system"), MUTATIONS=str(log))
    result = subprocess.run(["bash", str(unit)], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "retired VPS" in result.stdout
    assert not log.exists()
    assert not (tmp_path / "system").exists()
