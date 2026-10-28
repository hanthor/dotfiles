import json
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from test_server_units_check import check_system, run_check
from test_server_service_units import fake_system, run_unit, system_calls


@pytest.mark.parametrize('unit', ['proxy', 'tailscale-cert'])
@pytest.mark.parametrize('check', ['0', '1'])
def test_nested_vps_never_mutated(fake_system, unit, check):
    repo, root, env = fake_system
    (repo / 'inventory.yml').write_text(json.dumps({'all': {'children': {
        'vps': {'children': {'hosted': {'hosts': {'workstation': {}}}}}
    }}}))
    result = run_unit(unit, env, DOTFILES_DIR=str(repo), UNITS_CHECK=check)
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert system_calls(root) == ''
    assert not (root / 'etc/caddy').exists()
    assert not (root / 'etc/ssl/tailscale').exists()

@pytest.mark.parametrize('check', ['0', '1'])
def test_retired_cleanup_skips_nested_vps(check_system, check):
    repo, _, env, old = check_system
    (repo / 'inventory.yml').write_text(json.dumps({'all': {'children': {
        'vps': {'children': {'hosted': {'hosts': {'workstation': {}}}}}
    }}}))
    result = run_check(check_system, 'retired-services', UNITS_CHECK=check)
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert old.read_text() == 'retired\n'
    assert not Path(env['CALLS']).exists()



@pytest.mark.parametrize('unit', ['proxy', 'tailscale-cert'])
def test_unknown_host_fails_before_mutating(fake_system, unit):
    repo, root, env = fake_system
    result = run_unit(unit, env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE='unknown')
    assert result.returncode != 0
    assert system_calls(root) == ''


def test_group_settings_and_host_precedence(fake_system):
    repo, root, env = fake_system
    (repo / 'inventory.yml').write_text(json.dumps({'all': {'children': {
        'desktop': {'hosts': {'workstation': {}}}, 'vps': {'hosts': {}}
    }}}))
    (repo / 'group_vars/desktop.yml').write_text(
        'tailscale_domain: desktop.ts.net\nweb_services:\n'
        '  - name: Group App\n    href: https://group.example/\n')
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'redir https://group.example/ 302' in (root / 'etc/caddy/Caddyfile').read_text()
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'workstation.desktop.ts.net' in (root / 'etc/systemd/system/tailscale-cert-renew.service').read_text()
    (repo / 'host_vars/workstation.yml').write_text('skip_proxy: true\nskip_tailscale_cert: true\n')
    (root / 'calls').unlink()
    for unit in ('proxy', 'tailscale-cert'):
        result = run_unit(unit, env, DOTFILES_DIR=str(repo))
        assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert system_calls(root) == ''


@pytest.mark.parametrize('unit,flag', [('proxy', 'skip_proxy'), ('tailscale-cert', 'skip_tailscale_cert')])
def test_inherited_skip_and_host_override(fake_system, unit, flag):
    repo, root, env = fake_system
    (repo / 'inventory.yml').write_text(json.dumps({'all': {'children': {
        'desktop': {'hosts': {'workstation': {}}}, 'vps': {'hosts': {}}
    }}}))
    (repo / 'group_vars/desktop.yml').write_text(f'{flag}: true\n')
    result = run_unit(unit, env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0 and 'SKIPPED' in result.stdout
    assert system_calls(root) == ''
    (repo / 'host_vars/workstation.yml').write_text(f'{flag}: false\n')
    result = run_unit(unit, env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert system_calls(root)


def test_unreadable_serve_does_not_replace_configuration(fake_system):
    repo, root, env = fake_system
    (root / 'serve').write_text('existing target')
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo), FAIL_SERVE='1')
    assert result.returncode != 0
    assert 'inspect Tailscale serve status' in result.stdout
    assert (root / 'serve').read_text() == 'existing target'
    assert 'tailscale serve --bg' not in system_calls(root)


@pytest.mark.parametrize('other', ['workstation.example.ts.net:8443', 'other.example.ts.net:443'])
def test_unrelated_serve_target_does_not_hide_default_drift(fake_system, other):
    repo, root, env = fake_system
    (root / 'serve_json').write_text(json.dumps({
        'TCP': {'443': {'HTTPS': True}},
        'Web': {
            'workstation.example.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:3000'}}},
            other: {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:9000'}}},
        },
    }))
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (root / 'serve').read_text() == 'http://127.0.0.1:9000'
    assert 'tailscale serve --bg' in system_calls(root)


def test_invalid_serve_json_does_not_replace_configuration(fake_system):
    repo, root, env = fake_system
    (root / 'serve').write_text('existing target')
    (root / 'serve_json').write_text('{broken')
    result = run_unit('proxy', env, DOTFILES_DIR=str(repo))
    assert result.returncode != 0
    assert (root / 'serve').read_text() == 'existing target'
    assert 'tailscale serve --bg' not in system_calls(root)


def test_failed_certificate_request_preserves_existing_pair(fake_system):
    repo, root, env = fake_system
    directory = root / 'etc/ssl/tailscale'
    directory.mkdir(parents=True)
    (directory / 'cert.pem').write_text('EXPIRED')
    (directory / 'key.pem').write_text('ORIGINAL PRIVATE KEY')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo), FAIL_CERT='1')
    assert result.returncode != 0
    assert (directory / 'cert.pem').read_text() == 'EXPIRED'
    assert (directory / 'key.pem').read_text() == 'ORIGINAL PRIVATE KEY'
    assert 'systemctl enable' not in system_calls(root)


def test_valid_certificate_with_missing_key_is_reprovisioned(fake_system):
    repo, root, env = fake_system
    directory = root / 'etc/ssl/tailscale'
    directory.mkdir(parents=True)
    (directory / 'cert.pem').write_text('VALID')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (directory / 'key.pem').read_text() == 'PRIVATE'
    assert 'tailscale cert ' in system_calls(root)


def test_missing_key_check_reports_renewal_without_writing(fake_system):
    repo, root, env = fake_system
    directory = root / 'etc/ssl/tailscale'
    directory.mkdir(parents=True)
    (directory / 'cert.pem').write_text('VALID')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo), UNITS_CHECK='1')
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'private key missing or empty' in result.stdout
    assert not (directory / 'key.pem').exists()
    assert 'tailscale cert ' not in system_calls(root)


@pytest.mark.parametrize('bad', ['BAD_HOST', 'BAD_KEY'])
@pytest.mark.parametrize('check', ['0', '1'])
def test_existing_mismatched_certificate_is_preserved(fake_system, bad, check):
    repo, root, env = fake_system
    directory = root / 'etc/ssl/tailscale'
    directory.mkdir(parents=True)
    (directory / 'cert.pem').write_text('VALID')
    (directory / 'key.pem').write_text('PRIVATE')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo), UNITS_CHECK=check, **{bad: '1'})
    assert result.returncode != 0
    assert 'existing pair preserved' in result.stdout
    assert (directory / 'cert.pem').read_text() == 'VALID'
    assert (directory / 'key.pem').read_text() == 'PRIVATE'
    assert 'tailscale cert ' not in system_calls(root)


@pytest.mark.parametrize('bad', ['BAD_HOST', 'BAD_KEY'])
def test_invalid_issued_pair_does_not_replace_old_pair(fake_system, bad):
    repo, root, env = fake_system
    directory = root / 'etc/ssl/tailscale'
    directory.mkdir(parents=True)
    (directory / 'cert.pem').write_text('EXPIRED')
    (directory / 'key.pem').write_text('OLD KEY')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo), **{bad: '1'})
    assert result.returncode != 0
    assert (directory / 'cert.pem').read_text() == 'EXPIRED'
    assert (directory / 'key.pem').read_text() == 'OLD KEY'


@pytest.mark.parametrize('check', ['0', '1'])
def test_certificate_directory_file_is_preserved(fake_system, check):
    repo, root, env = fake_system
    path = root / 'etc/ssl/tailscale'
    path.parent.mkdir(parents=True)
    path.write_text('user data')
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo), UNITS_CHECK=check)
    assert result.returncode != 0
    assert path.read_text() == 'user data'
    assert system_calls(root) == ''


@pytest.mark.parametrize('path', ['cert.pem', 'key.pem'])
def test_certificate_symlinks_are_not_followed(fake_system, tmp_path, path):
    repo, root, env = fake_system
    directory = root / 'etc/ssl/tailscale'
    directory.mkdir(parents=True)
    target = tmp_path / 'user-owned'
    target.write_text('leave me alone')
    (directory / path).symlink_to(target)
    result = run_unit('tailscale-cert', env, DOTFILES_DIR=str(repo))
    assert result.returncode != 0
    assert target.read_text() == 'leave me alone'
    assert (directory / path).is_symlink()
    assert system_calls(root) == ''


def test_renewal_restores_key_if_certificate_commit_fails(stub_env, tmp_path):
    bindir, env = stub_env
    directory = tmp_path / 'certs'
    directory.mkdir()
    (directory / 'cert.pem').write_text('OLD CERT')
    (directory / 'key.pem').write_text('OLD KEY')
    write_stub(bindir, 'tailscale', '''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --cert-file) printf 'NEW CERT' > "$2"; shift 2 ;;
    --key-file) printf 'NEW KEY' > "$2"; shift 2 ;;
    *) shift ;;
  esac
done
''')
    write_stub(bindir, 'openssl', '''
case "$*" in
  *' -checkhost '*) printf 'Hostname %s does match certificate\\n' "$3" ;;
  *' -pubkey '*|*' -pubout '*) echo PUBLIC ;;
esac
''')
    write_stub(bindir, 'mv', '''
case "${*: -1}" in */cert.pem) exit 1 ;; esac
exec /usr/bin/mv "$@"
''')
    script = REPO / 'units/tailscale-cert/renew.sh'
    result = subprocess.run(['bash', str(script), str(directory), 'host.example.ts.net'],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert (directory / 'cert.pem').read_text() == 'OLD CERT'
    assert (directory / 'key.pem').read_text() == 'OLD KEY'
    assert not list(directory.glob('.renew.????????'))
