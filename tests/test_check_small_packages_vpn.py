"""Read-only checks for APK, Termux and Tailscale native units."""
from pathlib import Path

from conftest import write_stub
from test_platform_native_units import platform_env, run_unit, log_lines


def snapshot(path):
    result = {}
    for item in path.rglob('*'):
        rel = str(item.relative_to(path))
        if item.is_symlink():
            result[rel] = ('link', str(item.readlink()))
        elif item.is_file():
            result[rel] = ('file', item.stat().st_mode, item.read_bytes())
        else:
            result[rel] = ('directory', item.stat().st_mode)
    return result


def test_apk_check_reports_packages_services_and_group_without_mutation(platform_env):
    _, system, bindir, env, log = platform_env
    write_stub(bindir, 'apk', '''\
echo "apk $*" >> "$LOG"
[ "$1" = info ] && [ "$#" = 1 ] || exit 99
printf 'chezmoi\nbash\natuin\n'
''')
    write_stub(bindir, 'systemctl', '''\
echo "systemctl $*" >> "$LOG"
case "$1:$2" in
  is-enabled:podman) echo enabled ;;
  is-active:podman) echo active ;;
  is-enabled:podman.socket) echo disabled; exit 1 ;;
  is-active:podman.socket) echo inactive; exit 3 ;;
  *) exit 99 ;;
esac
''')
    write_stub(bindir, 'id', '''\
case "$1" in -nG) echo james ;; -u) echo 1000 ;; -un) echo james ;; *) exit 99 ;; esac
''')
    before = snapshot(system), snapshot(Path(env['HOME']))
    result = run_unit(platform_env, 'apk-packages', UNITS_CHECK='1', TEST_MUSL='1')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ok    APK package chezmoi' in result.stdout
    assert 'WOULD install APK package yq-go' in result.stdout
    assert 'WOULD install APK package atuin-sync' in result.stdout
    assert 'ok    podman enabled and active' in result.stdout
    assert 'WOULD enable and start podman.socket' in result.stdout
    assert 'WOULD add james to podman group' in result.stdout
    assert 'WOULD run npm install -g @bitwarden/cli' in result.stdout
    assert (snapshot(system), snapshot(Path(env['HOME']))) == before
    assert log_lines(log) == ['apk info', 'systemctl is-enabled podman',
                              'systemctl is-active podman', 'systemctl is-enabled podman.socket',
                              'systemctl is-active podman.socket']


def test_apk_check_fails_on_inspection_error(platform_env):
    _, _, bindir, _, log = platform_env
    write_stub(bindir, 'apk', 'echo "apk $*" >> "$LOG"; exit 2\n')
    result = run_unit(platform_env, 'apk-packages', UNITS_CHECK='1', TEST_MUSL='1')
    assert result.returncode != 0
    assert 'Cannot inspect installed APK packages' in result.stderr
    assert not any('MUTATION' in line for line in log_lines(log))
    write_stub(bindir, 'apk', '[ "$1" = info ] || exit 99; echo bash\n')
    write_stub(bindir, 'systemctl', 'exit 1\n')
    result = run_unit(platform_env, 'apk-packages', UNITS_CHECK='1', TEST_MUSL='1')
    assert result.returncode != 0
    assert 'Cannot inspect podman enablement' in result.stderr


def termux_check_stubs(bindir):
    write_stub(bindir, 'dpkg-query', '''\
echo "dpkg-query $*" >> "$LOG"
[ "${DPKG_FAIL:-0}" = 0 ] || exit 2
printf 'installed python\ninstalled openssh:arm64\nconfig-files git\n'
''')
    write_stub(bindir, 'pgrep', '''\
echo "pgrep $*" >> "$LOG"
exit "${PGREP_RC:-1}"
''')
    write_stub(bindir, 'termux-job-scheduler', '''\
echo "scheduler $*" >> "$LOG"
[ "$1" = -p ] || exit 99
[ "${SCHED_FAIL:-0}" = 0 ] || exit 2
[ "${PENDING:-0}" = 0 ] || echo "Pending Job ${PENDING}"
''')
    for name in ('pkg', 'npm', 'sshd'):
        write_stub(bindir, name, 'echo "MUTATION $0 $*" >> "$LOG"; exit 99\n')


def test_termux_check_reports_real_drift_without_mutation(platform_env):
    _, system, bindir, env, log = platform_env
    termux_check_stubs(bindir)
    before = snapshot(system), snapshot(Path(env['HOME']))
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ok    Termux package python' in result.stdout
    assert 'ok    Termux package openssh' in result.stdout
    assert 'WOULD install Termux package git' in result.stdout
    assert 'WOULD create or chmod Termux boot directory' in result.stdout
    assert 'WOULD install or chmod Termux sshd boot script' in result.stdout
    assert 'WOULD start Termux sshd' in result.stdout
    assert 'WOULD schedule Termux sshd keep-alive every 1800000 ms' in result.stdout
    assert 'WOULD run npm install -g @earendil-works/pi-coding-agent' in result.stdout
    assert (snapshot(system), snapshot(Path(env['HOME']))) == before
    assert not any('MUTATION' in line for line in log_lines(log))


def test_termux_check_detects_existing_boot_and_reports_inspection_failures(platform_env):
    root, _, bindir, env, _ = platform_env
    termux_check_stubs(bindir)
    directory = Path(env['HOME']) / '.termux/boot'
    directory.mkdir(parents=True, mode=0o755)
    directory.chmod(0o755)
    script = directory / 'start-sshd'
    script.write_bytes((root / 'units/termux-start-sshd').read_bytes())
    script.chmod(0o755)
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1', PENDING='1', PGREP_RC='0')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ok    Termux boot directory' in result.stdout
    assert 'ok    Termux sshd boot script' in result.stdout
    assert 'ok    Termux sshd running' in result.stdout
    assert 'job exists' in result.stdout
    for failure in ({'DPKG_FAIL': '1'}, {'SCHED_FAIL': '1'}, {'PGREP_RC': '2'}):
        result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1', **failure)
        assert result.returncode != 0
        assert 'Cannot inspect' in result.stderr
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1', PENDING='10')
    assert result.returncode == 0
    assert 'WOULD schedule Termux sshd keep-alive' in result.stdout
    script.unlink()
    script.symlink_to(directory / 'other-script')
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1')
    assert result.returncode != 0 and 'Cannot replace non-regular' in result.stderr
    script.unlink()
    script.write_text('custom script\n')
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1')
    assert result.returncode != 0 and 'Cannot replace customized' in result.stderr
    assert script.read_text() == 'custom script\n'


def tailscale_check_stubs(bindir):
    write_stub(bindir, 'tailscale', '''\
echo "tailscale $*" >> "$LOG"
case "$1:$2" in
  status:--json) [ "${STATUS_FAIL:-0}" = 0 ] || exit 2
    printf '{"BackendState":"%s","secret":"ts-secret-test"}\\n' "${TS_STATE:-Running}" ;;
  debug:prefs) [ "${PREFS_FAIL:-0}" = 0 ] || exit 2
    printf '%s\\n' '{"Hostname":"other","OperatorUser":"other","AdvertiseRoutes":[],"secret":"ts-secret-test"}' ;;
  *) exit 99 ;;
esac
''')
    write_stub(bindir, 'systemctl', '''\
echo "systemctl $*" >> "$LOG"
case "$1" in
  is-active) echo "${RESOLVED_STATE:-inactive}"; [ "${RESOLVED_STATE:-inactive}" = active ] && exit 0 || exit 3 ;;
  *) exit 99 ;;
esac
''')
    for name in ('bw', 'curl', 'sysctl'):
        write_stub(bindir, name, 'echo "MUTATION $0 $*" >> "$LOG"; exit 99\n')


def test_tailscale_check_reports_connected_drift_without_secrets_or_mutation(platform_env):
    root, system, bindir, env, log = platform_env
    tailscale_check_stubs(bindir)
    (root / 'host_vars/laptop.yml').write_text(
        'tailscale_advertise_routes: "192.168.0.0/24"\ntailscale_accept_dns: false\n')
    resolv = system / 'etc/resolv.conf'
    resolv.write_text('nameserver 9.9.9.9\n')
    before = snapshot(system), snapshot(Path(env['HOME']))
    result = run_unit(platform_env, 'tailscale', UNITS_CHECK='1', BW_SESSION='bw-secret-test')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WOULD configure Tailscale resolved configuration' in result.stdout
    assert 'WOULD configure Tailscale sysctl configuration' in result.stdout
    assert 'WOULD configure Tailscale static DNS' in result.stdout
    assert 'WOULD configure Tailscale advertised routes' in result.stdout
    assert 'WOULD set Tailscale hostname' in result.stdout
    assert 'WOULD set Tailscale desktop operator' in result.stdout
    assert 'WOULD configure Tailscale systray' in result.stdout
    assert 'secret-test' not in result.stdout + result.stderr
    assert (snapshot(system), snapshot(Path(env['HOME']))) == before
    assert log_lines(log) == ['tailscale status --json', 'tailscale debug prefs']


def test_tailscale_check_link_and_inspection_errors(platform_env):
    _, system, bindir, env, log = platform_env
    tailscale_check_stubs(bindir)
    resolv = system / 'etc/resolv.conf'
    resolv.write_text('nameserver 9.9.9.9\n')
    before = snapshot(system), snapshot(Path(env['HOME']))
    result = run_unit(platform_env, 'tailscale', UNITS_CHECK='1', RESOLVED_STATE='active')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WOULD configure Tailscale resolver link' in result.stdout
    assert 'WOULD restart systemd-resolved' in result.stdout
    assert (snapshot(system), snapshot(Path(env['HOME']))) == before
    for failure in ({'STATUS_FAIL': '1'}, {'PREFS_FAIL': '1'}):
        result = run_unit(platform_env, 'tailscale', UNITS_CHECK='1', **failure)
        assert result.returncode != 0
        assert 'inspect Tailscale' in result.stdout or 'Cannot inspect Tailscale' in result.stderr


def test_termux_check_rejects_unreadable_overrides_and_skips_non_host(platform_env):
    root, _, bindir, _, log = platform_env
    termux_check_stubs(bindir)
    (root / 'host_vars/phone.yml').write_text('termux_pkgs:\n  - custom\n')
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='phone', TEST_TERMUX='1')
    assert result.returncode != 0
    assert 'yq is required' in result.stderr
    assert not any('MUTATION' in line for line in log_lines(log))
    result = run_unit(platform_env, 'termux-packages', UNITS_CHECK='1', DOTFILES_MACHINE='laptop')
    assert result.returncode == 0
    assert 'SKIPPED: not in termux_hosts' in result.stdout


def test_tailscale_check_missing_binary_and_termux_skip(platform_env):
    _, system, bindir, env, log = platform_env
    write_stub(bindir, 'systemctl', 'echo "systemctl $*" >> "$LOG"; echo inactive; exit 3\n')
    before = snapshot(system), snapshot(Path(env['HOME']))
    result = run_unit(platform_env, 'tailscale', UNITS_CHECK='1', BW_SESSION='bw-secret-test')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WOULD install Tailscale and join tailnet' in result.stdout
    assert 'bw-secret-test' not in result.stdout + result.stderr
    assert (snapshot(system), snapshot(Path(env['HOME']))) == before
    log.unlink()
    result = run_unit(platform_env, 'tailscale', UNITS_CHECK='1', TEST_TERMUX='1')
    assert result.returncode == 0
    assert 'SKIPPED: Android Tailscale' in result.stdout
    assert not log.exists()
