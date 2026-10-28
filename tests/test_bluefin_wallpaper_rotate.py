"""Behavioral coverage for the installed monthly wallpaper script."""
import datetime
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from conftest import REPO, write_stub


SCRIPT = REPO / "units/bluefin/files/bluefin-wallpaper-rotate.py"
spec = importlib.util.spec_from_file_location('bluefin_wallpaper', SCRIPT)
wallpaper_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wallpaper_script)


@pytest.fixture
def wallpaper_env(tmp_path, stub_env):
    bindir, env = stub_env
    home = tmp_path / 'home & 100%'
    home.mkdir()
    env['HOME'] = str(home)
    write_stub(bindir, 'gsettings', '''\
printf '%s\\n' "$3 $4" >> "$HOME/calls"
if [ "${FAIL_KEY:-}" = "$3" ]; then exit 1; fi
''')
    return env, home


def run(env, **overrides):
    return subprocess.run([sys.executable, str(SCRIPT)], env={**env, **overrides},
                          capture_output=True, text=True)


def test_missing_wallpaper_skips_without_changing_settings(wallpaper_env, tmp_path, monkeypatch, capsys):
    _, home = wallpaper_env
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setattr(wallpaper_script, 'SYSTEM_BACKGROUNDS', tmp_path / 'absent')
    runner = mock.Mock()
    monkeypatch.setattr(wallpaper_script.subprocess, 'run', runner)
    assert wallpaper_script.set_wallpaper() == 0
    assert 'not found, skipping rotation' in capsys.readouterr().out
    runner.assert_not_called()


def test_system_wallpaper_is_used_when_no_local_copy(wallpaper_env, tmp_path, monkeypatch):
    _, home = wallpaper_env
    monkeypatch.setenv('HOME', str(home))
    system = tmp_path / 'system-backgrounds'
    system.mkdir()
    name = datetime.datetime.now().strftime('%m') + '-bluefin.xml'
    system_wallpaper = system / name
    system_wallpaper.touch()
    monkeypatch.setattr(wallpaper_script, 'SYSTEM_BACKGROUNDS', system)
    runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(wallpaper_script.subprocess, 'run', runner)

    assert wallpaper_script.set_wallpaper() == 0
    assert [call.args[0][-1] for call in runner.call_args_list] == [system_wallpaper.as_uri()] * 2
    local = home / '.local/share/backgrounds/bluefin' / name
    local.parent.mkdir(parents=True)
    local.touch()
    runner.reset_mock()
    assert wallpaper_script.set_wallpaper() == 0
    assert [call.args[0][-1] for call in runner.call_args_list] == [local.as_uri()] * 2


@pytest.mark.parametrize('failed_key', ['', 'picture-uri', 'picture-uri-dark'])
def test_rotates_both_variants_and_reports_failures(wallpaper_env, failed_key):
    env, home = wallpaper_env
    wallpaper = home / '.local/share/backgrounds/bluefin' / (datetime.datetime.now().strftime('%m') + '-bluefin.xml')
    wallpaper.parent.mkdir(parents=True)
    wallpaper.touch()
    result = run(env, FAIL_KEY=failed_key)
    assert result.returncode == (1 if failed_key else 0)
    uri = wallpaper.as_uri()
    assert '%20' in uri and '%25' in uri
    assert (home / 'calls').read_text().splitlines() == [
        f'picture-uri {uri}', f'picture-uri-dark {uri}',
    ]
