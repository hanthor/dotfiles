import json
from pathlib import Path

from conftest import REPO, write_stub
from unit_helpers import calls, run_unit


ZEN_ID = "app.zen_browser.zen.desktop"
ASSETS = REPO / "units/zen-browser"


def setup(stub_env, desktop="1"):
    bindir, env = stub_env
    # Render and compare against a throwaway system policy, even on a host
    # that actually has Zen's system-wide Flatpak installed.
    system_policy = "/var/lib/flatpak/app/app.zen_browser.zen/current/active/files/zen/distribution/policies.json"
    write_stub(bindir, "python3", f'''\
args=("$@")
if [ "${{args[1]:-}}" = "{system_policy}" ]; then args[1]="$HOME/system-existing-policy.json"; fi
exec /usr/bin/python3 "${{args[@]}}"
''')
    write_stub(bindir, "cmp", f'''\
args=("$@")
if [ "${{args[2]:-}}" = "{system_policy}" ]; then args[2]="$HOME/system-existing-policy.json"; fi
exec /usr/bin/cmp "${{args[@]}}"
''')
    write_stub(bindir, "stat", f'''\
if [ "${{3:-}}" = "{system_policy}" ]; then echo 644:0:0; else exec /usr/bin/stat "$@"; fi
''')
    env.update(DOTFILES_IS_DESKTOP=desktop, DOTFILES_MACHINE="zen-unit-test",
               DBUS_SESSION_BUS_ADDRESS="", XDG_RUNTIME_DIR="")
    write_stub(bindir, "id", 'if [ "$1" = -u ]; then echo 1234; else /usr/bin/id "$@"; fi\n')
    write_stub(bindir, "gsettings", '''\
echo "gsettings $* DBUS=$DBUS_SESSION_BUS_ADDRESS RUNTIME=$XDG_RUNTIME_DIR" >> "$HOME/calls"
if [ "$1" = get ]; then
  if [ -f "$HOME/dock" ]; then cat "$HOME/dock"; else echo "['org.mozilla.firefox.desktop', 'other.desktop', 'org.mozilla.Thunderbird.desktop']"; fi
else printf '%s\\n' "$4" > "$HOME/dock"; fi
''')
    write_stub(bindir, "xdg-mime", 'echo "xdg-mime $*" >> "$HOME/calls"\nexit "${MIME_RC:-0}"\n')
    write_stub(bindir, "sudo", '''\
echo "sudo $*" >> "$HOME/calls"
[ "${SUDO_RC:-0}" = 0 ] || exit "$SUDO_RC"
case " $* " in *" -d "*) exit 0 ;; esac
for arg in "$@"; do previous="${current:-}"; current="$arg"; done
cp "$previous" "$HOME/system-policy.json" && cp "$previous" "$HOME/system-existing-policy.json"
''')
    return env


def profile(env, path="abc.default", is_relative=True):
    base = Path(env["HOME"]) / ".var/app/app.zen_browser.zen/.zen"
    base.mkdir(parents=True, exist_ok=True)
    target = base / path if is_relative else Path(path)
    target.mkdir(parents=True, exist_ok=True)
    (base / "profiles.ini").write_text(
        f"[Profile0]\nIsRelative={int(is_relative)}\nPath={path}\n"
    )
    return target


def test_desktop_preferences_policy_and_dock_are_idempotent(stub_env):
    env = setup(stub_env)
    target = profile(env)
    user_js = target / "user.js"
    user_js.write_text('user_pref("custom.preference", 42);\n')
    user_policy = Path(env["HOME"]) / ".zen/distribution/policies.json"
    user_policy.parent.mkdir(parents=True)
    user_policy.write_text(json.dumps({"policies": {"DisableTelemetry": True,
        "Extensions": {"Install": ["https://example.test/other.xpi"]}}}))

    result = run_unit("zen-browser", env)
    assert result.returncode == 0, result.stdout + result.stderr
    contents = user_js.read_text()
    assert contents.startswith('user_pref("custom.preference", 42);\n')
    assert (ASSETS / "user.js").read_text().rstrip() in contents
    assert user_js.stat().st_mode & 0o777 == 0o644
    policy = json.loads(user_policy.read_text())["policies"]
    assert policy["DisableTelemetry"] is True
    assert policy["Extensions"]["Install"][0] == "https://example.test/other.xpi"
    assert len(policy["Extensions"]["Install"]) == 2
    assert policy["ExtensionSettings"]["{446900e4-71c2-419f-a6a7-df9c091e268b}"]["installation_mode"] == "force_installed"
    assert json.loads((Path(env["HOME"]) / "system-policy.json").read_text()) == json.loads((ASSETS / "policies.json").read_text())
    log = calls(env)
    assert "DBUS=unix:path=/run/user/1234/bus RUNTIME=/run/user/1234" in log
    assert (Path(env["HOME"]) / "dock").read_text().strip() == "['app.zen_browser.zen.desktop', 'other.desktop']"
    assert log.count("xdg-mime default") == 7
    assert "sudo -n install -d -m 0755 -o root -g root" in log
    assert "sudo -n install -m 0644 -o root -g root" in log

    before = user_js.read_bytes(), user_policy.read_bytes()
    result = run_unit("zen-browser", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (user_js.read_bytes(), user_policy.read_bytes()) == before
    assert calls(env).count("gsettings set") == 1
    assert calls(env).count("sudo -n install -m 0644") == 1


def test_missing_profile_and_host_gates_do_not_change_profiles(stub_env):
    env = setup(stub_env)
    result = run_unit("zen-browser", env)
    assert result.returncode == 0 and "profiles.ini not found" in result.stdout
    assert "sudo" not in calls(env) and "xdg-mime" not in calls(env)
    for overrides in ({"DOTFILES_IS_DESKTOP": "0"},
                      {"DOTFILES_MACHINE": "mumbai"},
                      {"DOTFILES_MACHINE": "test-fleet-fedora"}):
        (Path(env["HOME"]) / "calls").unlink(missing_ok=True)
        result = run_unit("zen-browser", env, **overrides)
        assert result.returncode == 0 and "SKIPPED" in result.stdout
        assert not calls(env)


def test_inventory_errors_are_not_silent_non_desktop(stub_env):
    env = setup(stub_env, desktop="")
    bindir = stub_env[0]
    write_stub(bindir, "yq", 'echo "inventory unavailable" >&2\nexit 2\n')
    result = run_unit("zen-browser", env)
    assert result.returncode == 1
    assert "FAIL  desktop inventory" in result.stdout
    assert not calls(env)


def test_absolute_profile_and_existing_managed_preferences(stub_env, tmp_path):
    env = setup(stub_env)
    target = profile(env, str(tmp_path / "absolute profile"), is_relative=False)
    user_js = target / "user.js"
    user_js.write_text((ASSETS / "user.js").read_text())
    result = run_unit("zen-browser", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert user_js.read_text() == (ASSETS / "user.js").read_text()


def test_broken_profile_and_sudo_failure_are_reported(stub_env):
    env = setup(stub_env)
    target = profile(env)
    (target.parent / "profiles.ini").write_text("[Profile0]\nPath=missing\n")
    result = run_unit("zen-browser", env, SUDO_RC="1")
    assert result.returncode == 1
    assert "FAIL  Zen profile preferences" in result.stdout
    assert "FAIL  Flatpak Zen policy" in result.stdout
    assert not (target.parent / "missing").exists()
    assert (Path(env["HOME"]) / ".zen/distribution/policies.json").exists()


def test_malformed_existing_policy_is_not_overwritten(stub_env):
    env = setup(stub_env)
    profile(env)
    policy = Path(env["HOME"]) / ".zen/distribution/policies.json"
    policy.parent.mkdir(parents=True)
    policy.write_text("not json")
    result = run_unit("zen-browser", env)
    assert result.returncode == 1
    assert "FAIL  user Zen policy" in result.stdout
    assert policy.read_text() == "not json"


def test_default_browser_failure_is_soft_and_reports_warning(stub_env):
    env = setup(stub_env)
    profile(env)
    result = run_unit("zen-browser", env, MIME_RC="1")
    assert result.returncode == 0
    assert "warn  default browser" in result.stdout
    assert calls(env).count("xdg-mime default") == 7


def test_system_policy_preserves_existing_settings(stub_env):
    env = setup(stub_env)
    profile(env)
    existing = Path(env["HOME"]) / "system-existing-policy.json"
    existing.write_text(json.dumps({"policies": {"DisableTelemetry": True,
        "ExtensionSettings": {"custom@example": {"installation_mode": "allowed"}}}}))
    result = run_unit("zen-browser", env)
    assert result.returncode == 0, result.stdout + result.stderr
    policies = json.loads(existing.read_text())["policies"]
    assert policies["DisableTelemetry"] is True
    assert policies["ExtensionSettings"]["custom@example"]["installation_mode"] == "allowed"
    assert policies["ExtensionSettings"]["{446900e4-71c2-419f-a6a7-df9c091e268b}"]["installation_mode"] == "force_installed"


def test_bad_preference_markers_do_not_destroy_custom_file(stub_env):
    env = setup(stub_env)
    user_js = profile(env) / "user.js"
    original = '// BEGIN dotfiles Zen preferences\nuser_pref("custom", true);\n'
    user_js.write_text(original)
    result = run_unit("zen-browser", env)
    assert result.returncode == 1 and "FAIL  Zen profile preferences" in result.stdout
    assert user_js.read_text() == original


def test_inventory_membership_controls_desktop_gate(stub_env):
    env = setup(stub_env, desktop="")
    bindir = stub_env[0]
    write_stub(bindir, "yq", 'echo "${DESKTOP_RESULT:-false}"\n')
    result = run_unit("zen-browser", env)
    assert result.returncode == 0 and "not a desktop" in result.stdout
    assert not calls(env)
    result = run_unit("zen-browser", env, DESKTOP_RESULT="true")
    assert result.returncode == 0 and "gsettings get" in calls(env)


def test_dock_uses_inherited_session(stub_env):
    env = setup(stub_env)
    result = run_unit("zen-browser", env, DBUS_SESSION_BUS_ADDRESS="unix:path=/custom/bus",
                      XDG_RUNTIME_DIR="/custom/runtime")
    assert result.returncode == 0
    assert "DBUS=unix:path=/custom/bus RUNTIME=/custom/runtime" in calls(env)


def test_dock_bus_falls_back_to_inherited_runtime(stub_env):
    env = setup(stub_env)
    result = run_unit("zen-browser", env, XDG_RUNTIME_DIR="/custom/runtime")
    assert result.returncode == 0
    assert "DBUS=unix:path=/custom/runtime/bus RUNTIME=/custom/runtime" in calls(env)
