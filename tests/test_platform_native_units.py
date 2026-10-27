"""Behavioral coverage for native platform units; all system paths are sandboxed."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO, write_stub


@pytest.fixture
def platform_env(tmp_path, stub_env):
    bindir, env = stub_env
    # Do not inherit host-specific tools such as yq, sudo, tailscale or pkg.
    for name in ("bash", "dirname", "cat", "sed", "head", "grep", "mktemp", "rm", "chmod",
                 "cmp", "install", "mkdir", "mv", "ln", "readlink", "stat", "sh"):
        target = shutil.which(name)
        assert target
        (bindir / name).symlink_to(target)
    (bindir / "python3").symlink_to(sys.executable)
    root = tmp_path / "repo"
    units = root / "units"
    units.mkdir(parents=True)
    (root / "host_vars").mkdir()
    (root / "group_vars").mkdir()
    (root / "group_vars/all.yml").write_text("tailscale_domain: example.ts.net\n")
    (root / "inventory.yml").write_text(
        "all:\n  children:\n    desktop:\n      hosts:\n        laptop:\n"
        "    termux_hosts:\n      hosts:\n        phone:\n"
    )
    for name in ("apk-packages.sh", "apk-packages.conf", "termux-packages.sh", "termux-packages.conf",
                 "termux-start-sshd", "tailscale.sh", "tailscale-connect.py", "sudo.sh", "sshd.sh",
                 "platform-config.bash", "package-config.bash"):
        (units / name).symlink_to(REPO / "units" / name)
    scripts = root / "scripts"
    scripts.mkdir()
    for name in ("tailnet.py", "inventory_parser.py"):
        (scripts / name).symlink_to(REPO / "scripts" / name)
    lib = (REPO / "units/lib.sh").read_text()
    lib = lib.replace("IS_TERMUX=0; [ -d /data/data/com.termux/files/usr ] && IS_TERMUX=1",
                      'IS_TERMUX="${TEST_TERMUX:-0}"')
    lib = lib.replace("IS_MUSL=0; { [ -e /lib/ld-musl-x86_64.so.1 ] || [ -e /lib/ld-musl-aarch64.so.1 ]; } && IS_MUSL=1",
                      'IS_MUSL="${TEST_MUSL:-0}"')
    (units / "lib.sh").write_text(lib)
    system = tmp_path / "system"
    (system / "etc/ssh/sshd_config.d").mkdir(parents=True)
    (system / "etc/sudoers.d").mkdir(parents=True)
    (system / "etc/os-release").write_text('ID=ubuntu\nID_LIKE=debian\n')
    log = tmp_path / "calls"
    env.update(PATH=str(bindir), DOTFILES_DIR=str(root), DOTFILES_SYSTEM_ROOT=str(system),
               DOTFILES_INVENTORY=str(root / "inventory.yml"), DOTFILES_MACHINE="laptop", USER="james", LOG=str(log),
               BREW_PREFIX=str(tmp_path / "no-brew"), TMPDIR=str(tmp_path))
    write_stub(bindir, "id", '''\
case "$1" in -u) echo 1000 ;; -un) echo james ;; -nG) echo "james podman" ;; *) exit 1 ;; esac
''')
    # Model root ownership while still writing only the temporary test directory.
    (bindir / "stat").unlink()
    write_stub(bindir, "stat", '''\
if [ "$1" = -c ] && [ "$2" = '%a:%u:%g' ]; then
  mode=$(/usr/bin/stat -c %a "$3") || exit 1; echo "$mode:0:0"
else exec /usr/bin/stat "$@"; fi
''')
    write_stub(bindir, "sudo", '''\
[ "$1" = -n ] || exit 1
shift
case "$1" in
 /usr/sbin/visudo) echo visudo >> "$LOG"; exit "${FAIL_VISUDO:-0}" ;;
 /usr/sbin/sshd) echo validate-sshd >> "$LOG"; exit "${FAIL_SSHD:-0}" ;;
 install)
   shift; args=()
   while [ "$#" -gt 0 ]; do
     case "$1" in -o|-g) shift 2 ;; *) args+=("$1"); shift ;; esac
   done
   exec /usr/bin/install "${args[@]}" ;;
 *) exec "$@" ;;
esac
''')
    write_stub(bindir, "systemctl", '''\
echo "systemctl $*" >> "$LOG"
if [ "$1" = is-active ]; then echo "${RESOLVED_STATE:-inactive}"; fi
''')
    write_stub(bindir, "sysctl", 'echo "sysctl $*" >> "$LOG"\n')
    write_stub(bindir, "sleep", 'exit 0\n')
    return root, system, bindir, env, log


def run_unit(fixture, name, **updates):
    root, _, _, env, _ = fixture
    return subprocess.run(["bash", str(root / "units" / f"{name}.sh")],
                          env={**env, **updates}, text=True, capture_output=True)


def log_lines(path):
    return path.read_text().splitlines() if path.exists() else []


def test_sudo_validate_before_replacement_and_cleanup(platform_env):
    root, system, _, _, log = platform_env
    sudoers = system / "etc/sudoers.d"
    (sudoers / "james").write_text("old rule\n")
    (sudoers / "99-james").write_text("another old rule\n")
    failed = run_unit(platform_env, "sudo", FAIL_VISUDO="1")
    assert failed.returncode == 1
    assert (sudoers / "james").read_text() == "old rule\n"
    assert (sudoers / "99-james").exists()
    assert not (sudoers / "zz-james").exists()
    result = run_unit(platform_env, "sudo")
    assert result.returncode == 0, result.stdout + result.stderr
    dest = sudoers / "zz-james"
    assert dest.read_text() == "james ALL=(ALL) NOPASSWD:ALL\n"
    assert dest.stat().st_mode & 0o777 == 0o440
    assert not (sudoers / "james").exists() and not (sudoers / "99-james").exists()
    (root / "host_vars/phone.yml").write_text("skip_sudo: true\n")
    before = log_lines(log)
    skipped = run_unit(platform_env, "sudo", DOTFILES_MACHINE="phone", TEST_TERMUX="1")
    assert skipped.returncode == 0 and log_lines(log) == before


def test_sshd_validates_hardening_and_reloads_once_only_on_change(platform_env):
    root, system, _, _, log = platform_env
    (root / "host_vars/laptop.yml").write_text("sshd_harden: true\n")
    directory = system / "etc/ssh/sshd_config.d"
    bad = run_unit(platform_env, "sshd", FAIL_SSHD="1")
    assert bad.returncode == 1
    assert (directory / "99-bw-env.conf").read_text() == "AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET\n"
    assert not (directory / "10-hardening.conf").exists()
    assert log_lines(log).count("systemctl reload ssh") == 1
    result = run_unit(platform_env, "sshd")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PasswordAuthentication no\n" in (directory / "10-hardening.conf").read_text()
    assert log_lines(log).count("systemctl reload ssh") == 2
    assert run_unit(platform_env, "sshd").returncode == 0
    assert log_lines(log).count("systemctl reload ssh") == 2
    (directory / "99-bw-env.conf").write_text("out of date\n")
    retired = run_unit(platform_env, "sshd", DOTFILES_MACHINE="matrix")
    assert retired.returncode == 0
    assert log_lines(log).count("systemctl reload ssh") == 2


def test_termux_packages_bootstrap_ssh_and_keepalive(platform_env):
    _, system, bindir, _, log = platform_env
    write_stub(bindir, "pkg", 'echo "pkg $*" >> "$LOG"\n')
    write_stub(bindir, "npm", 'echo "npm $*" >> "$LOG"\n')
    write_stub(bindir, "pgrep", 'exit "${SSHD_RUNNING:-1}"\n')
    write_stub(bindir, "sshd", 'echo sshd-start >> "$LOG"\n')
    write_stub(bindir, "termux-job-scheduler", '''\
if [ "$1" = -p ]; then [ "${PENDING:-0}" = 0 ] || echo 'Pending Job 1'; exit 0; fi
echo "job $*" >> "$LOG"
''')
    result = run_unit(platform_env, "termux-packages", DOTFILES_MACHINE="phone", TEST_TERMUX="1")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = log_lines(log)
    assert calls.index("pkg install -y python yq chezmoi") < next(i for i, x in enumerate(calls) if x.startswith("npm "))
    assert "pkg install -y mise" in calls
    assert "npm install -g @earendil-works/pi-coding-agent" in calls
    assert "sshd-start" in calls
    assert any("--job-id 1 --period-ms 1800000 --persisted true" in line for line in calls)
    boot = Path(platform_env[3]["HOME"]) / ".termux/boot/start-sshd"
    assert "termux-wake-lock\nsshd\n" in boot.read_text() and boot.stat().st_mode & 0o777 == 0o755
    log.unlink()
    assert run_unit(platform_env, "termux-packages", DOTFILES_MACHINE="phone", TEST_TERMUX="1",
                    SSHD_RUNNING="0", PENDING="1").returncode == 0
    assert not any(line.startswith("job ") or line == "sshd-start" for line in log_lines(log))
    log.unlink()
    result = run_unit(platform_env, "termux-packages", DOTFILES_MACHINE="laptop")
    assert result.returncode == 0 and not log_lines(log)
    assert system.exists()


def test_termux_unavailable_bootstrap_package_does_not_block_ssh(platform_env):
    _, _, bindir, env, log = platform_env
    write_stub(bindir, "pkg", '''\
echo "pkg $*" >> "$LOG"
case " $* " in *' yq '*) exit 1 ;; esac
''')
    write_stub(bindir, "npm", 'echo "npm $*" >> "$LOG"\n')
    write_stub(bindir, "pgrep", 'exit 1\n')
    write_stub(bindir, "sshd", 'echo sshd-start >> "$LOG"\n')
    write_stub(bindir, "termux-job-scheduler", 'echo "job $*" >> "$LOG"\n')
    result = run_unit(platform_env, "termux-packages", DOTFILES_MACHINE="phone", TEST_TERMUX="1")
    assert result.returncode == 1 and "Termux package unavailable or installation failed: yq" in result.stderr
    assert (Path(env["HOME"]) / ".termux/boot/start-sshd").exists()
    assert "sshd-start" in log_lines(log)
    assert any(line.startswith("job --job-id 1") for line in log_lines(log))


def test_apk_failure_isolation_and_bootstrap(platform_env):
    _, _, bindir, _, log = platform_env
    write_stub(bindir, "apk", '''\
case "$1" in
  info) exit 1 ;;
  update) echo 'apk update' >> "$LOG" ;;
  add) echo "apk $*" >> "$LOG"; case " $* " in *' exa '*) exit 1 ;; esac ;;
esac
''')
    write_stub(bindir, "npm", 'echo "npm $*" >> "$LOG"\n')
    result = run_unit(platform_env, "apk-packages", TEST_MUSL="1")
    assert result.returncode == 1 and "exa" in result.stderr
    calls = log_lines(log)
    assert any("chezmoi yq-go python3 py3-yaml" in line for line in calls)
    assert any("--no-upgrade" in line and " bash" in line for line in calls)
    assert "npm install -g @bitwarden/cli" in calls
    assert any("systemctl enable --now podman.socket" in line for line in calls)
    log.unlink()
    assert run_unit(platform_env, "apk-packages").returncode == 0
    assert not log_lines(log)


def tailscale_stubs(fixture):
    _, _, bindir, env, _ = fixture
    write_stub(bindir, "tailscale", '''\
echo "tailscale $*" >> "$LOG"
if [ "$1" = status ] && [ "${2:-}" != --json ]; then exit "${TS_CONNECTED:-1}"; fi
if [ "$1" = status ] && [ "${2:-}" = --json ]; then
  printf '%s' '{"Self":{"ID":"self-123"}}'
  exit "${TS_CONNECTED:-1}"
fi
if [ "$1" = up ]; then
  [ -z "${BW_SESSION:-}" ] && [ -z "${TS_OAUTH_CLIENT_SECRET:-}" ] || exit 1
  for arg in "$@"; do case "$arg" in --auth-key=file:*)
    file="${arg#--auth-key=file:}"
    /usr/bin/stat -c %a "$file" > "$KEY_MODE"
    /usr/bin/cat "$file" > "$KEY_CAPTURE"
    printf '%s' "$file" > "$KEY_PATH"
  ;; esac; done
  exit "${FAIL_JOIN:-0}"
fi
''')
    write_stub(bindir, "bw", '''\
echo "bw $*" >> "$LOG"
case "$1" in unlock) exit "${BW_LOCKED:-0}" ;; get) printf '%s' '{"login":{"password":"tskey-client-example-sensitive-test"}}' ;; esac
''')
    tmp = Path(env["TMPDIR"])
    env.update(KEY_MODE=str(tmp / "key-mode"), KEY_CAPTURE=str(tmp / "captured-key"), KEY_PATH=str(tmp / "key-path"))
    mock = tmp / "mockpython"
    mock.mkdir()
    (mock / "sitecustomize.py").write_text('''\
import io, json, os, urllib.error, urllib.parse, urllib.request
class Response(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
def open_mock(req, timeout):
    url, method = req.full_url, req.get_method()
    with open(os.environ["LOG"], "a") as f: f.write("api " + method + " " + url + "\\n")
    if url.endswith("/oauth/token"):
        assert method == "POST"
        assert urllib.parse.parse_qs(req.data.decode()) == {
            "client_id": ["example"], "client_secret": ["tskey-client-example-sensitive-test"]}
        if os.environ.get("FAIL_OAUTH") == "1":
            raise urllib.error.HTTPError(url, 401, "secret-bearing response", None,
                                         io.BytesIO(b"tskey-client-example-sensitive-test"))
        return Response(b'{"access_token":"access-sensitive-test"}')
    assert req.get_header("Authorization") == "Bearer access-sensitive-test"
    if method == "GET":
        name = os.environ.get("DEVICE_NAME", "laptop.example.ts.net")
        return Response(json.dumps({"devices": [
            {"name": name, "id": "device-123", "connectedToControl": False},
            {"name": "laptop-4.example.ts.net" if name.startswith("laptop.") else "other-1.example.ts.net",
             "id": "device-suffix", "connectedToControl": False},
            {"name": "laptop-1.example.ts.net", "id": "device-online", "connectedToControl": True},
            {"name": "laptop-2.example.ts.net", "id": "self-123", "connectedToControl": False},
            {"name": "laptop-3.example.ts.net", "id": "device-foreign", "isExternal": True, "connectedToControl": False},
            {"name": "other.example.ts.net", "id": "device-other", "connectedToControl": False},
        ]}).encode())
    if os.environ.get("FAIL_DELETE") == "1":
        raise urllib.error.HTTPError(url, 403, "secret-bearing response", None, None)
    return Response(b"{}")
urllib.request.urlopen = open_mock
''')
    env["PYTHONPATH"] = str(mock)


def test_tailscale_join_keeps_tokens_off_argv_and_no_secrets_skips_vault(platform_env):
    _, _, _, env, log = platform_env
    tailscale_stubs(platform_env)
    no_secrets = run_unit(platform_env, "tailscale", UNITS_NO_SECRETS="1", BW_SESSION="session-sensitive")
    assert no_secrets.returncode == 0, no_secrets.stdout + no_secrets.stderr
    assert "PARTIAL:" in no_secrets.stdout
    assert not any(line.startswith("bw ") or line.startswith("api ") for line in log_lines(log))
    log.unlink()
    locked = run_unit(platform_env, "tailscale", BW_LOCKED="1", BW_SESSION="session-sensitive")
    assert locked.returncode == 0, locked.stdout + locked.stderr
    assert "PARTIAL:" in locked.stdout
    assert not any(line.startswith("api ") or line.startswith("tailscale up") or line.startswith("bw get")
                   for line in log_lines(log))
    log.unlink()
    joined = run_unit(platform_env, "tailscale", BW_SESSION="session-sensitive")
    assert joined.returncode == 0, joined.stdout + joined.stderr
    calls = log_lines(log)
    assert any("api POST https://api.tailscale.com/api/v2/oauth/token" in line for line in calls)
    assert {line.rsplit("/", 1)[-1] for line in calls if line.startswith("api DELETE ")} == {
        "device-123", "device-suffix"}
    assert any("--auth-key=file:" in line and "--advertise-tags=tag:fleet" in line for line in calls)
    assert Path(env["KEY_MODE"]).read_text().strip() == "600"
    assert Path(env["KEY_CAPTURE"]).read_text() == "tskey-client-example-sensitive-test"
    key_path = Path(Path(env["KEY_PATH"]).read_text())
    assert not key_path.exists() and not key_path.parent.exists()
    for secret in ("tskey-client-example-sensitive-test", "access-sensitive-test", "session-sensitive"):
        assert secret not in "\n".join(calls) + joined.stdout + joined.stderr
    traced = subprocess.run(["bash", "-x", str(platform_env[0] / "units/tailscale.sh")],
                            env={**env, "BW_SESSION": "session-sensitive"}, text=True, capture_output=True)
    assert traced.returncode == 0, traced.stdout + traced.stderr
    for secret in ("session-sensitive", "tskey-client-example-sensitive-test", "access-sensitive-test"):
        assert secret not in traced.stdout + traced.stderr


def test_tailscale_resolver_routes_and_retired_service_guard(platform_env):
    root, system, _, _, log = platform_env
    tailscale_stubs(platform_env)
    (root / "host_vars/laptop.yml").write_text(
        'tailscale_advertise_routes: "192.168.0.0/24"\ntailscale_accept_dns: false\ntailscale_operator: james\n'
    )
    dest = system / "etc/resolv.conf"
    external = system / "stub"
    external.write_text("existing resolver\n")
    dest.symlink_to(external)
    result = run_unit(platform_env, "tailscale", TS_CONNECTED="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not dest.is_symlink() and dest.read_text() == "nameserver 1.1.1.1\nnameserver 8.8.8.8\n"
    assert external.read_text() == "existing resolver\n"
    assert any("--advertise-routes=192.168.0.0/24 --accept-dns=false --operator=james" in line for line in log_lines(log))
    for retired in ("matrix", "telengana"):
        for connected in ("0", "1"):
            log.unlink(missing_ok=True)
            result = run_unit(platform_env, "tailscale", DOTFILES_MACHINE=retired,
                              TS_CONNECTED=connected, BW_SESSION="session-sensitive")
            assert result.returncode == 0
            assert not any("restart" in line or "reload" in line or line.startswith(("bw ", "api ", "tailscale up"))
                           for line in log_lines(log))


@pytest.mark.parametrize("failure", ["FAIL_OAUTH", "FAIL_DELETE"])
def test_tailscale_cleanup_failure_warns_and_join_continues(platform_env, failure):
    _, _, _, _, log = platform_env
    tailscale_stubs(platform_env)
    result = run_unit(platform_env, "tailscale", BW_SESSION="session-sensitive", **{failure: "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "warn: Tailscale stale-device cleanup failed; continuing with join" in result.stdout
    assert any(line.startswith("tailscale up") for line in log_lines(log))
    for secret in ("secret-bearing response", "tskey-client-example-sensitive-test", "access-sensitive-test", "session-sensitive"):
        assert secret not in "\n".join(log_lines(log)) + result.stdout + result.stderr


def test_tailscale_other_device_is_not_deleted_and_join_failure_cleans_key(platform_env):
    _, _, _, env, log = platform_env
    tailscale_stubs(platform_env)
    result = run_unit(platform_env, "tailscale", BW_SESSION="x", DEVICE_NAME="other.example.ts.net", FAIL_JOIN="1")
    assert result.returncode == 1
    assert not any("api DELETE" in line for line in log_lines(log))
    assert any(line.startswith("tailscale up") for line in log_lines(log))
    key_path = Path(Path(env["KEY_PATH"]).read_text())
    assert not key_path.exists() and not key_path.parent.exists()


def test_tailscale_resolver_only_points_to_active_stub(platform_env):
    _, system, _, _, log = platform_env
    tailscale_stubs(platform_env)
    dest = system / "etc/resolv.conf"
    dest.write_text("nameserver 9.9.9.9\n")
    inactive = run_unit(platform_env, "tailscale", TS_CONNECTED="0")
    assert inactive.returncode == 0, inactive.stdout + inactive.stderr
    assert dest.read_text() == "nameserver 9.9.9.9\n" and not dest.is_symlink()
    log.unlink()
    active = run_unit(platform_env, "tailscale", TS_CONNECTED="0", RESOLVED_STATE="active")
    assert active.returncode == 0, active.stdout + active.stderr
    assert dest.is_symlink() and os.readlink(dest) == "/run/systemd/resolve/stub-resolv.conf"
    assert log_lines(log).count("systemctl restart systemd-resolved") == 1
    log.unlink()
    repeat = run_unit(platform_env, "tailscale", TS_CONNECTED="0", RESOLVED_STATE="active")
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert "systemctl restart systemd-resolved" not in log_lines(log)
