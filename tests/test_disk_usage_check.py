"""roles/systemd/files/disk-usage-check.py: threshold, skip rules and exit codes.

The script reads real filesystems, so each test loads it fresh and swaps its
os.stat / os.statvfs for fakes keyed by path.
"""
import importlib.util
import os
import types

import pytest

from conftest import REPO

SCRIPT = REPO / "roles" / "systemd" / "files" / "disk-usage-check.py"


def load():
    spec = importlib.util.spec_from_file_location("disk_usage_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def vfs(blocks=100, free=0, avail=0, flag=0):
    return types.SimpleNamespace(f_blocks=blocks, f_bfree=free, f_bavail=avail, f_flag=flag)


@pytest.fixture
def run(monkeypatch, capsys):
    """run(threshold, {path: (dev, statvfs)}) -> (exit code, stdout, stderr).

    A path missing from the mapping raises FileNotFoundError, like a real
    path that does not exist.
    """
    mod = load()

    def _run(threshold, fs, extra_args=()):
        def fake_stat(path):
            if path not in fs:
                raise FileNotFoundError(path)
            return types.SimpleNamespace(st_dev=fs[path][0])

        def fake_statvfs(path):
            if path not in fs:
                raise FileNotFoundError(path)
            return fs[path][1]

        # Patch the script's own os handle, not the real module: pytest's
        # tmp-path handling calls os.stat too.
        monkeypatch.setattr(
            mod,
            "os",
            types.SimpleNamespace(stat=fake_stat, statvfs=fake_statvfs, ST_RDONLY=os.ST_RDONLY),
        )
        monkeypatch.setattr(mod.sys, "argv", ["disk-usage-check.py", str(threshold), *fs, *extra_args])
        code = mod.main()
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


@pytest.mark.parametrize(
    "st, expected",
    [
        (vfs(blocks=100, free=50, avail=50), 50),
        (vfs(blocks=100, free=0, avail=0), 100),
        # used=1 of 3 -> 33.33% rounds up to 34, as df does
        (vfs(blocks=3, free=2, avail=2), 34),
        # reserved blocks: bfree counts root's reserve, bavail does not
        (vfs(blocks=100, free=10, avail=0), 100),
        (vfs(blocks=100, free=100, avail=100), 0),
        (vfs(blocks=0, free=0, avail=0), 0),
    ],
)
def test_usage_percent(st, expected):
    assert load().usage_percent(st) == expected


def test_below_threshold_exits_zero(run):
    code, out, err = run(90, {"/var": (1, vfs(free=50, avail=50))})
    assert code == 0
    assert out == "/var: 50% used\n"
    assert err == ""


def test_threshold_is_strictly_greater_than(run):
    code, _, _ = run(50, {"/var": (1, vfs(free=50, avail=50))})
    assert code == 0
    code, _, err = run(49, {"/var": (1, vfs(free=50, avail=50))})
    assert code == 1
    assert "over 49%: /var 50%" in err


def test_lists_every_full_filesystem(run):
    code, out, err = run(
        80,
        {
            "/": (1, vfs(free=5, avail=5)),
            "/var": (2, vfs(free=10, avail=10)),
            "/home": (3, vfs(free=60, avail=60)),
        },
    )
    assert code == 1
    assert "/home: 40% used" in out
    assert err == "over 80%: / 95%, /var 90%\n"


def test_missing_path_is_skipped(run):
    fs = {"/var": (1, vfs(free=50, avail=50))}
    code, out, _ = run(10, fs, extra_args=("/does/not/exist",))
    assert out == "/var: 50% used\n"
    assert code == 1  # /var only; the missing path neither crashes nor counts


def test_missing_path_alone_exits_zero(run):
    code, out, err = run(10, {}, extra_args=("/does/not/exist",))
    assert (code, out, err) == (0, "", "")


def test_read_only_filesystem_is_skipped(run):
    # composefs/erofs root on bootc hosts always reads 100% full
    code, out, err = run(10, {"/": (1, vfs(free=0, avail=0, flag=os.ST_RDONLY))})
    assert (code, out, err) == (0, "", "")


def test_same_device_is_reported_once(run):
    fs = {
        "/var": (7, vfs(free=5, avail=5)),
        "/var/lib": (7, vfs(free=5, avail=5)),
    }
    code, out, err = run(10, fs)
    assert out == "/var: 95% used\n"
    assert err == "over 10%: /var 95%\n"
    assert code == 1


def test_too_few_arguments_prints_usage(monkeypatch, capsys):
    mod = load()
    monkeypatch.setattr(mod.sys, "argv", ["disk-usage-check.py", "90"])
    assert mod.main() == 2
    assert "usage:" in capsys.readouterr().err


def test_non_numeric_threshold_raises(monkeypatch):
    mod = load()
    monkeypatch.setattr(mod.sys, "argv", ["disk-usage-check.py", "lots", "/"])
    with pytest.raises(ValueError):
        mod.main()
