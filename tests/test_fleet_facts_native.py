import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import REPO

SPEC = importlib.util.spec_from_file_location('fleet_facts_native', REPO / 'units/fleet-facts.py')
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


def put(root, path, text):
    dest = root / path.lstrip('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)


@pytest.fixture
def fake_host(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    home = tmp_path / 'home'
    home.mkdir()
    put(root, '/etc/os-release', 'NAME="Example Linux"\nVERSION_ID="42"\nVERSION_CODENAME=stable\n')
    put(root, '/proc/cpuinfo', 'processor : 0\nmodel name : Public CPU 123\nprocessor : 1\nmodel name : Public CPU 123\n')
    put(root, '/proc/meminfo', 'MemTotal:       16777216 kB\n')
    put(root, '/proc/uptime', '172800.0 0.0\n')
    put(root, '/sys/devices/virtual/dmi/id/sys_vendor', 'Example Vendor\n')
    put(root, '/sys/devices/virtual/dmi/id/product_name', 'System Product Name\n')
    put(root, '/sys/firmware/devicetree/base/model', 'Example Device\0')
    put(root, '/sys/devices/virtual/dmi/id/chassis_type', '9\n')
    monkeypatch.setattr(fleet.platform, 'release', lambda: '6.9.0')
    monkeypatch.setattr(fleet.platform, 'machine', lambda: 'x86_64')
    def run(args):
        if args[0] == 'lspci':
            return SimpleNamespace(returncode=0, stdout='00:02.0 "VGA compatible controller" "Acme" "Graphics"\n00:03.0 "VGA compatible controller" "Acme" "Device 1111"\n')
        return SimpleNamespace(returncode=1, stdout='')
    return root, home, run


def test_collect_public_schema_and_filtered_last_apply(fake_host):
    root, home, run = fake_host
    last = home / '.cache/dotfiles/last-apply.json'
    last.parent.mkdir(parents=True)
    last.write_text(json.dumps({'timestamp': '2026-10-27T01:02:03Z', 'exit_code': 0, 'hostname': 'PRIVATE-HOST', 'branch': 'SECRET-BRANCH', 'token': 'SECRET-TOKEN'}))
    doc = fleet.collect('laptop', ['desktop'], home, root=root, run=run)
    assert doc['schema'] == 1 and doc['host'] == 'laptop' and doc['groups'] == ['desktop']
    assert doc['os'] == {'name': 'Example Linux', 'version': '42', 'codename': 'stable', 'kernel': '6.9.0'}
    assert doc['hardware'] == {'vendor': 'Example Vendor', 'model': 'Example Device', 'form_factor': 'Laptop', 'arch': 'x86_64', 'cpu': 'Public CPU 123', 'cpu_threads': 2, 'gpus': ['Acme Graphics'], 'memory_gb': 16.0}
    assert doc['uptime_days'] == 2.0 and doc['last_apply'] == {'at': '2026-10-27T01:02:03Z', 'ok': True}
    assert 'PRIVATE-HOST' not in json.dumps(doc) and 'SECRET-' not in json.dumps(doc)


def test_sensitive_hardware_values_are_never_published(fake_host, capsys):
    root, home, run = fake_host
    put(root, '/sys/firmware/devicetree/base/model', 'serial number PRIVATE-1234\n')
    put(root, '/sys/devices/virtual/dmi/id/product_name', '192.168.1.4\n')
    put(root, '/sys/devices/virtual/dmi/id/sys_vendor', 'token=SECRET-TOKEN\n')
    doc = fleet.collect('laptop', [], home, root=root, run=run)
    content = json.dumps(doc)
    assert doc['hardware']['model'] == '' and doc['hardware']['vendor'] == ''
    assert 'PRIVATE-1234' not in content and '192.168.1.4' not in content and 'SECRET-TOKEN' not in content
    assert 'omitted' in capsys.readouterr().err


def test_required_collection_failure_is_not_faked(fake_host):
    root, home, run = fake_host
    (root / 'proc/meminfo').unlink()
    with pytest.raises(RuntimeError, match='required OS or hardware data unavailable'):
        fleet.collect('laptop', [], home, root=root, run=run)


def test_termux_android_model_and_release(fake_host):
    root, home, _ = fake_host
    def run(args):
        if args == ['getprop', 'ro.build.version.release']:
            return SimpleNamespace(returncode=0, stdout='16\n')
        if args == ['getprop', 'ro.product.model']:
            return SimpleNamespace(returncode=0, stdout='Pixel 9a\n')
        return SimpleNamespace(returncode=1, stdout='')
    doc = fleet.collect('termux', ['termux_hosts'], home, termux=True, root=root, run=run)
    assert doc['os']['name'] == 'Android' and doc['os']['version'] == '16'
    assert doc['hardware']['model'] == 'Pixel 9a'


def config_repo(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'units').mkdir(parents=True)
    (repo / 'units/fleet-facts').symlink_to(REPO / 'units/fleet-facts')
    (repo / 'group_vars').mkdir()
    (repo / 'host_vars').mkdir()
    (repo / 'inventory.yml').write_text('all:\n  hosts:\n    laptop: {}\n  children:\n    desktop:\n      hosts:\n        laptop: {}\n')
    return repo


def test_group_defaults_and_host_override(tmp_path):
    repo = config_repo(tmp_path)
    (repo / 'group_vars/desktop.yml').write_text('fleet_facts_publish: false\nfleet_facts_branch: desktop-facts\n')
    assert fleet.config(repo, 'laptop') == (False, 'hanthor/dotfiles', 'desktop-facts', ['desktop'])
    (repo / 'host_vars/laptop.yml').write_text('fleet_facts_publish: true\nfleet_facts_repo: example/fleet\n')
    assert fleet.config(repo, 'laptop') == (True, 'example/fleet', 'desktop-facts', ['desktop'])


def test_github_contents_write_and_nonfatal_failure(tmp_path, monkeypatch, capsys):
    repo = config_repo(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(fleet.sys, 'argv', ['fleet-facts.py', str(repo), 'laptop', '0'])
    doc = {'schema': 1, 'host': 'laptop', 'hardware': {'model': 'Public'}}
    monkeypatch.setattr(fleet, 'collect', lambda *args: doc)
    def command(args):
        if args[:2] == ['gh', 'auth']:
            return SimpleNamespace(returncode=0, stdout='')
        assert args == ['gh', 'api', 'repos/hanthor/dotfiles/contents/facts/laptop.json?ref=fleet-facts', '--jq', '.sha']
        return SimpleNamespace(returncode=0, stdout='abc123\n')
    monkeypatch.setattr(fleet, 'command', command)
    sent = []
    def put_request(args, **kwargs):
        sent.append((args, json.loads(kwargs['input'])))
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(fleet.subprocess, 'run', put_request)
    assert fleet.main() == 0
    args, body = sent[0]
    assert args[:5] == ['gh', 'api', '-X', 'PUT', 'repos/hanthor/dotfiles/contents/facts/laptop.json']
    assert body['branch'] == 'fleet-facts' and body['sha'] == 'abc123'
    assert json.loads(base64.b64decode(body['content'])) == doc
    assert 'could not publish' in capsys.readouterr().err


def test_opt_out_and_missing_auth_never_collect(tmp_path, monkeypatch):
    repo = config_repo(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(fleet.sys, 'argv', ['fleet-facts.py', str(repo), 'laptop', '0'])
    monkeypatch.setattr(fleet, 'collect', lambda *args: pytest.fail('must not collect'))
    (repo / 'host_vars/laptop.yml').write_text('fleet_facts_publish: false\n')
    monkeypatch.setattr(fleet, 'command', lambda args: pytest.fail('must not invoke gh for opt-out'))
    assert fleet.main() == 0
    (repo / 'host_vars/laptop.yml').write_text('fleet_facts_publish: true\n')
    monkeypatch.setattr(fleet, 'command', lambda args: None)
    assert fleet.main() == 0
