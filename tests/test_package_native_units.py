"""Behavioral coverage for native package units; all package commands are isolated."""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import REPO, write_stub


@pytest.fixture
def package_env(tmp_path, stub_env):
    yq = shutil.which("yq")
    if not yq or "github.com/mikefarah/yq" not in subprocess.run(
        [yq, "--version"], text=True, capture_output=True
    ).stdout:
        pytest.skip("Mike Farah yq is required")
    bindir, env = stub_env
    root = tmp_path / "repo"
    root.mkdir()
    (root / "units").mkdir()
    (root / "units/package-config.bash").symlink_to(REPO / "units/package-config.bash")
    (root / "group_vars").mkdir()
    (root / "host_vars").mkdir()
    (root / "group_vars/all.yml").write_text(yaml.safe_dump({
        "core_taps": ["example/core"],
        "core_brews": ["git", "coreowner/tap/formula"],
        "core_tap_brews": [],
        "desktop_taps": ["example/desktop"],
        "desktop_brews": ["desktop-pkg"],
        "desktop_casks": ["desktop-cask"],
        "desktop_vscode_extensions": ["author.extension"],
        "brew_blocked": ["trash-cli"],
        "flatpak_remotes": [{"name": "wrong", "url": "https://example.test/wrong"}],
    }))
    (root / "host_vars/laptop.yml").write_text(yaml.safe_dump({"extra_brews": ["me/tap/extra"]}))
    (root / "inventory.yml").write_text(yaml.safe_dump({
        "all": {"children": {"desktop": {"hosts": {"laptop": None}}}}
    }))
    (root / "units/flatpak-packages.yml").write_text(yaml.safe_dump({
        "flatpak_remotes": [{"name": "flathub", "url": "https://example.test/flathub.flatpakrepo"}],
        "system_flatpaks": ["org.example.Installed", "org.example.First", "org.example.Second"],
    }))
    prefix = tmp_path / "brew" / ".linuxbrew"
    (prefix / "bin").mkdir(parents=True)
    log = tmp_path / "commands.jsonl"
    env.update(DOTFILES_DIR=str(root), DOTFILES_MACHINE="laptop", BREW_PREFIX=str(prefix),
               COMMAND_LOG=str(log), INSTALLED_APPS=str(tmp_path / "installed"),
               USER_APPS=str(tmp_path / "user-apps.json"))
    Path(env["INSTALLED_APPS"]).write_text("org.mozilla.firefox\norg.example.Installed\n")
    Path(env["USER_APPS"]).write_text("{}")
    write_stub(bindir, "cc", "exit 0\n")
    write_stub(bindir, "gcc", "exit 0\n")
    # Never invoke host sudo, even if the CI process runs as root.
    write_stub(bindir, "id", 'if [ "$1" = -u ]; then echo 1000; else echo tester; fi\n')
    write_stub(bindir, "sudo", 'shift; if [ "$1" = flatpak ]; then PACKAGE_SUDO=1 exec "$@"; fi; exit 0\n')
    program = f'''#!{sys.executable}
import json, os, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as f:
    f.write(json.dumps({{"name": name, "args": args,
                        "git_count": os.getenv("GIT_CONFIG_COUNT"),
                        "git_value": os.getenv("GIT_CONFIG_VALUE_0"),
                        "sudo": os.getenv("PACKAGE_SUDO")}}) + "\\n")
if name == "brew" and args == ["install", "yq"]:
    if os.getenv("FAIL_YQ") == "1":
        sys.exit(1)
    target = os.getenv("YQ_BINARY")
    if target:
        os.symlink(target, os.path.join(os.path.dirname(sys.argv[0]), "yq"))
if name == "brew" and args and args[0] == "tap" and os.getenv("FAIL_TAP") == "1":
    sys.exit(1)
if name == "brew" and args[:2] == ["uninstall", "--formula"]:
    print("Error: No such keg", file=sys.stderr)
    sys.exit(1)
if name == "flatpak" and args and args[0] == "list":
    if "--user" in args:
        if os.getenv("FAIL_USER_LIST") == "1":
            sys.exit(1)
        print("\\n".join(json.load(open(os.environ["USER_APPS"]))))
    else:
        print(open(os.environ["INSTALLED_APPS"]).read(), end="")
if name == "flatpak" and args and args[0] == "info" and "--user" in args:
    if os.getenv("FAIL_USER_INFO") == args[-1]:
        sys.exit(1)
    print(json.load(open(os.environ["USER_APPS"]))[args[-1]])
if name == "flatpak" and args and args[0] == "install" and "--user" in args:
    state = json.load(open(os.environ["USER_APPS"]))
    state[args[-1]] = args[-2]
    with open(os.environ["USER_APPS"], "w") as f:
        json.dump(state, f)
if name == "flatpak" and args and args[0] == "install" and os.getenv("FAIL_BATCH") == "1":
    if "org.example.Second" in args:
        sys.exit(1)
'''
    for path in (prefix / "bin/brew", prefix / "bin/python3", bindir / "flatpak"):
        path.write_text(program)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return root, env, log


def run_unit(name, env):
    return subprocess.run(["bash", str(REPO / "units" / f"{name}.sh")],
                          env=env, text=True, capture_output=True)


def calls(log, name):
    if not log.exists():
        return []
    return [entry for entry in map(json.loads, log.read_text().splitlines()) if entry["name"] == name]


def isolate_bootstrap_path(env, tmp_path):
    original_bin = Path(env["PATH"].split(os.pathsep)[0])
    isolated = tmp_path / "bootstrap-bin"
    isolated.mkdir()
    for binary in ("bash", "dirname", "stat", "mktemp", "rm", "mkdir", "install", "chmod", "cmp", "grep", "uname", "cp", "cat", "sed", "head"):
        target = shutil.which(binary)
        assert target is not None
        (isolated / binary).symlink_to(target)
    for binary in ("id", "sudo", "cc", "gcc"):
        (isolated / binary).symlink_to(original_bin / binary)
    env["YQ_BINARY"] = shutil.which("yq")
    env["PATH"] = str(isolated)
    return isolated


def test_fresh_homebrew_bootstraps_yq_then_loads_config(package_env, tmp_path):
    _, env, log = package_env
    bindir = isolate_bootstrap_path(env, tmp_path)
    brew = Path(env["BREW_PREFIX"]) / "bin/brew"
    template = tmp_path / "brew-template"
    template.write_text(brew.read_text())
    brew.unlink()
    env["BREW_INSTALL_TEMPLATE"] = str(template)
    write_stub(bindir, "curl", '''cat > "$4" <<'INSTALLER'
mkdir -p "$BREW_PREFIX/bin"
cp "$BREW_INSTALL_TEMPLATE" "$BREW_PREFIX/bin/brew"
chmod +x "$BREW_PREFIX/bin/brew"
INSTALLER
''')
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    args = [entry["args"] for entry in calls(log, "brew")]
    assert args[0] == ["install", "yq"]
    assert any(call[:2] == ["bundle", "install"] for call in args)
    assert 'brew "desktop-pkg"' in (Path(env["HOME"]) / "Brewfile").read_text()


def test_failed_yq_bootstrap_stops_before_bundle(package_env, tmp_path):
    _, env, log = package_env
    isolate_bootstrap_path(env, tmp_path)
    env["FAIL_YQ"] = "1"
    result = run_unit("homebrew", env)
    assert result.returncode != 0
    assert "Unable to install yq" in result.stderr
    assert [entry["args"] for entry in calls(log, "brew")] == [["install", "yq"]]
    assert not (Path(env["HOME"]) / "Brewfile").exists()


def test_brew_desktop_lists_taps_blocked_and_no_upgrade(package_env):
    _, env, log = package_env
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    brewfile = Path(env["HOME"]) / "Brewfile"
    content = brewfile.read_text()
    assert 'brew "git"' in content
    assert 'brew "desktop-pkg"' in content
    assert 'brew "me/tap/extra"' in content
    assert 'cask "desktop-cask"' in content
    assert stat.S_IMODE(brewfile.stat().st_mode) == 0o644
    entries = calls(log, "brew")
    args = [entry["args"] for entry in entries]
    for tap in ("example/core", "example/desktop", "coreowner/tap", "me/tap"):
        assert ["tap", tap] in args
        assert ["trust", tap] in args
    bundle = next(entry for entry in entries if entry["args"][:2] == ["bundle", "install"])
    assert "--no-upgrade" in bundle["args"]
    assert bundle["git_count"] == "1" and bundle["git_value"] == ""
    assert ["uninstall", "--formula", "trash-cli"] in args
    assert ["upgrade"] not in args
    before = brewfile.stat().st_mtime_ns
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert brewfile.stat().st_mtime_ns == before


def test_brew_host_profile_and_explicit_upgrade(package_env):
    root, env, log = package_env
    (root / "host_vars/laptop.yml").write_text("is_desktop: false\nextra_brews: [private-extra]\n")
    env["DOTFILES_UPGRADE"] = "1"
    result = run_unit("homebrew", env)
    assert result.returncode == 0, result.stdout + result.stderr
    content = (Path(env["HOME"]) / "Brewfile").read_text()
    assert "desktop-pkg" not in content and "private-extra" not in content
    assert ["upgrade"] in [entry["args"] for entry in calls(log, "brew")]


def test_brew_blocked_host_package_fails_before_any_brew_action(package_env):
    root, env, log = package_env
    (root / "host_vars/laptop.yml").write_text("extra_brews: [owner/tap/trash-cli]\n")
    result = run_unit("homebrew", env)
    assert result.returncode != 0
    assert "brew_blocked" in result.stderr
    assert not calls(log, "brew")
    assert not (Path(env["HOME"]) / "Brewfile").exists()


def test_brew_continues_after_tap_failure(package_env):
    _, env, log = package_env
    env["FAIL_TAP"] = "1"
    result = run_unit("homebrew", env)
    assert result.returncode != 0
    args = [entry["args"] for entry in calls(log, "brew")]
    assert any(call[:2] == ["bundle", "install"] for call in args)
    assert ["uninstall", "--formula", "trash-cli"] in args


def test_flatpak_system_scope_batch_fallback_and_wrappers(package_env):
    _, env, log = package_env
    env["FAIL_BATCH"] = "1"
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    args = [entry["args"] for entry in calls(log, "flatpak")]
    assert ["remote-add", "--if-not-exists", "--system", "flathub", "https://example.test/flathub.flatpakrepo"] in args
    assert ["uninstall", "--system", "-y", "org.mozilla.firefox"] in args
    assert ["install", "--system", "-y", "flathub", "org.example.First", "org.example.Second"] in args
    assert ["install", "--system", "-y", "flathub", "org.example.First"] in args
    assert not any("org.example.Installed" in call for call in args if call and call[0] == "install")
    assert ["install", "--system", "-y", "flathub", "org.example.Second"] in args
    assert not any("--user" in call or "update" in call for call in args)
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        wrapper = Path(env["HOME"]) / ".local/bin" / name
        assert wrapper.read_text() == '#!/usr/bin/env bash\nexec flatpak run org.chromium.Chromium "$@"\n'
        assert stat.S_IMODE(wrapper.stat().st_mode) == 0o755


def test_user_flatpaks_preserve_origins_and_do_not_use_sudo(package_env):
    root, env, log = package_env
    (root / "host_vars/laptop.yml").write_text(yaml.safe_dump({
        "user_flatpak_remotes": [{"name": "flatpark", "url": "https://example.test/flatpark.flatpakrepo"}],
        "user_flatpaks": [
            {"remote": "flatpark", "id": "org.example.Blueshell"},
            {"remote": "flatpark", "id": "org.example.Tavern"},
            {"remote": "flatpark", "id": "org.example.Compass"},
        ],
    }))
    Path(env["USER_APPS"]).write_text(json.dumps({
        "org.example.Blueshell": "other-origin", "org.example.Tavern": "flatpark",
    }))
    result = run_unit("flatpak", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRESERVED: user Flatpak org.example.Blueshell uses other-origin" in result.stdout
    entries = calls(log, "flatpak")
    user = [entry for entry in entries if "--user" in entry["args"]]
    args = [entry["args"] for entry in user]
    assert ["remote-add", "--if-not-exists", "--user", "flatpark", "https://example.test/flatpark.flatpakrepo"] in args
    assert ["install", "--user", "-y", "flatpark", "org.example.Compass"] in args
    assert not any(call[0] == "install" and call[-1] in ("org.example.Blueshell", "org.example.Tavern") for call in args)
    assert all(entry["sudo"] is None for entry in user)
    assert all(entry["sudo"] == "1" for entry in entries if "--system" in entry["args"])
    result = run_unit("flatpak", env)
    assert result.returncode == 0, result.stdout + result.stderr
    installs = [entry["args"] for entry in calls(log, "flatpak") if entry["args"][:2] == ["install", "--user"]]
    assert installs == [["install", "--user", "-y", "flatpark", "org.example.Compass"]]


def test_user_flatpak_origin_failure_is_not_an_install(package_env):
    root, env, log = package_env
    (root / "host_vars/laptop.yml").write_text(yaml.safe_dump({
        "user_flatpaks": [
            {"remote": "flatpark", "id": "org.example.Existing"},
            {"remote": "flatpark", "id": "org.example.New"},
        ],
    }))
    Path(env["USER_APPS"]).write_text(json.dumps({"org.example.Existing": "another"}))
    env["FAIL_USER_INFO"] = "org.example.Existing"
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    assert "Could not determine origin" in result.stderr
    args = [entry["args"] for entry in calls(log, "flatpak")]
    assert ["install", "--user", "-y", "flatpark", "org.example.New"] in args
    assert not any(call[:2] == ["install", "--user"] and call[-1] == "org.example.Existing" for call in args)


def test_invalid_user_flatpak_config_does_not_block_system_apps(package_env):
    root, env, log = package_env
    (root / "host_vars/laptop.yml").write_text("user_flatpaks:\n  - remote: flatpark\n")
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    assert "Invalid user Flatpak app ID" in result.stderr
    args = [entry["args"] for entry in calls(log, "flatpak")]
    assert ["install", "--system", "-y", "flathub", "org.example.First", "org.example.Second"] in args
    assert not any("--user" in call for call in args)


def test_flatpak_profile_gate_and_explicit_update(package_env):
    root, env, log = package_env
    (root / "host_vars/laptop.yml").write_text("machine_profile: vm-test\n")
    result = run_unit("flatpak", env)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not calls(log, "flatpak")
    (root / "host_vars/laptop.yml").write_text("skip_flatpak: true\n")
    result = run_unit("flatpak", env)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not calls(log, "flatpak")
    (root / "host_vars/laptop.yml").write_text("skip_flatpak: false\n")
    env["DOTFILES_UPGRADE"] = "true"
    result = run_unit("flatpak", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ["update", "--system", "-y"] in [entry["args"] for entry in calls(log, "flatpak")]


def test_missing_or_unusable_yq_fails_without_package_operations(package_env):
    _, env, log = package_env
    bindir = Path(env["PATH"].split(os.pathsep)[0])
    write_stub(bindir, "yq", 'echo "unusable yq" >&2; exit 1\n')
    for unit in ("homebrew", "flatpak"):
        result = run_unit(unit, env)
        assert result.returncode != 0
    assert ["install", "yq"] in [entry["args"] for entry in calls(log, "brew")]
    assert not any(entry["args"][:2] == ["bundle", "install"] for entry in calls(log, "brew"))
    assert not calls(log, "flatpak")


def test_missing_flatpak_fails_but_still_installs_wrappers(package_env, tmp_path):
    _, env, log = package_env
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    for binary in ("bash", "yq", "dirname", "mktemp", "mkdir", "install", "chmod", "cmp", "rm", "sed", "head"):
        target = shutil.which(binary)
        assert target is not None
        (isolated / binary).symlink_to(target)
    env["PATH"] = str(isolated)
    result = run_unit("flatpak", env)
    assert result.returncode != 0
    assert "flatpak is required" in result.stderr
    assert (Path(env["HOME"]) / ".local/bin/chromium").exists()
    assert not calls(log, "flatpak")
