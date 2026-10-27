#!/usr/bin/env python3
"""Apply lineinfile-style edits without replacing other settings."""
import errno
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


def update(path, pattern, line, check=False):
    path = Path(os.path.realpath(path))
    original = path.read_bytes()
    text = original.decode("utf-8")
    lines = text.splitlines(keepends=True)
    matches = [i for i, current in enumerate(lines) if re.search(pattern, current)]
    if matches:
        i = matches[-1]
        ending = "\n" if lines[i].endswith("\n") else ""
        lines[i] = line + ending
    elif not any(current.rstrip("\r\n") == line for current in lines):
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(line + "\n")
    result = "".join(lines).encode("utf-8")
    if result == original:
        return False
    if check:
        return True
    metadata = path.stat()
    fd, temp = tempfile.mkstemp(prefix=".dotfiles-hardening-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(result)
            out.flush()
            os.fchmod(out.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fchown(out.fileno(), metadata.st_uid, metadata.st_gid)
        # Atomic replacement must retain SELinux labels and other file xattrs.
        # If copying a label fails, leave the original in place.
        try:
            names = os.listxattr(path)
        except OSError as error:
            if error.errno not in (errno.ENOTSUP, errno.EOPNOTSUPP):
                raise
            names = []
        for name in names:
            os.setxattr(temp, name, os.getxattr(path, name))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def main():
    try:
        check = len(sys.argv) > 1 and sys.argv[1] == "--check"
        args = sys.argv[2:] if check else sys.argv[1:]
        changed = update(args[0], args[1], args[2], check=check)
    except (OSError, UnicodeError, re.error, IndexError) as error:
        print(f"hardening file update: {error}", file=sys.stderr)
        return 1
    return 10 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
