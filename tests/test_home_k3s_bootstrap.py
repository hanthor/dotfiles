import subprocess

from conftest import REPO, write_stub


SCRIPT = REPO / "home-k3s" / "install-host.sh"


def run_install(tmp_path, stub_env, *, matches, active):
    bindir, env = stub_env
    write_stub(bindir, "id", "echo 0\n")
    write_stub(bindir, "hostname", "echo karnataka\n")
    write_stub(bindir, "uname", "echo x86_64\n")
    write_stub(bindir, "ip", "echo '1: tailscale0    inet 100.66.158.127/32 scope global tailscale0'\n")
    write_stub(
        bindir,
        "sha256sum",
        '''cat >/dev/null
if [ "${1:-}" = --check ]; then exit "$MATCH_EXIT"; fi
exit 0
''',
    )
    write_stub(
        bindir,
        "systemctl",
        '''echo "systemctl $*" >> "$INSTALL_LOG"
if [ "${1:-}" = is-active ]; then exit "$ACTIVE_EXIT"; fi
''',
    )
    write_stub(bindir, "install", 'echo "install $*" >> "$INSTALL_LOG"\n')
    write_stub(
        bindir,
        "curl",
        '''echo "curl $*" >> "$INSTALL_LOG"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; echo asset > "$1"; break; fi
  shift
done
''',
    )
    log = tmp_path / "install.log"
    env.update(INSTALL_LOG=str(log), MATCH_EXIT="0" if matches else "1", ACTIVE_EXIT="0" if active else "3")
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
    return result, log.read_text().splitlines() if log.exists() else []


def test_matching_binary_does_not_download_or_replace_running_k3s(tmp_path, stub_env):
    result, calls = run_install(tmp_path, stub_env, matches=True, active=True)
    assert result.returncode == 0, result.stderr
    assert not any(call.startswith("curl ") for call in calls)
    assert not any(call.startswith("install ") and call.endswith(" /var/usrlocal/bin/k3s") for call in calls)
    assert not any("restart" in call for call in calls)


def test_different_binary_is_not_replaced_while_running(tmp_path, stub_env):
    result, calls = run_install(tmp_path, stub_env, matches=False, active=True)
    assert result.returncode != 0
    assert "Refusing to replace" in result.stderr
    assert calls == ["systemctl is-active --quiet k3s.service"]


