from types import SimpleNamespace

import pytest

from test_fleet_facts_native import config_repo, fake_host, fleet


def test_check_plans_publication_without_github_write(tmp_path, monkeypatch, capsys):
    repo = config_repo(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(fleet.sys, 'argv', ['fleet-facts.py', str(repo), 'laptop', '0', '--check'])
    monkeypatch.setattr(fleet, 'config', lambda *args: (True, 'hanthor/dotfiles', 'fleet-facts', ['desktop']))
    monkeypatch.setattr(fleet, 'collect', lambda *args, **kwargs: {'private': 'SECRET'})
    calls = []
    def command(args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(fleet, 'command', command)
    monkeypatch.setattr(fleet.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not publish'))
    assert fleet.main() == 0
    assert calls == [['gh', 'auth', 'status']]
    output = capsys.readouterr().out
    assert 'PLAN: publish facts/laptop.json' in output
    assert 'SECRET' not in output


def test_check_fails_if_auth_inspection_fails(tmp_path, monkeypatch):
    repo = config_repo(tmp_path)
    monkeypatch.setattr(fleet.sys, 'argv', ['fleet-facts.py', str(repo), 'laptop', '0', '--check'])
    monkeypatch.setattr(fleet, 'command', lambda args: None)
    monkeypatch.setattr(fleet, 'collect', lambda *args: pytest.fail('must not collect'))
    with pytest.raises(RuntimeError, match='gh authentication unavailable'):
        fleet.main()


def test_check_respects_publish_opt_out(tmp_path, monkeypatch, capsys):
    repo = config_repo(tmp_path)
    (repo / 'host_vars/laptop.yml').write_text('fleet_facts_publish: false\n')
    monkeypatch.setattr(fleet.sys, 'argv', ['fleet-facts.py', str(repo), 'laptop', '0', '--check'])
    monkeypatch.setattr(fleet, 'command', lambda args: pytest.fail('must not invoke gh'))
    assert fleet.main() == 0
    assert 'SKIPPED' in capsys.readouterr().out


def test_strict_collection_reports_failed_gpu_inspection(fake_host):
    root, home, _ = fake_host
    with pytest.raises(RuntimeError, match='GPU inventory inspection failed'):
        fleet.collect('laptop', [], home, root=root, run=lambda args: None, strict=True)
