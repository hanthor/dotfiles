import subprocess
import sys

import pytest

from conftest import REPO
from unit_helpers import run_unit as run_common_unit


# System files live in a private fake /etc. The scripts under test still execute
# their real rendering, comparison, privilege, and service-control logic.
FAKE_SYSTEM = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['FAKE_ROOT'])
log = root / 'calls'
def mapped(arg):
    return str(root / arg.lstrip('/')) if arg.startswith('/etc/') else arg
def record():
    with log.open('a') as f: f.write(name + ' ' + ' '.join(args) + '\n')
if name == 'sudo':
    if args and args[0] == '-n': args.pop(0)
    os.execvp(args[0], args)
if name == 'yq':
    expression = args[-2]
    import yaml
    with open(args[-1]) as f: data = yaml.safe_load(f)
    if expression == '.':
        print(json.dumps(data))
    elif 'children.vps.hosts' in expression:
        print(str(os.environ['MACHINE'] in (data['all']['children']['vps']['hosts'] or {})).lower())
    elif 'web_services' in expression:
        print(json.dumps((data or {}).get('web_services') or []))
    elif 'tailscale_domain' in expression:
        print((data or {}).get('tailscale_domain') or '')
    else: sys.exit(2)
    sys.exit(0)
if name in ('systemctl', 'tailscale', 'loginctl'):
    record()
    if name == 'systemctl' and args[:1] == ['show']:
        print('LoadState=loaded\nActiveState=active\nUnitFileState=enabled')
    if name == 'tailscale' and args[:2] == ['status', '--json']:
        print(json.dumps({'Self': {'DNSName': 'workstation.example.ts.net.'}}))
    if name == 'tailscale' and args[:2] == ['serve', 'status']:
        if os.environ.get('FAIL_SERVE'): sys.exit(1)
        state = root / 'serve'
        custom = root / 'serve_json'
        if custom.exists():
            print(custom.read_text())
        elif state.exists():
            print(json.dumps({'TCP': {'443': {'HTTPS': True}}, 'Web': {
                'workstation.example.ts.net:443': {'Handlers': {'/': {'Proxy': state.read_text()}}}}}))
        else:
            print('{}')
    if name == 'tailscale' and args[:2] == ['serve', '--bg']:
        (root / 'serve').write_text(args[2])
        (root / 'serve_json').unlink(missing_ok=True)
    if name == 'tailscale' and args[:1] == ['cert']:
        pathlib.Path(mapped(args[args.index('--cert-file')+1])).write_text('VALID')
        if os.environ.get('FAIL_CERT'): sys.exit(1)
        pathlib.Path(mapped(args[args.index('--key-file')+1])).write_text('PRIVATE')
    sys.exit(0)
if name == 'openssl':
    path = pathlib.Path(mapped(args[args.index('-in') + 1]))
    if not path.exists(): sys.exit(1)
    if args[0] == 'pkey':
        print('OTHER PUBLIC' if os.environ.get('BAD_KEY') else 'PUBLIC')
        sys.exit(0)
    if path.read_text() != 'VALID': sys.exit(1)
    if '-checkhost' in args:
        hostname = args[args.index('-checkhost') + 1]
        print(f"Hostname {hostname} does {'NOT ' if os.environ.get('BAD_HOST') else ''}match certificate")
    if '-pubkey' in args: print('PUBLIC')
    sys.exit(0)
if name == 'chown': sys.exit(0)
if name == 'stat':
    try:
        mode = pathlib.Path(mapped(args[-1])).stat().st_mode & 0o777
        print(f'{mode:o}:0:0')
    except FileNotFoundError: sys.exit(1)
    sys.exit(0)
if name == 'install':
    if os.environ.get('FAIL_CADDY') and args[-1].endswith('/etc/caddy/Caddyfile'): sys.exit(1)
    output = []
    i = 0
    while i < len(args):
        if args[i] in ('-o', '-g'):
            i += 2
        else:
            output.append(mapped(args[i]))
            i += 1
    os.execv('/usr/bin/install', ['install'] + output)
if name in ('cmp', 'chmod'):
    os.execv('/usr/bin/' + name, [name] + [mapped(x) for x in args])
sys.exit(2)
'''


@pytest.fixture
def fake_system(stub_env, tmp_path):
    bindir, env = stub_env
    root = tmp_path / 'system'
    (root / 'etc/systemd/system').mkdir(parents=True)
    env['FAKE_ROOT'] = str(root)
    for name in ('sudo', 'yq', 'install', 'stat', 'cmp', 'chmod', 'chown', 'systemctl', 'tailscale', 'openssl', 'loginctl'):
        path = bindir / name
        path.write_text(FAKE_SYSTEM)
        path.chmod(0o755)
    repo = tmp_path / 'repo'
    (repo / 'host_vars').mkdir(parents=True)
    (repo / 'group_vars').mkdir()
    (repo / 'group_vars/all.yml').write_text('tailscale_domain: example.ts.net\n')
    (repo / 'inventory.yml').write_text('all:\n  hosts:\n    workstation: {}\n    vm: {}\n  children:\n    vps:\n      hosts:\n        matrix: {}\n        telengana: {}\n        other-vps: {}\n')
    units = repo / 'units'
    units.mkdir()
    for name in ('lib.sh', 'proxy-inventory.py', 'proxy-serve.py', 'osquery_native_inventory.py', 'service-templates.py',
                 'proxy', 'tailscale-cert', 'bst-dashboard', 'kirocrew-sockets.py'):
        (units / name).symlink_to(REPO / 'units' / name)
    for name in ('proxy', 'tailscale-cert'):
        script = (REPO / 'units' / f'{name}.sh').read_text()
        (units / f'{name}.sh').write_text(script.replace('/etc/', str(root / 'etc') + '/'))
    env.update(DOTFILES_DIR=str(repo), DOTFILES_MACHINE='workstation')
    return repo, root, env


def run_unit(name, env, **extra):
    if name not in ('proxy', 'tailscale-cert'):
        return run_common_unit(name, env, **extra)
    repo = extra.get('DOTFILES_DIR', env['DOTFILES_DIR'])
    return subprocess.run(['bash', str(repo + '/units/' + name + '.sh')],
                          env={**env, **extra}, capture_output=True, text=True)


def system_calls(root):
    path = root / 'calls'
    return path.read_text() if path.exists() else ''


def test_proxy_redirects_serve_migration_and_idempotence(fake_system):
    repo, root, env = fake_system
    (repo / 'host_vars/workstation.yml').write_text('web_services:\n  - name: Build / Monitor\n    href: https://example.test/monitor\n')
    (root / 'serve').write_text('http://127.0.0.1:3000')
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    caddy = (root / 'etc/caddy/Caddyfile').read_text()
    assert 'handle /service/build---monitor {' in caddy
    assert 'redir https://example.test/monitor 302' in caddy
    assert 'reverse_proxy 10.88.0.1:8765' in caddy
    assert (root / 'serve').read_text() == 'http://127.0.0.1:9000'
    assert 'systemctl restart caddy.service' in system_calls(root)
    (root / 'calls').unlink()
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'systemctl restart' not in system_calls(root)
    assert 'tailscale serve --bg' not in system_calls(root)


def test_proxy_failure_does_not_skip_other_configuration(fake_system):
    repo, root, env = fake_system
    env['FAIL_CADDY'] = '1'
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo))
    assert result.returncode != 0
    assert 'FAIL  deploy Caddyfile' in result.stdout
    assert (root / 'etc/containers/systemd/caddy.container').exists()
    assert 'systemctl restart' not in system_calls(root)
    assert 'tailscale serve --bg' not in system_calls(root)


def test_certificate_renewal_permissions_timer_and_validity(fake_system):
    repo, root, env = fake_system
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    cert = root / 'etc/ssl/tailscale/cert.pem'
    key = root / 'etc/ssl/tailscale/key.pem'
    assert cert.read_text() == 'VALID' and cert.stat().st_mode & 0o777 == 0o644
    assert key.read_text() == 'PRIVATE' and key.stat().st_mode & 0o777 == 0o640
    service = (root / 'etc/systemd/system/tailscale-cert-renew.service').read_text()
    timer = (root / 'etc/systemd/system/tailscale-cert-renew.timer').read_text()
    assert 'workstation.example.ts.net' in service and 'tailscale-cert-renew.sh' in service
    assert '--min-validity 720h' in (root / 'etc/systemd/system/tailscale-cert-renew.sh').read_text()
    assert 'OnCalendar=weekly' in timer and 'RandomizedDelaySec=1h' in timer and 'Persistent=true' in timer
    assert 'systemctl enable --now tailscale-cert-renew.timer' in system_calls(root)
    (root / 'calls').unlink()
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'tailscale cert ' not in system_calls(root)


def test_certificate_renews_expired_cert_and_uses_host_domain(fake_system):
    repo, root, env = fake_system
    (repo / 'host_vars/workstation.yml').write_text('tailscale_domain: override.ts.net\n')
    cert = root / 'etc/ssl/tailscale/cert.pem'
    cert.parent.mkdir(parents=True)
    cert.write_text('EXPIRED')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert cert.read_text() == 'VALID'
    assert 'workstation.override.ts.net' in system_calls(root)
    assert 'workstation.override.ts.net' in (root / 'etc/systemd/system/tailscale-cert-renew.service').read_text()


@pytest.mark.parametrize('unit', ['proxy', 'tailscale-cert', 'bst-dashboard', 'kirocrew'])
@pytest.mark.parametrize('machine', ['matrix', 'telengana'])
def test_retired_vps_are_untouched(fake_system, unit, machine):
    repo, root, env = fake_system
    env['DOTFILES_MACHINE'] = machine
    result = run_unit(unit, env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert system_calls(root) == ''


@pytest.mark.parametrize('unit', ['proxy', 'tailscale-cert'])
def test_other_vps_and_profile_exclusions(fake_system, unit):
    repo, root, env = fake_system
    env['DOTFILES_MACHINE'] = 'other-vps'
    result = run_unit(unit, env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    env['DOTFILES_MACHINE'] = 'vm'
    (repo / 'host_vars/vm.yml').write_text('machine_profile: vm-test\n')
    result = run_unit(unit, env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert system_calls(root) == ''


@pytest.mark.parametrize('unit,flag', [('proxy', 'skip_proxy'), ('tailscale-cert', 'skip_tailscale_cert')])
def test_per_host_exclusion_prevents_service_changes(fake_system, unit, flag):
    repo, root, env = fake_system
    (repo / 'host_vars/workstation.yml').write_text(f'{flag}: true\n')
    result = run_unit(unit, env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert system_calls(root) == ''


def test_enabled_kirocrew_without_binary_does_not_change_service(fake_system):
    repo, root, env = fake_system
    (repo / 'host_vars/workstation.yml').write_text('kirocrew_enabled: true\n')
    result = run_unit('kirocrew', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0 and 'binary or system service missing' in result.stdout
    assert system_calls(root) == ''


def test_dashboard_template_uses_correct_project_and_service_scope():
    renderer = REPO / 'units/service-templates.py'
    template = REPO / 'units/bst-dashboard/bst-dashboard.service.j2'
    for project, image in [('/var/home/james/dev/kde-linux', 'aurora'), ('/var/home/james/dev/dakota', 'dakota')]:
        result = subprocess.run([sys.executable, str(renderer), 'dashboard', str(template), project, image], capture_output=True, text=True, check=True)
        assert f'--log /var/tmp/{image}-build.log --target oci/{image}.bst --project {project}' in result.stdout
        assert 'WantedBy=default.target' in result.stdout and 'Restart=always' in result.stdout


@pytest.mark.parametrize('address,allowed', [('127.0.0.1:8000', True), ('[::1]:8000', True), ('0.0.0.0:8000', False), ('[::]:8000', False)])
def test_kirocrew_listener_exposure(address, allowed):
    line = f'LISTEN 0 128 {address} 0.0.0.0:* users:(("kirocrew",pid=7,fd=5))\n'
    result = subprocess.run([sys.executable, str(REPO / 'units/kirocrew-sockets.py')], input=line, capture_output=True, text=True)
    assert (result.returncode == 0) is allowed


def test_kirocrew_checks_local_address_not_loopback_peer():
    line = 'LISTEN 0 128 0.0.0.0:8000 127.0.0.1:99 users:(("kirocrew",pid=7,fd=5))\n'
    result = subprocess.run([sys.executable, str(REPO / 'units/kirocrew-sockets.py')], input=line, capture_output=True, text=True)
    assert result.returncode != 0
