"""scripts/bw-seed-ssh-keys.sh: key discovery, Bitwarden upsert, GitHub
registration and authorized_keys generation, with bw/ssh/gh/chezmoi/hostname
stubbed."""
import json
import shutil
import subprocess

import pytest

from conftest import REPO, write_stub

PRIV = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n-----END OPENSSH PRIVATE KEY-----"


def pub(tag):
    # Distinct 20+ char body per machine so grep -F on it cannot collide.
    return f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA{tag}0123456789 james@{tag}"


# Every call is appended to $STUB_LOG; bodies piped to `bw create/edit` are
# recorded on one line (`bw encode` compacts the JSON) so tests can parse them.
BW_STUB = r'''
echo "bw $*" >> "$STUB_LOG"
case "$1 ${2:-}" in
  "list items") printf '%s' "${STUB_ITEMS:-[]}" ;;
  "encode ") jq -c . ;;
  "create item") echo "CREATE $(cat)" >> "$STUB_LOG" ;;
  "edit item") echo "EDIT $3 $(cat)" >> "$STUB_LOG" ;;
  *) exit 99 ;;
esac
'''

GH_STUB = r'''
echo "gh $*" >> "$STUB_LOG"
case "$*" in
  *"--method POST"*) exit 0 ;;
  "api user/keys "*) printf '%s\n' "${STUB_GH_AUTH:-}" ;;
  "api user/ssh_signing_keys "*) printf '%s\n' "${STUB_GH_SIGN:-}" ;;
  *) exit 99 ;;
esac
'''

SSH_STUB = r'''
echo "ssh $*" >> "$STUB_LOG"
printf '%s' "${STUB_SSH_OUT:-}"
exit "${STUB_SSH_RC:-0}"
'''


@pytest.fixture
def seed(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "bw", BW_STUB)
    write_stub(bindir, "gh", GH_STUB)
    write_stub(bindir, "ssh", SSH_STUB)
    write_stub(bindir, "hostname", 'echo "${STUB_HOSTNAME:-testhost}"')
    write_stub(bindir, "chezmoi", '[ "$1" = source-path ] && echo "$STUB_SRC"')

    # The script hardcodes `eval "$(/home/linuxbrew/.linuxbrew/bin/brew
    # shellenv)"`, which on a runner with linuxbrew prepends its bin dir to
    # PATH and would shadow the stubs. Run a copy without that one line.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("bw-seed-ssh-keys.sh", "bw-item.sh", "bw-unlock.sh"):
        shutil.copy(REPO / "scripts" / name, scripts / name)
    target = scripts / "bw-seed-ssh-keys.sh"
    lines = target.read_text().splitlines(keepends=True)
    kept = [ln for ln in lines if "linuxbrew" not in ln]
    assert len(kept) == len(lines) - 1
    target.write_text("".join(kept))

    src = tmp_path / "chezmoi-src"
    (src / "dot_ssh").mkdir(parents=True)
    log = tmp_path / "calls.log"
    log.touch()
    env.update(STUB_LOG=str(log), STUB_SRC=str(src), BW_SESSION="sess")

    class Ctx:
        pass

    c = Ctx()
    c.env, c.log, c.src, c.home = env, log, src, tmp_path / "home"
    c.authorized = src / "dot_ssh" / "authorized_keys"

    def run(*args):
        return subprocess.run(["bash", str(target), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def put_local_key(name, tag):
        ssh = c.home / ".ssh"
        ssh.mkdir(exist_ok=True)
        (ssh / name).write_text(PRIV)
        (ssh / f"{name}.pub").write_text(pub(tag))

    def calls(prefix):
        return [ln for ln in log.read_text().splitlines() if ln.startswith(prefix)]

    c.run, c.put_local_key, c.calls = run, put_local_key, calls
    return c


# Known script bugs, tracked in hanthor/dotfiles#431. strict=True: once the
# script is fixed these XPASS and fail CI, which is the cue to drop the marks.
empty_collected_keys_aborts = pytest.mark.xfail(
    strict=True, reason="#431: ${#COLLECTED_KEYS[@]} is unbound under set -u when no key was collected")
empty_key_block_aborts = pytest.mark.xfail(
    strict=True, reason="#431: grep -v on empty key block exits 1 under pipefail + set -e")


def payload(line):
    return json.loads(line.split(" ", 1)[1])


def test_unknown_machine_exits_before_any_work(seed):
    r = seed.run("nowhere")
    assert r.returncode == 1
    assert "Unknown machine: nowhere" in r.stdout
    assert "Valid machines:" in r.stdout and "karnataka" in r.stdout
    assert seed.calls("ssh") == [] and seed.calls("CREATE") == []
    assert not seed.authorized.exists()


def test_local_machine_key_creates_item_registers_github_and_writes_authorized_keys(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")
    r = seed.run("goa")
    assert r.returncode == 0, r.stderr

    assert seed.calls("ssh") == []  # local machine is read from disk, not over ssh
    (create,) = seed.calls("CREATE")
    item = payload(create)
    assert item["type"] == 5 and item["name"] == "goa"
    assert item["sshKey"]["privateKey"] == PRIV
    assert item["sshKey"]["publicKey"] == pub("goa")
    assert seed.calls("EDIT") == []

    posts = [c for c in seed.calls("gh") if "--method POST" in c]
    assert len(posts) == 2
    assert any("api user/keys" in p and "title=goa-auth" in p for p in posts)
    assert any("api user/ssh_signing_keys" in p and "title=goa-signing" in p for p in posts)

    text = seed.authorized.read_text().splitlines()
    assert text[0].startswith("# Managed by chezmoi")
    assert text[-2:] == ["# goa", pub("goa")]
    assert "1 machine(s)" in r.stdout


def test_local_machine_falls_back_to_default_key_name(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("id_ed25519", "default")
    r = seed.run("goa")
    assert r.returncode == 0, r.stderr
    assert payload(seed.calls("CREATE")[0])["sshKey"]["publicKey"] == pub("default")


def test_machine_named_key_preferred_over_default(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("id_ed25519", "default")
    seed.put_local_key("goa_id_ed25519", "goa")
    seed.run("goa")
    assert payload(seed.calls("CREATE")[0])["sshKey"]["publicKey"] == pub("goa")


@empty_collected_keys_aborts
def test_local_machine_without_any_key_is_skipped(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    r = seed.run("goa")
    assert r.returncode == 0
    assert "No SSH key found" in r.stdout and "skipping" in r.stdout
    assert seed.calls("CREATE") == [] and seed.calls("gh") == []
    assert not seed.authorized.exists()
    assert "Done." in r.stdout


def test_existing_item_is_edited_by_exact_name_and_type(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")
    # Same name but a login item (type 1), a longer name, then the real SSH key.
    seed.env["STUB_ITEMS"] = json.dumps([
        {"id": "login-id", "name": "goa", "type": 1},
        {"id": "other-id", "name": "goa-old", "type": 5},
        {"id": "right-id", "name": "goa", "type": 5},
    ])
    r = seed.run("goa")
    assert r.returncode == 0, r.stderr
    assert seed.calls("CREATE") == []
    (edit,) = seed.calls("EDIT")
    assert edit.startswith("EDIT right-id ")
    assert payload(edit.split(" ", 1)[1])["sshKey"]["publicKey"] == pub("goa")


def test_github_keys_already_registered_are_not_posted_again(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")
    body = pub("goa").split()[1]
    seed.env["STUB_GH_AUTH"] = f"ssh-ed25519 {body}"
    seed.env["STUB_GH_SIGN"] = f"ssh-ed25519 {body}"
    r = seed.run("goa")
    assert r.returncode == 0, r.stderr
    assert not [c for c in seed.calls("gh") if "--method POST" in c]
    assert "auth key already registered" in r.stdout
    assert "signing key already registered" in r.stdout


def test_only_the_missing_github_key_kind_is_posted(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")
    seed.env["STUB_GH_AUTH"] = "ssh-ed25519 " + pub("goa").split()[1]
    r = seed.run("goa")
    assert r.returncode == 0, r.stderr
    posts = [c for c in seed.calls("gh") if "--method POST" in c]
    assert len(posts) == 1 and "title=goa-signing" in posts[0]


def test_remote_machine_keys_are_parsed_from_ssh_output(seed):
    seed.env["STUB_SSH_OUT"] = (
        f"PRIVKEY_START\n{PRIV}\nPRIVKEY_END\nPUBKEY_START\n{pub('dilli')}\nPUBKEY_END\n"
    )
    r = seed.run("dilli")
    assert r.returncode == 0, r.stderr
    (ssh,) = seed.calls("ssh")
    assert "james@dilli" in ssh and "BatchMode=yes" in ssh
    item = payload(seed.calls("CREATE")[0])
    assert item["name"] == "dilli"
    assert item["sshKey"]["privateKey"] == PRIV
    assert item["sshKey"]["publicKey"] == pub("dilli")


def test_matrix_machine_uses_its_fqdn(seed):
    seed.env["STUB_SSH_OUT"] = "NOKEY\n"
    seed.run("matrix")
    assert "james@matrix.reilly.asia" in seed.calls("ssh")[0]


@empty_collected_keys_aborts
def test_unreachable_remote_is_skipped(seed):
    seed.env["STUB_SSH_RC"] = "255"
    r = seed.run("kanpur")
    assert r.returncode == 0
    assert "SSH unreachable" in r.stdout
    assert seed.calls("CREATE") == [] and not seed.authorized.exists()


@empty_collected_keys_aborts
def test_remote_without_key_is_skipped(seed):
    seed.env["STUB_SSH_OUT"] = "NOKEY\n"
    r = seed.run("kanpur")
    assert r.returncode == 0
    assert "No SSH key found on remote machine" in r.stdout
    assert seed.calls("CREATE") == [] and not seed.authorized.exists()


@empty_key_block_aborts
def test_remote_with_empty_key_blocks_is_skipped(seed):
    seed.env["STUB_SSH_OUT"] = "PRIVKEY_START\nPRIVKEY_END\nPUBKEY_START\nPUBKEY_END\n"
    r = seed.run("kanpur")
    assert r.returncode == 0
    assert "Could not read keys" in r.stdout
    assert seed.calls("CREATE") == []


def test_authorized_keys_lists_machines_sorted_and_skips_failed_ones(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")

    # dilli answers, kanpur does not: the ssh stub keys off the target host.
    write_stub(
        seed.env["PATH"].split(":")[0], "ssh",
        r'''
echo "ssh $*" >> "$STUB_LOG"
case "$*" in
  *james@dilli*) printf 'PRIVKEY_START\n%s\nPRIVKEY_END\nPUBKEY_START\n%s\nPUBKEY_END\n' \
      "$STUB_DILLI_PRIV" "$STUB_DILLI_PUB" ;;
  *) exit 255 ;;
esac
''',
    )
    seed.env.update(STUB_DILLI_PRIV=PRIV, STUB_DILLI_PUB=pub("dilli"))

    r = seed.run("goa", "kanpur", "dilli")
    assert r.returncode == 0, r.stderr
    lines = seed.authorized.read_text().splitlines()
    assert lines[3:] == ["# dilli", pub("dilli"), "# goa", pub("goa")]
    assert "kanpur" not in seed.authorized.read_text()
    assert "2 machine(s)" in r.stdout


def test_authorized_keys_path_falls_back_to_home_dotfiles(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")
    write_stub(seed.env["PATH"].split(":")[0], "chezmoi", "exit 1")
    fallback = seed.home / "dotfiles" / "dot_ssh"
    fallback.mkdir(parents=True)
    r = seed.run("goa")
    assert r.returncode == 0, r.stderr
    assert (fallback / "authorized_keys").read_text().splitlines()[-1] == pub("goa")
    assert not seed.authorized.exists()


def test_authorized_keys_is_rewritten_not_appended(seed):
    seed.env["STUB_HOSTNAME"] = "goa"
    seed.put_local_key("goa_id_ed25519", "goa")
    seed.authorized.write_text("# stale\nssh-ed25519 OLDKEY old@host\n")
    seed.run("goa")
    text = seed.authorized.read_text()
    assert "OLDKEY" not in text and "stale" not in text
