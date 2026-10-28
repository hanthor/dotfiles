"""Check-mode package inspection without invoking package managers on the host."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

from conftest import write_stub
from test_package_native_units import package_env, run_flatpak_with_dangling_store, run_unit


@pytest.fixture
def check_env(package_env, tmp_path):
    root, env, log = package_env
    bindir = Path(env["PATH"].split(os.pathsep)[0])
    sandbox_log = tmp_path / "sandbox.jsonl"
    env.update(UNITS_CHECK="1", SANDBOX_LOG=str(sandbox_log))
    program = f'''#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["SANDBOX_LOG"], "a") as f:
    f.write(json.dumps(args) + "\\n")
if os.getenv("SANDBOX_FAIL") == "1":
    print("sentinel-credential", file=sys.stderr)
    sys.exit(1)
required = ["--unshare-all", "--ro-bind", "--tmpfs", "--clearenv"]
if not all(flag in args for flag in required) or args[args.index("--tmpfs") + 1] != "/run":
    sys.exit(98)
command = next((i for i, arg in enumerate(args) if arg == "flatpak" or arg.endswith("/bin/brew") or arg.endswith("/bin/python3")), None)
if command is None:
    sys.exit(97)
exe, sub = args[command], args[command + 1:]
if exe == "flatpak":
    if sub == ["remotes", "--system", "--columns=name"]:
        print(os.getenv("SYSTEM_REMOTES", "flathub"))
    elif sub == ["list", "--system", "--columns=application", "--app"]:
        print(os.getenv("SYSTEM_APPS", "org.mozilla.firefox\\norg.example.Installed"))
    elif sub == ["remotes", "--user", "--columns=name"]:
        print(os.getenv("USER_REMOTES", ""))
    elif sub == ["list", "--user", "--columns=application", "--app"]:
        print("\\n".join(json.loads(os.getenv("USER_ORIGINS", "{{}}"))))
    elif sub[:3] == ["info", "--user", "--show-origin"]:
        origins = json.loads(os.getenv("USER_ORIGINS", "{{}}"))
        if sub[-1] not in origins or os.getenv("FAIL_ORIGIN") == sub[-1]:
            sys.exit(1)
        print(origins[sub[-1]])
    else:
        sys.exit(96)
elif exe.endswith("/bin/brew"):
    if sub == ["tap"]:
        print(os.getenv("BREW_TAPS", "example/core\\nexample/desktop"))
    elif sub[:3] == ["info", "--json=v1", "--formula"] and len(sub) == 4:
        if os.getenv("BLOCKED_FAIL") == "1":
            print("sentinel-credential", file=sys.stderr)
            sys.exit(1)
        if os.getenv("BLOCKED_MALFORMED") == "1":
            print('not-json sentinel-credential')
        else:
            installed = [{{"version": "1"}}] if os.getenv("BLOCKED_INSTALLED", "1") == "1" else []
            print(json.dumps([{{"name": "canonical-name", "aliases": [sub[-1]], "installed": installed}}]))
    elif sub == ["bundle", "check", "--file=-", "--no-upgrade", "--verbose"]:
        brewfile = sys.stdin.read()
        if 'brew "git"' not in brewfile:
            sys.exit(95)
        if os.getenv("MISSING_BUNDLE") == "1":
            print("brew bundle can't satisfy your Brewfile's dependencies.", file=sys.stderr)
            print("→ Formula desktop-pkg needs to be installed.", file=sys.stderr)
            print("sentinel-credential", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit(94)
elif sub[:1] != ["-c"]:
    sys.exit(93)
elif os.getenv("PYTHON_MISSING") == "1":
    sys.exit(42)
'''
    bwrap = bindir / "bwrap"
    bwrap.write_text(program)
    bwrap.chmod(0o755)
    return root, env, log, sandbox_log


def sandbox_calls(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def tree_state(path):
    return {
        str(item.relative_to(path)): (stat.S_IMODE(item.stat().st_mode), item.read_bytes() if item.is_file() else None)
        for item in path.rglob("*") if not item.is_symlink()
    }


def test_flatpak_check_reports_scoped_drift_without_mutation(check_env):
    root, env, log, sandbox = check_env
    (root / "host_vars/laptop.yml").write_text(yaml.safe_dump({
        "user_flatpak_remotes": [{"name": "private", "url": "https://example.test/secret?token=sentinel-credential"}],
        "user_flatpaks": [
            {"remote": "private", "id": "org.example.Existing"},
            {"remote": "private", "id": "org.example.New"},
            {"remote": "other", "id": "org.example.New"},
        ],
    }))
    env["USER_ORIGINS"] = json.dumps({"org.example.Existing": "other"})
    env["DOTFILES_UPGRADE"] = "1"
    home = Path(env["HOME"])
    before = tree_state(home)
    result = run_unit("flatpak", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "remove system Flatpak org.mozilla.firefox" in result.stdout
    assert "install system Flatpak org.example.First" in result.stdout
    assert "add user Flatpak remote private" in result.stdout
    assert "install user Flatpak org.example.New from private" in result.stdout
    assert "org.example.Existing uses other" in result.stdout
    assert "org.example.New would use private" in result.stdout
    assert "system update requested" in result.stdout
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert tree_state(home) == before
    assert not log.exists()
    commands = sandbox_calls(sandbox)
    assert commands and all("--unshare-all" in cmd and "--clearenv" in cmd for cmd in commands)
    assert all("--ro-bind" in cmd and "--tmpfs" in cmd for cmd in commands)
    assert all("install" not in cmd and "uninstall" not in cmd and "remote-add" not in cmd for cmd in commands)


def test_flatpak_check_reports_inspection_and_origin_failures(check_env):
    root, env, log, sandbox = check_env
    (root / "host_vars/laptop.yml").write_text(yaml.safe_dump({
        "user_flatpaks": [{"remote": "private", "id": "org.example.Existing"}],
    }))
    env["USER_ORIGINS"] = json.dumps({"org.example.Existing": "private"})
    env["FAIL_ORIGIN"] = "org.example.Existing"
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    assert "Cannot inspect origin" in result.stderr
    assert "install user Flatpak org.example.Existing" not in result.stdout
    env["SANDBOX_FAIL"] = "1"
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    assert "read-only sandbox" in result.stderr
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert not log.exists()


def test_flatpak_check_respects_profile_and_never_touches_wrappers(check_env):
    root, env, log, sandbox = check_env
    (root / "host_vars/laptop.yml").write_text("skip_flatpak: true\n")
    result = run_unit("flatpak", env)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not sandbox.exists() and not log.exists()
    assert not (Path(env["HOME"]) / ".local").exists()


def test_homebrew_check_reports_real_plans_and_never_runs_apply(check_env):
    _, env, log, sandbox = check_env
    env["MISSING_BUNDLE"] = "1"
    env["DOTFILES_UPGRADE"] = "1"
    home, prefix = Path(env["HOME"]), Path(env["BREW_PREFIX"])
    (home / "Brewfile").write_text("old contents\n")
    (home / "Brewfile").chmod(0o600)
    before_home, before_prefix = tree_state(home), tree_state(prefix)
    result = run_unit("homebrew", env)
    assert result.returncode != 0  # bundle uses the same status for drift and inspection errors
    assert "update Brewfile" in result.stdout
    assert "Brewfile mode to 0644" in result.stdout
    assert "tap Homebrew repository coreowner/tap" in result.stdout
    assert "dependency desktop-pkg" in result.stdout
    assert 'attempt Homebrew tap trust on apply' in result.stdout
    assert "uninstall blocked Homebrew formula trash-cli" in result.stdout
    assert "Homebrew upgrade requested" in result.stdout
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert tree_state(home) == before_home and tree_state(prefix) == before_prefix
    assert not log.exists()
    commands = sandbox_calls(sandbox)
    assert commands and all("--unshare-all" in cmd and "--clearenv" in cmd for cmd in commands)
    assert all("--ro-bind" in cmd and "--tmpfs" in cmd for cmd in commands)
    assert all("install" not in cmd and "uninstall" not in cmd and "upgrade" not in cmd for cmd in commands)


def test_homebrew_check_skips_desktop_only_taps_for_server(check_env):
    root, env, log, _ = check_env
    (root / "host_vars/laptop.yml").write_text("is_desktop: false\nextra_brews: [private/tap/tool]\n")
    env["BREW_TAPS"] = "example/core"
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tap Homebrew repository coreowner/tap" in result.stdout
    assert "tap Homebrew repository example/desktop" not in result.stdout
    assert "tap Homebrew repository private/tap" not in result.stdout
    assert not log.exists()


def test_homebrew_check_missing_brew_and_failed_sandbox(check_env):
    _, env, log, sandbox = check_env
    brew = Path(env["BREW_PREFIX"]) / "bin/brew"
    original = brew.read_bytes()
    brew.unlink()
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGE: install Homebrew" in result.stdout
    assert 'attempt Homebrew tap trust on apply' in result.stdout
    assert "install configured Homebrew taps and packages" in result.stdout
    assert not sandbox.exists() and not log.exists()
    brew.write_bytes(original)
    brew.chmod(0o755)
    env["SANDBOX_FAIL"] = "1"
    result = run_unit("homebrew", env)
    assert result.returncode != 0
    assert "Cannot inspect Homebrew" in result.stderr
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert not log.exists()


def test_homebrew_check_never_bootstraps_missing_yq(check_env):
    _, env, log, sandbox = check_env
    bindir = Path(env["PATH"].split(os.pathsep)[0])
    write_stub(bindir, "yq", 'echo "sentinel-credential" >&2; exit 1\n')
    result = run_unit("homebrew", env)
    assert result.returncode != 0
    assert "Mike Farah yq is required" in result.stderr
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert not sandbox.exists() and not log.exists()


def test_flatpak_check_matching_system_and_wrappers_are_unchanged(check_env):
    _, env, log, _ = check_env
    env["DOTFILES_UPGRADE"] = "0"
    env["SYSTEM_APPS"] = "\n".join(["org.example.Installed", "org.example.First", "org.example.Second"])
    bindir = Path(env["HOME"]) / ".local/bin"
    bindir.mkdir(parents=True)
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        wrapper = bindir / name
        wrapper.write_text('#!/usr/bin/env bash\nexec flatpak run org.chromium.Chromium "$@"\n')
        wrapper.chmod(0o755)
    before = tree_state(Path(env["HOME"]))
    result = run_unit("flatpak", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGE:" not in result.stdout
    assert tree_state(Path(env["HOME"])) == before and not log.exists()


def test_flatpak_check_preserves_custom_launchers_and_symlinks(check_env, tmp_path):
    _, env, log, _ = check_env
    bindir = Path(env["HOME"]) / ".local/bin"
    bindir.mkdir(parents=True)
    custom = bindir / "google-chrome"
    custom.write_text("custom launcher\n")
    target = tmp_path / "target"
    target.write_text("target\n")
    link = bindir / "google-chrome-stable"
    link.symlink_to(target)
    before = tree_state(Path(env["HOME"]))
    result = run_unit("flatpak", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRESERVED: existing Chromium launcher google-chrome" in result.stdout
    assert "PRESERVED: existing Chromium launcher google-chrome-stable" in result.stdout
    assert "CHANGE: install Chromium wrapper chromium" in result.stdout
    assert tree_state(Path(env["HOME"])) == before and not log.exists()
    assert link.is_symlink() and link.readlink() == target and target.read_text() == "target\n"



def test_flatpak_check_preserves_dangling_store(check_env, tmp_path):
    root, env, log, sandbox = check_env
    (root / "host_vars/laptop.yml").write_text(yaml.safe_dump({
        "user_flatpaks": [{"remote": "flatpark", "id": "org.example.User"}],
    }))
    result, store = run_flatpak_with_dangling_store(root, env, tmp_path)
    assert result.returncode != 0 and "dangling symlink" in result.stderr
    assert "SKIPPED: system Flatpak inspection" in result.stdout
    assert store.is_symlink() and not store.exists() and not log.exists()
    commands = sandbox_calls(sandbox)
    assert any("--user" in cmd for cmd in commands)
    assert not any("--system" in cmd for cmd in commands)

def test_homebrew_check_matching_brewfile_and_bundle(check_env):
    _, env, log, _ = check_env
    env["DOTFILES_UPGRADE"] = "0"
    env["BREW_TAPS"] = "example/core\nexample/desktop\ncoreowner/tap\nme/tap"
    env["BLOCKED_INSTALLED"] = "0"
    bindir = Path(env["PATH"].split(os.pathsep)[0])
    write_stub(bindir, "uname", 'echo Linux\n')
    brewfile = Path(env["HOME"]) / "Brewfile"
    brewfile.write_text(
        '# Core packages\ntap "example/core"\n\n'
        'brew "git"\nbrew "coreowner/tap/formula"\n\n\n'
        '# Desktop packages\ntap "example/desktop"\n\n'
        'brew "desktop-pkg"\n\nbrew "me/tap/extra"\n\n'
        'cask "desktop-cask"\n\n'
    )
    brewfile.chmod(0o644)
    before = tree_state(Path(env["HOME"]))
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok    Homebrew bundle dependencies" in result.stdout
    assert "CHANGE: update Brewfile" not in result.stdout
    assert "Brewfile mode" not in result.stdout
    assert "uninstall blocked" not in result.stdout
    assert tree_state(Path(env["HOME"])) == before and not log.exists()


def test_flatpak_check_redacts_invalid_configuration(check_env):
    root, env, log, sandbox = check_env
    (root / "units/flatpak-packages.yml").write_text("flatpak_remotes: [sentinel-credential\n")
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    assert "Cannot inspect Flatpak configuration" in result.stderr
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert not sandbox.exists() and not log.exists()


def test_homebrew_check_reports_missing_python_packaging(check_env):
    _, env, log, _ = check_env
    env["PYTHON_MISSING"] = "1"
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGE: install Homebrew Python packaging" in result.stdout
    assert not log.exists()


@pytest.mark.parametrize("failure", ["BLOCKED_FAIL", "BLOCKED_MALFORMED"])
def test_homebrew_check_blocked_alias_inspection_failure_is_not_absence(check_env, failure):
    _, env, log, sandbox = check_env
    env[failure] = "1"
    result = run_unit("homebrew", env)
    assert result.returncode != 0
    assert "Cannot inspect blocked Homebrew formula trash-cli" in result.stderr
    assert "uninstall blocked Homebrew formula" not in result.stdout
    assert "sentinel-credential" not in result.stdout + result.stderr
    assert any(["info", "--json=v1", "--formula", "trash-cli"] == cmd[-4:] for cmd in sandbox_calls(sandbox))
    assert not log.exists()
