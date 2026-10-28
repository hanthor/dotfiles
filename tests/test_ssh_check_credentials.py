import pytest

from test_ssh_native_units import execute, fleet, pytestmark


@pytest.mark.parametrize("mode", ["ssh-keys", "ssh-mesh"])
def test_check_plans_local_ssh_drift_without_writes_or_secret_access(fleet, mode):
    home = fleet["home"]
    ssh = home / ".ssh"
    ssh.mkdir(mode=0o755)
    ssh.chmod(0o755)
    private = ssh / "id_ed25519"
    private.write_text(fleet["private"])
    private.chmod(0o644)
    public = ssh / "id_ed25519.pub"
    public.write_text(fleet["public"] + "\n")
    result = execute(fleet, mode, UNITS_CHECK="1")
    assert result.returncode != 0
    assert "would set" in result.stdout
    assert fleet["private"] not in result.stdout + result.stderr
    assert private.read_text() == fleet["private"]
    assert private.stat().st_mode & 0o777 == 0o644
    assert ssh.stat().st_mode & 0o777 == 0o755
    assert not (ssh / ".dotfiles-ssh.lock").exists()
    assert not (ssh / "config").exists()
    assert not (ssh / "authorized_keys").exists()
    assert not (ssh / "known_hosts").exists()
    assert not (home / "bw-calls").exists()
    assert not (home / "ssh-calls").exists()
    if mode == "ssh-keys":
        assert "audit events" in result.stdout and "would write" in result.stdout
    else:
        assert "authentication and retries" in result.stdout


def test_missing_identity_check_does_not_read_vault_or_create_directory(fleet):
    result = execute(fleet, "ssh-mesh", UNITS_CHECK="1")
    assert result.returncode != 0 and "audit events" in result.stdout
    assert not (fleet["home"] / ".ssh").exists()
    assert not (fleet["home"] / "bw-calls").exists()
