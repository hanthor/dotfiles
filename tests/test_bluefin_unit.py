"""Behavioral coverage for bluefin's host gates and desktop side effects."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import REPO, write_stub


@pytest.fixture
def desktop(tmp_path, stub_env):
    bindir, env = stub_env
    home = Path(env["HOME"])
    config = tmp_path / "config"
    (config / "host_vars").mkdir(parents=True)
    (config / "inventory.yml").write_text("all: {}\n")
    (config / "units").symlink_to(REPO / "units", target_is_directory=True)
    env.update(DOTFILES_DIR=str(config), DOTFILES_MACHINE="test-desktop",
               DOTFILES_IS_DESKTOP="true", BREW_PREFIX="/nonexistent",
               DBUS_SESSION_BUS_ADDRESS="")

    write_stub(bindir, "grep", '''\
if [ "${3:-}" = /etc/os-release ]; then exit "${STUB_BLUEFIN_RC:-1}"; fi
exec /usr/bin/grep "$@"
''')
    write_stub(bindir, "gsettings", '''\
echo "gsettings $* bus=${DBUS_SESSION_BUS_ADDRESS:-}" >> "$HOME/calls"
if [ "$1" = get ]; then exit "${STUB_GNOME_RC:-0}"; fi
''')
    write_stub(bindir, "podman", '''\
echo "podman $*" >> "$HOME/calls"
case "$1" in
  pull) exit "${STUB_PULL_RC:-0}" ;;
  create) echo test-container ;;
  cp)
    if [ "${STUB_MISSING_ICON:-0}" = 1 ] && [[ "$2" = *icons* ]]; then exit 1; fi
    case "$2" in
      *gschema.override) printf '[org.gnome.desktop.interface]\\ncolor-scheme=\\x27prefer-dark\\x27\\n' > "$3/zz0-bluefin-modifications.gschema.override" ;;
      *dconf*) : ;;
      *backgrounds*) printf '<file>/usr/share/backgrounds/bluefin/a.jpg</file>\\n' > "$3/01-bluefin.xml" ;;
      *icons*) printf icon > "$3/icon" ;;
      *ublue-os*) printf logo > "$3/logo" ;;
    esac ;;
esac
''')
    write_stub(bindir, "curl", '''\
url='' out=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    --retry) shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
echo "curl $url" >> "$HOME/calls"
case "$url" in
  */SHA256SUMS)
    read -r hash _ <<< "$(printf 'corral binary' | sha256sum)"
    [ "${STUB_BAD_CHECKSUM:-0}" = 1 ] && hash=0000000000000000000000000000000000000000000000000000000000000000
    case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; *) arch="$(uname -m)" ;; esac
    printf '%s  corral-linux-%s\\n' "$hash" "$arch" > "$out" ;;
  */corral-linux-*) printf 'corral binary' > "$out" ;;
  *) printf 'font archive' > "$out" ;;
esac
''')
    write_stub(bindir, "unzip", '''\
echo "unzip $*" >> "$HOME/calls"
archive="$2"; dest="$4"
printf font > "$dest/$(basename "$archive").font"
''')
    write_stub(bindir, "fc-cache", 'echo "fc-cache $*" >> "$HOME/calls"\n')
    write_stub(bindir, "systemctl", '''\
echo "systemctl $*" >> "$HOME/calls"
if [ "${STUB_SYSTEMCTL_FAIL:-}" = "$2" ]; then exit 1; fi
''')
    write_stub(bindir, "python3", f'''\
if [[ "$1" = */install-extensions.py ]]; then
  echo "extensions bus=${{DBUS_SESSION_BUS_ADDRESS:-}}" >> "$HOME/calls"
  exit "${{STUB_EXTENSIONS_RC:-0}}"
fi
exec "{sys.executable}" "$@"
''')
    # Redirect the only privileged destination, including when tests run as root.
    write_stub(bindir, "sudo", 'shift\nexec "$@"\n')
    write_stub(bindir, "install", '''\
if [ "${4:-}" = /etc/sysctl.d/99-zram.conf ]; then
  echo "install sysctl" >> "$HOME/calls"
  exec /usr/bin/install "$1" "$2" "$3" "$HOME/sysctl.conf"
fi
exec /usr/bin/install "$@"
''')
    write_stub(bindir, "cmp", '''\
if [ "${3:-}" = /etc/sysctl.d/99-zram.conf ]; then
  exec /usr/bin/cmp "$1" "$2" "$HOME/sysctl.conf"
fi
exec /usr/bin/cmp "$@"
''')
    write_stub(bindir, "stat", '''\
if [ "${3:-}" = /etc/sysctl.d/99-zram.conf ]; then
  exec /usr/bin/stat "$1" "$2" "$HOME/sysctl.conf"
fi
exec /usr/bin/stat "$@"
''')
    write_stub(bindir, "sysctl", 'echo "sysctl $*" >> "$HOME/calls"\n')
    return env, config


def run(env, **overrides):
    return subprocess.run(["bash", str(REPO / "units/bluefin.sh")],
                          env={**env, **overrides}, capture_output=True, text=True)


def log(env):
    path = Path(env["HOME"]) / "calls"
    return path.read_text() if path.exists() else ""


def hostvars(config, text):
    (config / "host_vars/test-desktop.yml").write_text(text)


@pytest.mark.parametrize("value", ["skip_bluefin: true\n", "machine_profile: vm-test\n"])
def test_skip_flags_precede_inventory_lookup(desktop, value):
    env, config = desktop
    hostvars(config, value)
    r = run(env, DOTFILES_IS_DESKTOP="")
    assert r.returncode == 0
    assert "SKIPPED" in r.stdout
    assert log(env) == ""


def test_non_desktop_is_skipped_without_yq(desktop):
    env, _ = desktop
    r = run(env, DOTFILES_IS_DESKTOP="false")
    assert r.returncode == 0
    assert "not a desktop" in r.stdout
    assert log(env) == ""


def test_missing_yq_is_reported_when_membership_is_unknown(desktop, tmp_path):
    env, _ = desktop
    bindir = tmp_path / "minimal-bin"
    bindir.mkdir()
    for name in ("bash", "dirname", "sed", "head"):
        (bindir / name).symlink_to(shutil.which(name))
    r = run(env, DOTFILES_IS_DESKTOP="", PATH=str(bindir))
    assert r.returncode == 1
    assert "desktop inventory requires yq" in r.stdout
    assert log(env) == ""


def test_host_desktop_override_needs_no_inventory_reader(desktop, tmp_path):
    env, config = desktop
    hostvars(config, "is_desktop: false\n")
    bindir = tmp_path / "minimal-bin"
    bindir.mkdir()
    for name in ("bash", "dirname", "sed", "head"):
        (bindir / name).symlink_to(shutil.which(name))
    r = run(env, DOTFILES_IS_DESKTOP="", PATH=str(bindir))
    assert r.returncode == 0
    assert "not a desktop" in r.stdout
    assert log(env) == ""


def test_inventory_non_desktop_is_a_clean_skip(desktop):
    env, _ = desktop
    write_stub(Path(env["PATH"].split(":")[0]), "yq", "echo false\n")
    r = run(env, DOTFILES_IS_DESKTOP="")
    assert r.returncode == 0
    assert "not a desktop" in r.stdout
    assert log(env) == ""


def test_inventory_reader_errors_are_not_a_successful_skip(desktop):
    env, _ = desktop
    write_stub(Path(env["PATH"].split(":")[0]), "yq", "exit 2\n")
    r = run(env, DOTFILES_IS_DESKTOP="")
    assert r.returncode == 1
    assert "desktop inventory lookup" in r.stdout
    assert log(env) == ""


def test_gnome_sync_and_system_changes_are_idempotent(desktop):
    env, _ = desktop
    home = Path(env["HOME"])
    retired = home / ".local/bin/tailvm"
    retired.parent.mkdir(parents=True)
    retired.write_text("old")
    first = run(env)
    assert first.returncode == 0, first.stdout + first.stderr
    assert not retired.exists()
    assert (home / ".local/bin/corral").read_bytes() == b"corral binary"
    assert (home / ".local/bin/corral").stat().st_mode & 0o777 == 0o755
    xml = (home / ".local/share/backgrounds/bluefin/01-bluefin.xml").read_text()
    assert f"{home}/.local/share/backgrounds/bluefin/a.jpg" in xml
    assert (home / ".local/share/icons/hicolor/icon").read_text() == "icon"
    assert (home / ".local/share/ublue-os/logo").read_text() == "logo"
    assert (home / ".local/share/fonts/Inter/Inter.zip.font").is_file()
    assert (home / ".local/share/fonts/JetBrainsMono/JetBrainsMono.zip.font").is_file()
    service = (home / ".config/systemd/user/bluefin-wallpaper-rotate.service").read_text()
    assert f"ExecStart={home}/.local/bin/bluefin-wallpaper-rotate.py" in service
    bus = f"unix:path=/run/user/{os.getuid()}/bus"
    assert f"Environment=DBUS_SESSION_BUS_ADDRESS={bus}" in service
    assert f"extensions bus={bus}" in log(env)
    assert "color-scheme 'prefer-dark' bus=" + bus in log(env)
    assert "vm.swappiness = 150" in (home / "sysctl.conf").read_text()
    before = log(env)
    second = run(env)
    assert second.returncode == 0, second.stdout + second.stderr
    later = log(env)[len(before):]
    assert "systemctl --user daemon-reload" not in later
    assert "install sysctl" not in later
    assert "sysctl -p" not in later
    assert "systemctl --user enable --now bluefin-wallpaper-rotate.timer" in later


def test_existing_custom_bus_is_used_for_probe_and_service(desktop):
    env, _ = desktop
    with tempfile.TemporaryDirectory(prefix="bluefin-bus-") as directory:
        path = str(Path(directory) / "bus")
        with socket.socket(socket.AF_UNIX) as session:
            session.bind(path)
            bus = f"unix:path={path}"
            r = run(env, DBUS_SESSION_BUS_ADDRESS=bus)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "session bus socket unavailable" not in r.stdout
        assert f"gsettings get org.gnome.desktop.interface color-scheme bus={bus}" in log(env)
        assert f"extensions bus={bus}" in log(env)
        service = (Path(env["HOME"]) / ".config/systemd/user/bluefin-wallpaper-rotate.service").read_text()
        assert f"Environment=DBUS_SESSION_BUS_ADDRESS={bus}" in service


def test_missing_bus_and_failed_gnome_probe_are_reported(desktop, tmp_path):
    env, _ = desktop
    r = run(env, DBUS_SESSION_BUS_ADDRESS=f"unix:path={tmp_path}/missing", STUB_GNOME_RC="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PARTIAL: session bus socket unavailable" in r.stdout
    assert "PARTIAL: GNOME session detection failed" in r.stdout
    assert "podman pull" not in log(env)


@pytest.mark.parametrize("gnome,bluefin,force,sync", [
    ("0", "0", "false", False),
    ("0", "0", "true", True),
    ("1", "1", "true", False),
    ("0", "1", "false", True),
])
def test_platform_gates_do_not_suppress_unconditional_tasks(desktop, gnome, bluefin, force, sync):
    env, config = desktop
    hostvars(config, f"force_bluefin: {force}\n")
    r = run(env, STUB_GNOME_RC=gnome, STUB_BLUEFIN_RC=bluefin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("podman pull" in log(env)) is sync
    assert ("extensions bus=" in log(env)) is sync
    assert (Path(env["HOME"]) / ".local/bin/corral").is_file()
    assert "sysctl -p" in log(env)
    assert "systemctl --user enable --now bluefin-wallpaper-rotate.timer" in log(env)


def test_missing_optional_image_asset_is_reported(desktop):
    env, _ = desktop
    r = run(env, STUB_MISSING_ICON="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PARTIAL: Bluefin image asset unavailable:" in r.stdout
    assert "icons/hicolor" in r.stdout
    assert (Path(env["HOME"]) / ".local/share/ublue-os/logo").is_file()


def test_os_detection_failure_does_not_apply_wrong_branding(desktop):
    env, _ = desktop
    r = run(env, STUB_BLUEFIN_RC="2")
    assert r.returncode == 1
    assert "detect Bluefin OS" in r.stdout
    assert "podman pull" not in log(env)


def test_failed_pull_is_visible_and_independent_steps_continue(desktop):
    env, _ = desktop
    r = run(env, STUB_PULL_RC="1")
    assert r.returncode == 1
    assert "FAIL  Bluefin branding and settings" in r.stdout
    assert (Path(env["HOME"]) / ".local/bin/corral").is_file()
    assert "sysctl -p" in log(env)


def test_invalid_corral_checksum_never_installs_binary(desktop):
    env, _ = desktop
    r = run(env, STUB_GNOME_RC="1", STUB_BAD_CHECKSUM="1")
    assert r.returncode == 1
    assert "checksum missing or mismatched" in r.stderr
    assert not (Path(env["HOME"]) / ".local/bin/corral").exists()
    assert "sysctl -p" in log(env)


def test_extensions_failure_remains_nonfatal(desktop):
    env, _ = desktop
    r = run(env, STUB_EXTENSIONS_RC="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warn  GNOME extensions" in r.stdout
    assert "sysctl -p" in log(env)
