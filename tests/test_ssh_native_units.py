import base64
import hashlib
import hmac
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen required")


def make_key(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "fixture", "-f", str(path)], check=True)
    return path.read_text(), path.with_suffix(".pub").read_text().strip()


@pytest.fixture
def fleet(stub_env, tmp_path):
    bindir, env = stub_env
    home = Path(env["HOME"])
    data = tmp_path / "data"
    data.mkdir()
    private, public = make_key(tmp_path / "source")
    other_private, other_public = make_key(tmp_path / "other")
    variables = {
        "user_login": "james", "user_email": "james@example.org",
        "machines": {"newhost": {"hostname": "newhost"}, "remote": {"hostname": "peer"},
                     "retired": {"hostname": "retired"}},
        "machine_pubkeys": {"newhost": public, "remote": other_public},
        "ssh_mesh_exclude": [], "extra_authorized_keys": [],
    }
    inventory = {"all": {"hosts": {"newhost": {}, "remote": {"ansible_port": 2222, "ansible_user": "alice", "tailnet_name": "peer-dns"}, "retired": {}},
                         "children": {"vps": {"hosts": {"retired": {}}}}}}
    (data / "all.yml.json").write_text(json.dumps(variables))
    (data / "inventory.yml.json").write_text(json.dumps(inventory))
    (data / "test-fleet-fedora.yml.json").write_text(json.dumps({"machine_profile": "vm-test"}))
    root = tmp_path / "repo"
    (root / "group_vars").mkdir(parents=True)
    (root / "host_vars").mkdir()
    (root / "units").symlink_to(REPO / "units")
    (root / "scripts").symlink_to(REPO / "scripts")
    (root / "group_vars/all.yml").symlink_to(data / "all.yml.json")
    (root / "inventory.yml").symlink_to(data / "inventory.yml.json")
    (root / "host_vars/test-fleet-fedora.yml").symlink_to(data / "test-fleet-fedora.yml.json")
    item = {"id": "item-1", "type": 5, "name": "james@newhost",
            "sshKey": {"privateKey": private, "publicKey": public}}
    (home / "items.json").write_text(json.dumps([item]))
    (home / "item.json").write_text(json.dumps(item))
    (home / "scan-key").write_text(" ".join(other_public.split()[:2]))
    write_stub(bindir, "yq", 'cat "$SSH_FIXTURE/${3##*/}.json"\n')
    write_stub(bindir, "bw", '''printf '%s\\n' "$*" >> "$HOME/bw-calls"
case "$1 $2" in
  'unlock --check') [ "$BW_SESSION" = 'secret-session' ] ;;
  'list items') [ "${BW_LIST_FAIL:-0}" != 1 ] && cat "$HOME/items.json" ;;
  'get item') cat "$HOME/item.json" ;;
  'encode ') base64 | tr -d '\\n' ;;
  'edit item'|'create item') cat > "$HOME/encoded-item" ;;
  *) exit 1 ;;
esac
''')
    write_stub(bindir, "ssh-keyscan", '''printf '%s\\n' "$*" >> "$HOME/scans"
[ "${SCAN_FAIL:-0}" != 1 ] || exit 1
[ "${!#}" = peer ] || exit 1
printf '[peer]:2222 %s\\n' "$(cat "$HOME/scan-key")"
''')
    write_stub(bindir, "ssh", '''printf '%s\\n' "$*" >> "$HOME/ssh-calls"
[ "$1" = -O ] && exit 0
[ "${SSH_FAIL:-0}" = 1 ] && exit 1
if [ ! -e "$HOME/probed" ]; then touch "$HOME/probed"; exit 1; fi
exit 0
''')
    write_stub(bindir, "tailscale", '''printf '%s\\n' '{"Peer":{"one":{"Online":true,"DNSName":"peer-dns.example."},"two":{"Online":true,"DNSName":"retired.example."}}}'
''')
    env.update(DOTFILES_DIR=str(root), DOTFILES_MACHINE="newhost", SSH_FIXTURE=str(data),
               BW_SESSION="secret-session", BREW_PREFIX="/nonexistent")
    return {"env": env, "home": home, "data": data, "private": private, "public": public,
            "other_private": other_private, "other_public": other_public, "variables": variables}


def execute(fleet, mode="ssh-keys", **env):
    return subprocess.run(["bash", str(REPO / f"units/{mode}.sh")], env={**fleet["env"], **env},
                          text=True, capture_output=True, timeout=30)


def test_restores_vault_identity_preserves_user_files_and_idempotency(fleet):
    home = fleet["home"]
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "config").write_text("Host personal\n  User custom\n")
    (ssh / "authorized_keys").write_text("# my unmanaged key\n")
    (ssh / "allowed_signers").write_text("other namespaces=\"git\" ssh-ed25519 untouched\n")
    salt = b"fixed-test-salt"
    digest = hmac.new(salt, b"[peer]:2222", hashlib.sha1).digest()
    hashed = "|1|" + base64.b64encode(salt).decode() + "|" + base64.b64encode(digest).decode()
    (ssh / "known_hosts").write_text(f"{hashed} {fleet['public']}\n[peer]:2222,unmanaged {fleet['public']}\n")
    result = execute(fleet)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (ssh / "id_ed25519").read_text() == fleet["private"]
    assert (ssh / "id_ed25519.pub").read_text().strip() == fleet["public"]
    assert (ssh / "id_ed25519").stat().st_mode & 0o777 == 0o600
    assert (ssh / "authorized_keys").stat().st_mode & 0o777 == 0o600
    assert "Host personal\n  User custom\n" in (ssh / "config").read_text()
    assert "Host remote\n  HostName peer\n  Port 2222\n  User alice\n" in (ssh / "config").read_text()
    assert "# my unmanaged key" in (ssh / "authorized_keys").read_text()
    assert fleet["public"] in (ssh / "authorized_keys").read_text()
    assert "other namespaces=" in (ssh / "allowed_signers").read_text()
    known = (ssh / "known_hosts").read_text()
    assert known == f"{hashed} {fleet['public']}\n[peer]:2222,unmanaged {fleet['public']}\n"
    assert not (home / "scans").exists()
    assert "out-of-band verification" in result.stdout
    calls = (home / "bw-calls").read_text()
    assert "secret-session" not in calls and "secret-session" not in result.stdout + result.stderr
    assert fleet["private"] not in result.stdout + result.stderr
    paths = [ssh / name for name in ("config", "authorized_keys", "allowed_signers", "known_hosts")]
    before = [(p.read_text(), p.stat().st_mtime_ns) for p in paths]
    again = execute(fleet)
    assert again.returncode == 0, again.stdout + again.stderr
    assert [(p.read_text(), p.stat().st_mtime_ns) for p in paths] == before


def test_existing_mismatch_never_overwrites_vault_without_force(fleet):
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(fleet["other_private"])
    (ssh / "id_ed25519").chmod(0o600)
    (ssh / "id_ed25519.pub").write_text(fleet["other_public"] + "\n")
    first = execute(fleet, UNITS_NO_SECRETS="1")
    assert first.returncode == 0, first.stdout + first.stderr
    assert (ssh / "id_ed25519").read_text() == fleet["other_private"]
    local = (ssh / "id_ed25519.pub").read_text().split()[:2]
    assert local != fleet["public"].split()[:2]
    second = execute(fleet)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "vault left unchanged" in second.stdout
    assert not (fleet["home"] / "encoded-item").exists()
    third = execute(fleet, SSH_KEYS_FORCE_PUSH="true")
    assert third.returncode == 0, third.stdout + third.stderr
    item = json.loads(base64.b64decode((fleet["home"] / "encoded-item").read_bytes()))
    assert item["sshKey"]["publicKey"].split() == local
    assert item["sshKey"]["privateKey"] == (ssh / "id_ed25519").read_text()


def test_unavailable_vault_listing_never_creates_identity(fleet):
    result = execute(fleet, BW_LIST_FAIL="1")
    assert result.returncode != 0
    assert "listing failed" in result.stdout
    assert not (fleet["home"] / ".ssh/id_ed25519").exists()
    assert (fleet["home"] / ".ssh/config").exists()
    assert not (fleet["home"] / "encoded-item").exists()


@pytest.mark.parametrize("mode", ["ssh-keys", "ssh-mesh"])
@pytest.mark.parametrize("disabled", [True, False])
def test_missing_identity_waits_for_unlocked_vault(fleet, mode, disabled):
    kwargs = {"UNITS_NO_SECRETS": "1"} if disabled else {"BW_SESSION": "locked-session"}
    first = execute(fleet, mode, **kwargs)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "PARTIAL: SSH identity deferred" in first.stdout
    ssh = fleet["home"] / ".ssh"
    assert not (ssh / "id_ed25519").exists()
    assert not (ssh / "id_ed25519.pub").exists()
    assert not (fleet["home"] / "encoded-item").exists()
    assert not (fleet["home"] / "ssh-calls").exists()
    if mode == "ssh-mesh":
        assert fleet["other_public"] in (ssh / "authorized_keys").read_text()
    second = execute(fleet, mode)
    assert second.returncode == 0, second.stdout + second.stderr
    assert (ssh / "id_ed25519").read_text() == fleet["private"]


def test_mesh_uses_vault_key_merges_git_keys_and_excludes_vps(fleet):
    home = fleet["home"]
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "authorized_keys").write_text("# unmanaged\n")
    result = execute(fleet, "ssh-mesh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (ssh / "id_ed25519").read_text() == fleet["private"]
    keys = (ssh / "authorized_keys").read_text()
    assert "# unmanaged" in keys and fleet["other_public"] in keys
    calls = (home / "ssh-calls").read_text()
    assert calls.count("alice@peer true") == 2
    assert "-O exit -p 2222 alice@peer" in calls
    assert "retired" not in calls
    assert "StrictHostKeyChecking=yes" in calls
    assert not (ssh / "known_hosts").exists()
    assert not (home / "scans").exists()


def test_mesh_authentication_failure_preserves_known_hosts_and_reports_failure(fleet):
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(fleet["private"])
    (ssh / "id_ed25519").chmod(0o600)
    (ssh / "id_ed25519.pub").write_text(fleet["public"] + "\n")
    old = "[peer]:2222 " + fleet["public"] + "\n"
    (ssh / "known_hosts").write_text(old)
    result = execute(fleet, "ssh-mesh", UNITS_NO_SECRETS="1", SSH_FAIL="1")
    assert result.returncode != 0
    assert "SSH mesh broken to: remote" in result.stdout
    assert (ssh / "known_hosts").read_text() == old


def test_profile_skip_does_not_create_key_or_contact_vault(fleet):
    result = execute(fleet, "ssh-mesh", DOTFILES_MACHINE="test-fleet-fedora")
    assert result.returncode == 0
    assert "SKIPPED" in result.stdout
    assert not (fleet["home"] / ".ssh/id_ed25519").exists()
    assert not (fleet["home"] / "bw-calls").exists()


def test_parallel_units_restore_one_identity_and_preserve_both_key_sources(fleet):
    env = fleet["env"]
    units = [subprocess.Popen(["bash", str(REPO / f"units/{name}.sh")], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for name in ("ssh-keys", "ssh-mesh")]
    for unit in units:
        stdout, stderr = unit.communicate(timeout=30)
        assert unit.returncode == 0, stdout + stderr
    ssh = fleet["home"] / ".ssh"
    assert (ssh / "id_ed25519").read_text() == fleet["private"]
    authorized = (ssh / "authorized_keys").read_text()
    assert fleet["public"] in authorized and fleet["other_public"] in authorized


def test_missing_vault_item_is_created_and_authorized_immediately(fleet):
    home = fleet["home"]
    (home / "items.json").write_text("[]")
    result = execute(fleet)
    assert result.returncode == 0, result.stdout + result.stderr
    item = json.loads(base64.b64decode((home / "encoded-item").read_bytes()))
    assert item["name"] == "james@newhost" and item["type"] == 5
    local = (home / ".ssh/id_ed25519.pub").read_text().split()[:2]
    assert item["sshKey"]["publicKey"].split() == local
    assert item["sshKey"]["publicKey"] in (home / ".ssh/authorized_keys").read_text()


def test_partial_vault_never_shrinks_keys_without_explicit_force(fleet):
    home = fleet["home"]
    own = json.loads((home / "item.json").read_text())
    remote = {"id": "remote-1", "name": "james@remote", "sshKey": {"publicKey": fleet["other_public"]}}
    (home / "items.json").write_text(json.dumps([own, remote]))
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "authorized_keys").write_text('# user-managed access\n')
    first = execute(fleet)
    assert first.returncode == 0, first.stdout + first.stderr
    (home / "items.json").write_text(json.dumps([own]))
    second = execute(fleet)
    assert second.returncode == 0, second.stdout + second.stderr
    assert fleet["other_public"] in (ssh / "authorized_keys").read_text()
    forced = execute(fleet, SSH_KEYS_FORCE_AUTHORIZED="true")
    assert forced.returncode == 0, forced.stdout + forced.stderr
    content = (ssh / "authorized_keys").read_text()
    assert fleet["other_public"] not in content
    assert "# user-managed access" in content and fleet["public"] in content


def test_mesh_does_not_consult_vault_when_identity_exists(fleet):
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(fleet["private"])
    (ssh / "id_ed25519").chmod(0o600)
    (ssh / "id_ed25519.pub").write_text(fleet["public"] + "\n")
    result = execute(fleet, "ssh-mesh", BW_LIST_FAIL="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (fleet["home"] / "bw-calls").exists()


def test_invalid_vault_key_pair_is_not_installed_or_logged(fleet):
    home = fleet["home"]
    item = json.loads((home / "item.json").read_text())
    item["sshKey"]["publicKey"] = fleet["other_public"]
    (home / "item.json").write_text(json.dumps(item))
    (home / "items.json").write_text(json.dumps([item]))
    result = execute(fleet)
    assert result.returncode != 0
    assert "does not match" in result.stdout
    assert not (home / ".ssh/id_ed25519").exists()
    assert fleet["private"] not in result.stdout + result.stderr


@pytest.mark.parametrize("mismatch", [False, True])
def test_restores_encrypted_vault_identity_without_prompting(fleet, tmp_path, mismatch):
    source = tmp_path / "encrypted-vault-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "test-passphrase", "-f", str(source)],
                   check=True, capture_output=True)
    private = source.read_text()
    public = source.with_suffix(".pub").read_text().strip()
    home = fleet["home"]
    item = json.loads((home / "item.json").read_text())
    item["sshKey"] = {"privateKey": private, "publicKey": fleet["other_public"] if mismatch else public}
    (home / "item.json").write_text(json.dumps(item))
    (home / "items.json").write_text(json.dumps([item]))
    result = execute(fleet)
    if mismatch:
        assert result.returncode != 0
        assert not (home / ".ssh/id_ed25519").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert (home / ".ssh/id_ed25519").read_text() == private
        assert (home / ".ssh/id_ed25519.pub").read_text().strip() == public
    assert not (home / "encoded-item").exists()
    assert private not in result.stdout + result.stderr


@pytest.mark.parametrize("contents,parsed,valid", [
    ("---\n", "null", True),
    ("# onboarding\n--- # empty\n", "null", True),
    ("- unexpected\n", '["unexpected"]', False),
    ("null\n", "null", False),
])
def test_host_vars_accepts_empty_document_but_rejects_nonmapping(fleet, tmp_path, contents, parsed, valid):
    root = tmp_path / "fleet-root"
    (root / "host_vars").mkdir(parents=True)
    (root / "group_vars").mkdir()
    (root / "group_vars/all.yml").symlink_to(fleet["data"] / "all.yml.json")
    (root / "inventory.yml").symlink_to(fleet["data"] / "inventory.yml.json")
    (root / "host_vars/newhost.yml").write_text(contents)
    (fleet["data"] / "newhost.yml.json").write_text(parsed)
    script = '''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ssh_fleet", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.Fleet()
'''
    result = subprocess.run(["python3", "-c", script, str(REPO / "units/ssh-fleet.py")],
                            env={**fleet["env"], "DOTFILES_DIR": str(root)}, capture_output=True, text=True)
    assert (result.returncode == 0) is valid
    if not valid:
        assert "invalid YAML mapping" in result.stderr


@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("check", [False, True])
def test_encrypted_identity_never_prompts_or_overwrites_vault(fleet, mismatch, check):
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    private = ssh / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "test-passphrase", "-f", str(private)],
                   check=True, capture_output=True)
    public = ssh / "id_ed25519.pub"
    if mismatch:
        public.write_text(fleet["other_public"] + "\n")
    private_before, public_before = private.read_bytes(), public.read_bytes()
    result = execute(fleet, SSH_KEYS_FORCE_PUSH="true", **({"UNITS_CHECK": "1"} if check else {}))
    if mismatch:
        assert result.returncode != 0
        assert "local SSH private and public keys do not match" in result.stdout
    else:
        assert "encrypted SSH key envelope matches" in result.stdout
        if not check:
            assert result.returncode == 0, result.stdout + result.stderr
            assert "Bitwarden key left unchanged" in result.stdout
    assert private.read_bytes() == private_before and public.read_bytes() == public_before
    assert not (fleet["home"] / "encoded-item").exists()
    assert "test-passphrase" not in result.stdout + result.stderr
    assert private_before.decode() not in result.stdout + result.stderr


def test_encrypted_identity_without_public_key_is_not_replaced(fleet):
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    private = ssh / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "test-passphrase", "-f", str(private)],
                   check=True, capture_output=True)
    before = private.read_bytes()
    public = ssh / "id_ed25519.pub"
    public.unlink()
    result = execute(fleet, SSH_KEYS_FORCE_PUSH="true")
    assert result.returncode != 0
    assert "requires an existing public key" in result.stdout
    assert private.read_bytes() == before
    assert not public.exists()
    assert not (fleet["home"] / "encoded-item").exists()
    assert before.decode() not in result.stdout + result.stderr


@pytest.mark.parametrize("check", [False, True])
def test_ssh_unit_never_scans_unverified_host_keys(fleet, check):
    variables = fleet["variables"]
    variables["machines"].pop("retired")
    variables["machines"].update({"matrix": {"hostname": "matrix.reilly.asia"},
                                  "telengana": {"hostname": "telengana"}})
    (fleet["data"] / "all.yml.json").write_text(json.dumps(variables))
    result = execute(fleet, UNITS_NO_SECRETS="1", UNITS_CHECK="1" if check else "0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (fleet["home"] / "scans").exists()
    assert "out-of-band verification" in result.stdout


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("excluded", [False, True])
def test_host_specific_mesh_exclusions_override_group_defaults(fleet, tmp_path, check, excluded):
    root = tmp_path / "host-override"
    root.mkdir()
    (root / "units").symlink_to(REPO / "units")
    (root / "scripts").symlink_to(REPO / "scripts")
    (root / "group_vars").mkdir()
    (root / "group_vars/all.yml").symlink_to(fleet["data"] / "all.yml.json")
    (root / "inventory.yml").symlink_to(fleet["data"] / "inventory.yml.json")
    (root / "host_vars").mkdir()
    host_exclude = ["remote"] if excluded else []
    fleet["variables"]["ssh_mesh_exclude"] = [] if excluded else ["remote"]
    (fleet["data"] / "all.yml.json").write_text(json.dumps(fleet["variables"]))
    (root / "host_vars/newhost.yml").write_text(json.dumps({"ssh_mesh_exclude": host_exclude}))
    (fleet["data"] / "newhost.yml.json").write_text(json.dumps({"ssh_mesh_exclude": host_exclude}))
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(fleet["private"])
    (ssh / "id_ed25519").chmod(0o600)
    (ssh / "id_ed25519.pub").write_text(fleet["public"] + "\n")
    result = execute(fleet, "ssh-mesh", DOTFILES_DIR=str(root), UNITS_NO_SECRETS="1",
                     UNITS_CHECK="1" if check else "0")
    if excluded:
        assert result.returncode == 0, result.stdout + result.stderr
        assert not (fleet["home"] / "ssh-calls").exists()
    elif check:
        assert result.returncode != 0 and "online SSH mesh targets: remote" in result.stdout
        assert not (fleet["home"] / "ssh-calls").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "alice@peer" in (fleet["home"] / "ssh-calls").read_text()


def test_group_force_push_allows_explicit_identity_rotation(fleet):
    fleet["variables"]["ssh_keys_force_push"] = True
    (fleet["data"] / "all.yml.json").write_text(json.dumps(fleet["variables"]))
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(fleet["other_private"])
    (ssh / "id_ed25519").chmod(0o600)
    (ssh / "id_ed25519.pub").write_text(fleet["other_public"] + "\n")
    result = execute(fleet)
    assert result.returncode == 0, result.stdout + result.stderr
    item = json.loads(base64.b64decode((fleet["home"] / "encoded-item").read_bytes()))
    assert item["sshKey"]["publicKey"].split() == fleet["other_public"].split()[:2]


def test_group_force_authorized_removes_only_managed_obsolete_keys(fleet):
    fleet["variables"]["ssh_keys_force_authorized"] = True
    (fleet["data"] / "all.yml.json").write_text(json.dumps(fleet["variables"]))
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "authorized_keys").write_text(
        "# user-managed access\n# BEGIN dotfiles Bitwarden SSH keys\n"
        + fleet["other_public"] + "\n# END dotfiles Bitwarden SSH keys\n"
    )
    result = execute(fleet)
    assert result.returncode == 0, result.stdout + result.stderr
    content = (ssh / "authorized_keys").read_text()
    assert fleet["other_public"] not in content
    assert "# user-managed access" in content and fleet["public"] in content


def test_nested_inventory_group_vars_and_vps_are_respected(fleet):
    inventory = {"all": {"hosts": {"newhost": {}}, "children": {
        "fleet": {"vars": {"ansible_port": 2022, "tailnet_name": "peer-dns"},
                  "children": {"workstations": {"hosts": {"remote": {}}}}},
        "vps": {"children": {"old_servers": {"hosts": {"retired": {}}}}},
    }}}
    (fleet["data"] / "inventory.yml.json").write_text(json.dumps(inventory))
    root = Path(fleet["env"]["DOTFILES_DIR"])
    (root / "group_vars/fleet.yml").write_text(json.dumps({"ansible_user": "group-user", "ansible_port": 2222}))
    (root / "host_vars/remote.yml").write_text(json.dumps({"ansible_user": "host-user"}))
    result = execute(fleet)
    assert result.returncode == 0, result.stdout + result.stderr
    config = (fleet["home"] / ".ssh/config").read_text()
    assert "Host remote\n  HostName peer\n  Port 2222\n  User host-user\n" in config
    result = execute(fleet, "ssh-mesh")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (fleet["home"] / "ssh-calls").read_text()
    assert "host-user@peer" in calls and "retired" not in calls


def test_managed_ssh_config_requires_verified_host_keys(fleet):
    ssh_client = shutil.which("ssh")
    if not ssh_client:
        pytest.skip("OpenSSH client required")
    result = execute(fleet, UNITS_NO_SECRETS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    config = fleet["home"] / ".ssh/config"
    effective = subprocess.run([ssh_client, "-G", "-F", str(config), "remote"],
                               text=True, capture_output=True, check=True)
    assert "stricthostkeychecking true" in effective.stdout.splitlines()


def test_committed_key_revocation_preserves_unowned_and_vault_keys(fleet):
    home = fleet["home"]
    ssh = home / ".ssh"
    ssh.mkdir()
    legacy = fleet["other_public"] + " legacy-user-entry"
    (ssh / "authorized_keys").write_text(legacy + "\n")
    first = execute(fleet, "ssh-mesh")
    assert first.returncode == 0, first.stdout + first.stderr
    contents = (ssh / "authorized_keys").read_text()
    assert "# BEGIN dotfiles committed SSH keys" in contents
    assert fleet["other_public"] + "\n" in contents
    vault_key = {"id": "remote-1", "name": "james@remote", "sshKey": {"publicKey": fleet["other_public"]}}
    (home / "items.json").write_text(json.dumps([json.loads((home / "item.json").read_text()), vault_key]))
    assert execute(fleet).returncode == 0
    del fleet["variables"]["machine_pubkeys"]["remote"]
    (fleet["data"] / "all.yml.json").write_text(json.dumps(fleet["variables"]))
    assert execute(fleet, "ssh-mesh").returncode == 0
    assert fleet["other_public"] + "\n" in (ssh / "authorized_keys").read_text()
    assert execute(fleet, "ssh-mesh", SSH_KEYS_FORCE_AUTHORIZED="true").returncode == 0
    contents = (ssh / "authorized_keys").read_text()
    git_block = contents.split("# BEGIN dotfiles committed SSH keys\n", 1)[1].split("# END dotfiles committed SSH keys", 1)[0]
    vault_block = contents.split("# BEGIN dotfiles Bitwarden SSH keys\n", 1)[1].split("# END dotfiles Bitwarden SSH keys", 1)[0]
    assert fleet["other_public"] not in git_block
    assert fleet["other_public"] in vault_block and legacy in contents
    own = json.loads((home / "item.json").read_text())
    (home / "items.json").write_text(json.dumps([own]))
    assert execute(fleet, SSH_KEYS_FORCE_AUTHORIZED="true").returncode == 0
    contents = (ssh / "authorized_keys").read_text()
    assert legacy in contents
    vault_block = contents.split("# BEGIN dotfiles Bitwarden SSH keys\n", 1)[1].split("# END dotfiles Bitwarden SSH keys", 1)[0]
    assert fleet["other_public"] not in vault_block


@pytest.mark.parametrize("pinned", [False, True])
def test_mesh_rejects_unverified_and_changed_host_keys(fleet, tmp_path, pinned):
    paramiko = pytest.importorskip("paramiko")
    import socket
    import threading

    real_ssh = shutil.which("ssh")
    if not real_ssh:
        pytest.skip("OpenSSH client required")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(3)
    listener.settimeout(20)
    port = listener.getsockname()[1]
    attempts = []

    class Server(paramiko.ServerInterface):
        def check_auth_none(self, username):
            attempts.append(username)
            return paramiko.AUTH_FAILED

        def check_auth_publickey(self, username, key):
            attempts.append(username)
            return paramiko.AUTH_FAILED

    def serve():
        for _ in range(2):
            try:
                client, _ = listener.accept()
                transport = paramiko.Transport(client)
                transport.add_server_key(paramiko.Ed25519Key.from_private_key_file(str(tmp_path / "other")))
                try:
                    transport.start_server(server=Server())
                    transport.accept(5)
                except (EOFError, OSError, paramiko.SSHException):
                    pass
                finally:
                    transport.close()
            except OSError:
                break

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    ssh = fleet["home"] / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(fleet["private"])
    (ssh / "id_ed25519").chmod(0o600)
    (ssh / "id_ed25519.pub").write_text(fleet["public"] + "\n")
    known = ssh / "known_hosts"
    original = f"[127.0.0.1]:{port} {fleet['public']}\n" if pinned else ""
    if pinned:
        known.write_text(original)
    (ssh / "config").write_text(f"Host *\n  UserKnownHostsFile {known}\n  GlobalKnownHostsFile /dev/null\n")
    fleet["variables"]["machines"]["remote"]["hostname"] = "127.0.0.1"
    (fleet["data"] / "all.yml.json").write_text(json.dumps(fleet["variables"]))
    inventory = json.loads((fleet["data"] / "inventory.yml.json").read_text())
    inventory["all"]["hosts"]["remote"]["ansible_port"] = port
    (fleet["data"] / "inventory.yml.json").write_text(json.dumps(inventory))
    bindir = Path(fleet["env"]["PATH"].split(":", 1)[0])
    write_stub(bindir, "ssh", 'exec "$REAL_SSH" -F "$HOME/.ssh/config" "$@"\n')
    try:
        result = execute(fleet, "ssh-mesh", UNITS_NO_SECRETS="1", REAL_SSH=real_ssh)
    finally:
        listener.close()
        thread.join(timeout=3)
    assert result.returncode != 0 and "SSH mesh broken to: remote" in result.stdout
    assert not attempts
    assert known.read_text() == original if pinned else not known.exists()
    assert not (fleet["home"] / "scans").exists()
