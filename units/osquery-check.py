#!/usr/bin/env python3
"""Inspect the native osquery unit without installing or starting anything."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


def plan(message):
    print('PLAN: ' + message)


def exists(path):
    try:
        path.stat()
        return True
    except FileNotFoundError:
        return False


def metadata(path, mode, uid=0, gid=0, directory=False):
    try:
        info = path.stat()
    except FileNotFoundError:
        plan('create ' + str(path))
        return False
    if (directory and not stat.S_ISDIR(info.st_mode)) or (not directory and not stat.S_ISREG(info.st_mode)):
        plan('replace unexpected file type at ' + str(path))
        return False
    if stat.S_IMODE(info.st_mode) != mode or info.st_uid != uid or info.st_gid != gid:
        plan('correct ownership or permissions of ' + str(path))
    return True

def file_from_bytes(path, content, mode):
    if not metadata(path, mode):
        return True
    if path.read_bytes() != content:
        plan('update ' + str(path))
        return True
    return False


def installed_file(source, destination, mode):
    return file_from_bytes(Path(destination), source.read_bytes(), mode)


def symlink(path, target):
    try:
        actual = os.readlink(path)
    except FileNotFoundError:
        actual = None
    except OSError as error:
        if error.errno != errno.EINVAL:
            raise
        actual = None
    if actual != target:
        plan('set symlink ' + path + ' -> ' + target)
        return True
    return False


def systemctl(*args):
    result = subprocess.run(['systemctl', *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('systemd inspection failed')
    return result.stdout


def service_state(unit, enabled=True, active=True, disable=True):
    # The apply installs these unit files before reloading systemd.
    if not exists(Path('/etc/systemd/system', unit)):
        plan(('enable and start ' if enabled else 'stop ') + unit)
        return
    values = {}
    for line in systemctl('show', '--property=LoadState,UnitFileState,ActiveState', unit).splitlines():
        key, sep, value = line.partition('=')
        if sep:
            values[key] = value
    if not {'LoadState', 'UnitFileState', 'ActiveState'} <= values.keys():
        raise RuntimeError('incomplete systemd unit inspection')
    if values['LoadState'] not in ('loaded', 'not-found'):
        raise RuntimeError('systemd unit has an invalid load state')
    if enabled:
        if values['UnitFileState'] != 'enabled':
            plan('enable ' + unit)
        if active and values['ActiveState'] != 'active':
            plan('start ' + unit)
    else:
        if disable and values['UnitFileState'] in ('enabled', 'enabled-runtime', 'linked', 'linked-runtime', 'alias'):
            plan('disable ' + unit)
        if values['ActiveState'] not in ('inactive', 'failed'):
            plan('stop ' + unit)


def main():
    repo, version, archive, checksum, poller, pollpath, state, home, user, uid, gid, apply_path = sys.argv[1:]
    repo = Path(repo)
    assets = repo / 'units/osquery'
    uid, gid = int(uid), int(gid)
    systemctl('show', '--property=Version', '--value')
    for path in ('/var/cache/fleet-osquery', '/opt/osquery-' + version, '/opt/fleet-osquery'):
        metadata(Path(path), 0o755, directory=True)
    cache = Path('/var/cache/fleet-osquery') / archive
    try:
        with cache.open('rb') as stream:
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(block)
            digest = hasher.hexdigest()
    except FileNotFoundError:
        digest = None
    if digest != checksum:
        if not shutil.which('curl', path=apply_path):
            raise RuntimeError('osquery download requires curl')
        plan('download and verify osquery release ' + version)
    target = Path('/opt/osquery-' + version + '/bin/osqueryd')
    if not exists(target) and not shutil.which('tar', path=apply_path):
        raise RuntimeError('osquery extraction requires tar')
    metadata(target, 0o755)
    symlink('/opt/osquery-' + version + '/bin/osqueryi', 'osqueryd')
    daemon_changed = symlink('/opt/osquery', '/opt/osquery-' + version)
    for path in ('/etc/osquery', '/var/lib/osquery', '/var/log/osquery', '/var/lib/fleet-osquery'):
        metadata(Path(path), 0o700, directory=True)
    installed_file(assets / 'files/fleet-osquery.py', '/opt/fleet-osquery/fleet-osquery', 0o755)
    if installed_file(assets / 'templates/osquery.conf.j2', '/etc/osquery/osquery.conf', 0o600):
        daemon_changed = True
    for unit in ('osqueryd.service', 'fleet-osquery-report.service', 'fleet-osquery-report.timer'):
        if installed_file(assets / ('templates/' + unit + '.j2'), '/etc/systemd/system/' + unit, 0o644) and unit == 'osqueryd.service':
            daemon_changed = True
    if daemon_changed:
        plan('restart osqueryd.service after configuration changes')
    if shutil.which('selinuxenabled'):
        result = subprocess.run(['selinuxenabled'], capture_output=True, timeout=30)
        if result.returncode not in (0, 1):
            raise RuntimeError('SELinux status inspection failed')
        if result.returncode == 0:
            for path in (target, Path('/opt/fleet-osquery/fleet-osquery')):
                if exists(path):
                    result = subprocess.run(['stat', '-c', '%C', str(path)], capture_output=True, text=True, timeout=30)
                    if result.returncode or len(result.stdout.strip().split(':')) < 3:
                        raise RuntimeError('SELinux context inspection failed')
                    if result.stdout.strip().split(':')[2] != 'bin_t':
                        plan('set SELinux bin_t context on ' + str(path))
    plan('reload systemd and validate osquery configuration during apply')
    print('NOTE: configuration validation and release download are not run in check mode')
    service_state('osqueryd.service')
    service_state('fleet-osquery-report.timer')
    if not exists(Path('/var/lib/fleet-osquery/baseline.json')):
        plan('generate osquery baseline')
    plan('run fleet-osquery-report.service')
    if poller != 'true':
        if exists(Path('/etc/systemd/system/fleet-osquery-poll.timer')):
            service_state('fleet-osquery-poll.timer', enabled=False)
            service_state('fleet-osquery-poll.service', enabled=False, disable=False)
        return
    spec = importlib.util.spec_from_file_location('osquery_poller_render', repo / 'units/osquery-poller-render.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    original_path = os.environ.get('PATH', '')
    try:
        os.environ['PATH'] = pollpath
        inventory = renderer.inventory(repo / 'inventory.yml')
    finally:
        os.environ['PATH'] = original_path
    inventory_text = json.dumps(inventory, indent=2, sort_keys=True) + '\n'
    service_text = renderer.service(assets / 'templates/fleet-osquery-poll.service.j2', user, str(gid), home, pollpath, state)
    for path in ('/etc/fleet-osquery', '/opt/fleet-osquery'):
        metadata(Path(path), 0o755, directory=True)
    for source in ('scripts/osquery-fleet.py', 'scripts/online_hosts.py', 'units/osquery_native_inventory.py'):
        installed_file(repo / source, '/opt/fleet-osquery/' + Path(source).name, 0o644)
    file_from_bytes(Path('/etc/fleet-osquery/inventory.yml'), inventory_text.encode(), 0o644)
    metadata(Path(state), 0o700, uid, gid, directory=True)
    file_from_bytes(Path('/etc/systemd/system/fleet-osquery-poll.service'), service_text.encode(), 0o644)
    installed_file(assets / 'templates/fleet-osquery-poll.timer.j2', '/etc/systemd/system/fleet-osquery-poll.timer', 0o644)
    service_state('fleet-osquery-poll.timer')
    plan('run fleet-osquery-poll.service')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print('osquery check: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, TypeError, KeyError, ImportError, subprocess.SubprocessError) as error:
        print('osquery check: inspection failed (' + error.__class__.__name__ + ')', file=sys.stderr)
        sys.exit(1)
