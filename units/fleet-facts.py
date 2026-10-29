#!/usr/bin/env python3
"""Collect only public fleet metadata and publish it with the gh contents API."""
import base64
import datetime as dt
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

PLACEHOLDERS = {'', 'NA', 'None', 'System Product Name', 'To Be Filled By O.E.M.', 'Default string', 'Not Specified'}
SENSITIVE = re.compile(
    r'(?i)(?:\b(?:serial|password|token|secret|credential|api[_ -]?key)\b|'
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b|'
    r'\b(?:[0-9a-f]{1,4}:){2,}[0-9a-f]{0,4}\b|\b[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}\b|'
    r'\b[0-9a-f]{20,}\b|\b\d{12,}\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}|https?://|(?:^|\s)/(?:home|var|etc|root|data)/)'
)
CHASSIS = {3: 'Desktop', 4: 'Low Profile Desktop', 5: 'Pizza Box', 6: 'Mini Tower', 7: 'Tower', 8: 'Portable', 9: 'Laptop', 10: 'Notebook', 11: 'Hand Held', 12: 'Docking Station', 13: 'All In One', 14: 'Sub Notebook', 15: 'Space-Saving', 16: 'Lunch Box', 17: 'Main Server Chassis', 18: 'Expansion Chassis', 19: 'SubChassis', 20: 'Bus Expansion Chassis', 21: 'Peripheral Chassis', 22: 'Storage Chassis', 23: 'Rack Mount Chassis', 24: 'Sealed-Case PC', 30: 'Tablet', 31: 'Convertible', 32: 'Detachable'}


def warn(message):
    print('fleet_facts: ' + message, file=sys.stderr)


def clean(value):
    text = ' '.join(str(value or '').replace('\x00', '').split())
    if text in PLACEHOLDERS:
        return ''
    if len(text) > 200 or SENSITIVE.search(text):
        warn('sensitive or invalid hardware/OS text omitted')
        return ''
    return text


def read_yaml(path):
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        if not shutil.which('yq'):
            raise RuntimeError('install yq or Python PyYAML to read fleet configuration')
        result = subprocess.run(['yq', '-o=json', '.', str(path)], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('could not read fleet configuration with yq')
        return json.loads(result.stdout) or {}
    with path.open(encoding='utf-8') as stream:
        return yaml.safe_load(stream) or {}


def group_file(repo, group):
    path = repo / 'group_vars' / (group + '.yml')
    return read_yaml(path)


def config(repo, machine):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', machine):
        raise ValueError('invalid inventory host name')
    defaults = read_yaml(repo / 'units/fleet-facts/defaults.yml')
    if not all(key in defaults for key in ('fleet_facts_publish', 'fleet_facts_repo', 'fleet_facts_branch')):
        raise ValueError('fleet facts defaults are missing or incomplete')
    inventory = read_yaml(repo / 'inventory.yml')
    if not isinstance(inventory, dict) or not isinstance(inventory.get('all'), dict):
        raise ValueError('invalid inventory')
    all_group = inventory['all']
    groups = []
    host_values = {}

    def visit(name, node, depth):
        if not isinstance(node, dict):
            raise ValueError('invalid inventory group')
        hosts = node.get('hosts') or {}
        children = node.get('children') or {}
        if not isinstance(hosts, dict) or not isinstance(children, dict):
            raise ValueError('invalid inventory hosts or children')
        belongs = machine in hosts
        if belongs:
            value = hosts[machine] or {}
            if not isinstance(value, dict):
                raise ValueError('invalid inventory host variables')
            host_values.update(value)
        for child_name, child in sorted(children.items()):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', child_name):
                raise ValueError('invalid inventory group name')
            belongs = visit(child_name, child or {}, depth + 1) or belongs
        if belongs and name not in ('all', 'ungrouped'):
            groups.append((depth, name, node.get('vars') or {}))
        return belongs

    if not visit('all', all_group, 0):
        raise RuntimeError('machine is not in inventory; register it before publishing')
    values = dict(defaults)
    values.update(all_group.get('vars') or {})
    values.update(group_file(repo, 'all'))
    for _, name, variables in sorted(groups):
        if not isinstance(variables, dict):
            raise ValueError('invalid inventory group variables')
        values.update(variables)
        values.update(group_file(repo, name))
    values.update(host_values)
    values.update(read_yaml(repo / 'host_vars' / (machine + '.yml')))
    enabled = values['fleet_facts_publish']
    if isinstance(enabled, str):
        if enabled.lower() not in ('true', 'false', 'yes', 'no', '1', '0'):
            raise ValueError('invalid fleet_facts_publish value')
        enabled = enabled.lower() in ('true', 'yes', '1')
    if not isinstance(enabled, bool):
        raise ValueError('invalid fleet_facts_publish value')
    repo_name = values['fleet_facts_repo']
    branch = values['fleet_facts_branch']
    if not isinstance(repo_name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo_name):
        raise ValueError('invalid fleet facts repository')
    if not isinstance(branch, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', branch):
        raise ValueError('invalid fleet facts branch')
    return enabled, repo_name, branch, sorted(name for _, name, _ in groups)


def optional_file(root, name, strict=False):
    try:
        return (root / name.lstrip('/')).read_text(encoding='utf-8', errors='replace').strip()
    except FileNotFoundError:
        return ''
    except OSError:
        if strict:
            raise RuntimeError('could not read an optional hardware attribute') from None
        warn('could not read an optional hardware attribute')
        return ''


def required_file(root, name):
    value = optional_file(root, name)
    if not value:
        raise RuntimeError('required OS or hardware data unavailable: ' + name)
    return value


def command(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_os_release(root):
    data = required_file(root, '/etc/os-release')
    values = {}
    for line in data.splitlines():
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in ('NAME', 'VERSION_ID', 'VERSION_CODENAME', 'UBUNTU_CODENAME'):
            parsed = shlex.split(value, comments=False)
            if len(parsed) > 1:
                raise ValueError('invalid os-release value')
            values[key] = parsed[0] if parsed else ''
    if not values.get('NAME'):
        raise ValueError('os-release has no NAME')
    return values


def collect(machine, groups, home, termux=False, root=Path('/'), run=command, strict=False):
    if termux:
        release = run(['getprop', 'ro.build.version.release'])
        if release is None or release.returncode or not release.stdout.strip():
            raise RuntimeError('cannot read Android release with getprop')
        os_info = {'name': 'Android', 'version': clean(release.stdout), 'codename': ''}
        android_model = run(['getprop', 'ro.product.model'])
        if android_model is None or android_model.returncode:
            if strict:
                raise RuntimeError('Android model inspection failed')
            warn('Android model unavailable')
            model = ''
        else:
            model = clean(android_model.stdout)
    else:
        os_release = read_os_release(root)
        os_info = {'name': clean(os_release.get('NAME')), 'version': clean(os_release.get('VERSION_ID')), 'codename': clean(os_release.get('VERSION_CODENAME') or os_release.get('UBUNTU_CODENAME'))}
        model = ''
    os_info['kernel'] = clean(platform.release())
    model = model or clean(optional_file(root, '/sys/firmware/devicetree/base/model', strict)) or clean(optional_file(root, '/sys/devices/virtual/dmi/id/product_name', strict))
    vendor = clean(optional_file(root, '/sys/devices/virtual/dmi/id/sys_vendor', strict))
    chassis = optional_file(root, '/sys/devices/virtual/dmi/id/chassis_type', strict)
    form_factor = CHASSIS.get(int(chassis), '') if chassis.isdigit() else ''
    cpuinfo = required_file(root, '/proc/cpuinfo')
    cpu = ''
    cpu_count = 0
    for line in cpuinfo.splitlines():
        key, separator, value = line.partition(':')
        if not separator:
            continue
        if key.strip().lower() == 'processor' and value.strip().isdigit():
            cpu_count += 1
        if not cpu and key.strip().lower() in ('model name', 'hardware', 'processor') and not value.strip().isdigit():
            cpu = clean(value)
    cpu_count = cpu_count or os.cpu_count() or 0
    if not cpu:
        warn('CPU model unavailable')
    meminfo = required_file(root, '/proc/meminfo')
    match = re.search(r'^MemTotal:\s*(\d+)\s+kB\s*$', meminfo, re.MULTILINE)
    if not match:
        raise ValueError('MemTotal missing in /proc/meminfo')
    memory_gb = round((int(match.group(1)) // 1024) / 1024, 1)
    uptime = required_file(root, '/proc/uptime').split()[0]
    uptime_days = round(float(uptime) / 86400, 1)
    gpus = []
    pci = run(['lspci', '-mm'])
    if pci is None or pci.returncode:
        if strict:
            raise RuntimeError('GPU inventory inspection failed (lspci missing or failed)')
        warn('GPU inventory unavailable (lspci missing or failed)')
    else:
        for line in pci.stdout.splitlines():
            fields = shlex.split(line)
            if len(fields) >= 4 and re.match(r'^(VGA|3D|Display)', fields[1], re.I):
                gpu = clean(fields[2] + ' ' + fields[3])
                if gpu and not re.fullmatch(r'(?:\S+ )?Device [0-9a-fA-F]{4}', gpu):
                    gpus.append(gpu)
    virt = run(['systemd-detect-virt', '--vm'])
    if virt is None:
        if strict:
            raise RuntimeError('virtualization inspection unavailable')
        warn('virtualization detection unavailable')
        virtualization = ''
    elif virt.returncode == 0:
        virtualization = clean(virt.stdout)
    elif virt.returncode == 1:
        virtualization = ''
    else:
        if strict:
            raise RuntimeError('virtualization inspection failed')
        warn('virtualization detection failed')
        virtualization = ''
    last_path = home / '.cache/dotfiles/last-apply.json'
    if last_path.exists():
        with last_path.open(encoding='utf-8') as stream:
            last = json.load(stream)
        if not isinstance(last, dict):
            raise ValueError('invalid last-apply record')
    else:
        last = {}
    at = last.get('timestamp', last.get('at', ''))
    if at:
        if not isinstance(at, str):
            raise ValueError('invalid last-apply timestamp')
        dt.datetime.fromisoformat(at.replace('Z', '+00:00'))
    status = int(last.get('rc', last.get('exit_code', 1))) == 0 if last else ''
    return {
        'schema': 1, 'host': machine, 'updated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'groups': groups, 'os': os_info,
        'hardware': {'vendor': vendor, 'model': model, 'form_factor': form_factor, 'arch': clean(platform.machine()), 'cpu': cpu, 'cpu_threads': cpu_count, 'gpus': gpus, 'memory_gb': memory_gb},
        'virtualization': virtualization, 'uptime_days': uptime_days, 'last_apply': {'at': at, 'ok': status},
    }


def main():
    repo, machine, termux = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == '1'
    enabled, target, branch, groups = config(repo, machine)
    if not enabled:
        print('SKIPPED: fleet facts publishing disabled for this host')
        return 0
    if len(sys.argv) > 4 and sys.argv[4] == '--check':
        auth = command(['gh', 'auth', 'status'])
        if auth is None or auth.returncode:
            raise RuntimeError('gh authentication unavailable; cannot inspect fleet facts publication')
        collect(machine, groups, Path(os.environ['HOME']), termux, strict=True)
        # Every apply publishes a new timestamp, even when other facts are unchanged.
        print(f'PLAN: publish facts/{machine}.json to {target} branch {branch} (updated timestamp)')
        return 0
    auth = command(['gh', 'auth', 'status'])
    if auth is None or auth.returncode:
        print('PARTIAL: gh is not authenticated; fleet facts not published')
        return 0
    facts = collect(machine, groups, Path(os.environ['HOME']), termux)
    path = f'repos/{target}/contents/facts/{machine}.json'
    prior = command(['gh', 'api', f'{path}?ref={quote(branch, safe="")}', '--jq', '.sha'])
    sha = prior.stdout.strip() if prior is not None and prior.returncode == 0 else ''
    content = base64.b64encode((json.dumps(facts, indent=2, ensure_ascii=True) + '\n').encode()).decode()
    body = {'message': f'facts: {machine}', 'content': content, 'branch': branch}
    if sha:
        body['sha'] = sha
    try:
        result = subprocess.run(['gh', 'api', '-X', 'PUT', path, '--input', '-', '--jq', '.commit.sha'], input=json.dumps(body), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode:
        warn('could not publish fleet facts (GitHub API request failed)')
    else:
        print('published fleet facts')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except RuntimeError as error:
        # RuntimeError messages above are fixed diagnostics, never raw values.
        warn('collection/configuration failed: ' + str(error))
        sys.exit(1)
    except Exception as error:
        # Do not expose YAML parse excerpts, host data, or command output.
        warn('collection/configuration failed: ' + error.__class__.__name__)
        sys.exit(1)
