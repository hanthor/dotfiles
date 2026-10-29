import importlib.util
import os

import pytest

from conftest import REPO

SPEC = importlib.util.spec_from_file_location('osquery_check', REPO / 'units/osquery-check.py')
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def test_file_and_symlink_checks_only_report_changes(tmp_path, capsys):
    path = tmp_path / 'installed'
    path.write_bytes(b'old')
    path.chmod(0o600)
    link = tmp_path / 'link'
    link.symlink_to('old-target')
    assert check.file_from_bytes(path, b'new', 0o600)
    assert check.symlink(str(link), 'new-target')
    assert path.read_bytes() == b'old'
    assert os.readlink(link) == 'old-target'
    output = capsys.readouterr().out
    assert 'update ' + str(path) in output
    assert 'set symlink ' + str(link) in output


def test_systemd_inspection_reports_drift(monkeypatch, capsys):
    monkeypatch.setattr(check, 'exists', lambda path: True)
    calls = []
    def systemctl(*args):
        calls.append(args)
        return 'LoadState=loaded\nUnitFileState=disabled\nActiveState=inactive\n'
    monkeypatch.setattr(check, 'systemctl', systemctl)
    check.service_state('osqueryd.service')
    assert calls == [('show', '--property=LoadState,UnitFileState,ActiveState', 'osqueryd.service')]
    output = capsys.readouterr().out
    assert 'enable osqueryd.service' in output
    assert 'start osqueryd.service' in output


def test_systemd_incomplete_inspection_fails(monkeypatch):
    monkeypatch.setattr(check, 'exists', lambda path: True)
    monkeypatch.setattr(check, 'systemctl', lambda *args: 'LoadState=loaded\n')
    with pytest.raises(RuntimeError, match='incomplete systemd'):
        check.service_state('osqueryd.service')


def test_disabled_poller_service_is_not_disabled(monkeypatch, capsys):
    monkeypatch.setattr(check, 'exists', lambda path: True)
    monkeypatch.setattr(check, 'systemctl', lambda *args: 'LoadState=loaded\nUnitFileState=enabled\nActiveState=active\n')
    check.service_state('fleet-osquery-poll.service', enabled=False, disable=False)
    output = capsys.readouterr().out
    assert 'stop fleet-osquery-poll.service' in output
    assert 'disable fleet-osquery-poll.service' not in output
