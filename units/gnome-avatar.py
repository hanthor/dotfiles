#!/usr/bin/env python3
"""Install the desktop avatar and update AccountsService as root."""

import grp
import os
from pathlib import Path
import pwd
import re
import sys
import tempfile

ICON = Path('/var/lib/AccountsService/icons/james')
ACCOUNT = Path('/var/lib/AccountsService/users/james')
GDM_CACHE = Path('/var/lib/gdm3/.cache')
ICON_VALUE = '/var/lib/AccountsService/icons/james'


def write_file(path, content, owner=None):
    """Replace changed content atomically, retaining existing ownership unless specified."""
    try:
        previous = path.stat()
        unchanged = path.read_bytes() == content
    except FileNotFoundError:
        previous = None
        unchanged = False
    if not unchanged:
        fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            if owner is not None:
                os.chown(name, *owner)
            elif previous is not None:
                os.chown(name, previous.st_uid, previous.st_gid)
            os.chmod(name, 0o644)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    else:
        if owner is not None and (previous.st_uid, previous.st_gid) != owner:
            os.chown(path, *owner)
        if previous.st_mode & 0o7777 != 0o644:
            os.chmod(path, 0o644)


def account_with_icon(text):
    """Set User.Icon without rewriting unrelated account options or comments."""
    lines = text.splitlines(keepends=True)
    output = []
    in_user = False
    saw_user = False
    wrote_icon = False
    for line in lines:
        section = re.match(r'^\s*\[([^]]+)\]', line)
        if section:
            if in_user and not wrote_icon:
                if output and not output[-1].endswith('\n'):
                    output[-1] += '\n'
                output.append(f'Icon={ICON_VALUE}\n')
                wrote_icon = True
            in_user = section.group(1) == 'User'
            saw_user = saw_user or in_user
        if in_user and re.match(r'^\s*Icon\s*=', line):
            if not wrote_icon:
                output.append(f'Icon={ICON_VALUE}\n')
                wrote_icon = True
            continue
        output.append(line)
    if in_user and not wrote_icon:
        if output and not output[-1].endswith('\n'):
            output[-1] += '\n'
        output.append(f'Icon={ICON_VALUE}\n')
    elif not saw_user:
        if output and not output[-1].endswith('\n'):
            output[-1] += '\n'
        output.extend(['[User]\n', f'Icon={ICON_VALUE}\n'])
    return ''.join(output)


def install_avatar(source):
    data = source.read_bytes()
    write_file(ICON, data)
    try:
        gdm = pwd.getpwnam('gdm')
    except KeyError:
        pass
    else:
        group = grp.getgrnam('gdm')
        GDM_CACHE.mkdir(parents=True, exist_ok=True, mode=0o755)
        write_file(GDM_CACHE / 'james', data, (gdm.pw_uid, group.gr_gid))
    try:
        account = ACCOUNT.read_text()
    except FileNotFoundError:
        account = ''
    write_file(ACCOUNT, account_with_icon(account).encode())


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: gnome-avatar.py PROFILE_PNG')
    install_avatar(Path(sys.argv[1]))
