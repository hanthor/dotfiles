import os
import shutil
import subprocess

from conftest import REPO, write_stub


def git(*args, cwd=None):
    return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_registration_pr_does_not_change_checkout_or_push_master(tmp_path, stub_env):
    bindir, env = stub_env
    repo, remote = tmp_path / 'repo', tmp_path / 'remote.git'
    git('init', '--initial-branch=master', repo)
    git('config', 'user.name', 'Test', cwd=repo)
    git('config', 'user.email', 'test@example.invalid', cwd=repo)
    (repo / 'scripts').mkdir()
    for name in ('onboard-machine.sh', 'register-machine.py', 'inventory_parser.py'):
        shutil.copy2(REPO / 'scripts' / name, repo / 'scripts' / name)
    (repo / 'inventory.yml').write_text(
        'all:\n  hosts:\n    existing:\n    termux:\n      ansible_port: 8022\n      tailnet_name: pixel-9a\n'
        '  children:\n    desktop:\n      hosts:\n        existing:\n'
        '    server:\n      hosts:\n    vps:\n      hosts:\n    termux_hosts:\n      hosts:\n        termux:\n')
    (repo / 'notes').write_text('committed\n')
    git('add', '.', cwd=repo)
    git('commit', '-m', 'base', cwd=repo)
    git('clone', '--bare', repo, remote)
    git('remote', 'add', 'origin', remote, cwd=repo)
    (repo / 'notes').write_text('staged user work\n')
    git('add', 'notes', cwd=repo)
    with (repo / 'inventory.yml').open('a') as stream:
        stream.write('# uncommitted user work\n')
    before = git('status', '--porcelain', cwd=repo)
    inventory_before = (repo / 'inventory.yml').read_bytes()
    env['GH_STATE'] = str(tmp_path / 'pr-open')
    write_stub(bindir, 'gh', '''
case "$*" in
  'pr list '*) [ ! -f "$GH_STATE" ] || echo 'https://example.invalid/pr/1' ;;
  'pr create '*) touch "$GH_STATE"; echo 'https://example.invalid/pr/1' ;;
  *) exit 2 ;;
esac
''')
    termux = subprocess.run(['bash', str(repo / 'scripts/onboard-machine.sh'), 'termux', 'termux_hosts'],
                            env=env, capture_output=True, text=True)
    assert termux.returncode == 0, termux.stdout + termux.stderr
    assert not (repo / 'scripts/__pycache__').exists()
    new_mobile = subprocess.run(['bash', str(repo / 'scripts/onboard-machine.sh'), 'new-phone', 'termux_hosts'],
                                env=env, capture_output=True, text=True)
    assert new_mobile.returncode != 0
    assert 'individually reviewed inventory PR' in new_mobile.stderr
    assert git('status', '--porcelain', cwd=repo) == before
    assert not os.path.exists(env['GH_STATE'])
    command = ['bash', str(repo / 'scripts/onboard-machine.sh'), 'newhost', 'desktop']
    first = subprocess.run(command, env=env, capture_output=True, text=True)
    assert first.returncode == 3, first.stdout + first.stderr
    assert not (repo / 'scripts/__pycache__').exists()
    assert git('status', '--porcelain', cwd=repo) == before
    assert (repo / 'inventory.yml').read_bytes() == inventory_before
    assert 'newhost:' not in git('--git-dir', remote, 'show', 'master:inventory.yml')
    branch_inventory = git('--git-dir', remote, 'show', 'onboarding/newhost:inventory.yml')
    assert '    newhost:\n' in branch_inventory
    assert '    desktop:\n      hosts:\n        newhost:' in branch_inventory
    assert git('--git-dir', remote, 'show', 'onboarding/newhost:host_vars/newhost.yml') == '---'
    assert git('--git-dir', remote, 'diff', '--name-only', 'master', 'onboarding/newhost') == 'host_vars/newhost.yml\ninventory.yml'

    second = subprocess.run(command, env=env, capture_output=True, text=True)
    assert second.returncode == 3
    assert 'awaits review and merge' in second.stdout
    assert git('status', '--porcelain', cwd=repo) == before

    reviewed = git('--git-dir', remote, 'rev-parse', 'onboarding/newhost')
    git('--git-dir', remote, 'update-ref', 'refs/heads/master', reviewed)
    after_merge = subprocess.run(command, env=env, capture_output=True, text=True)
    assert after_merge.returncode == 0, after_merge.stdout + after_merge.stderr
    assert git('status', '--porcelain', cwd=repo) == before
    wrong_type = subprocess.run(command[:-1] + ['server'], env=env, capture_output=True, text=True)
    assert wrong_type.returncode != 0
    assert 'not in the server group' in wrong_type.stderr
    assert git('status', '--porcelain', cwd=repo) == before


def test_retired_host_is_rejected_before_fetch(stub_env, tmp_path):
    bindir, env = stub_env
    env['CALLS'] = str(tmp_path / 'calls')
    write_stub(bindir, 'git', 'echo called >> "$CALLS"\nexit 1\n')
    result = subprocess.run(['bash', str(REPO / 'scripts/onboard-machine.sh'), 'matrix', 'vps'],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not os.path.exists(env['CALLS'])
