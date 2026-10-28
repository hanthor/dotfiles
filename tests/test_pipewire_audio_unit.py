from pathlib import Path
import shutil
import shlex
import subprocess

from conftest import REPO, write_stub
from unit_helpers import calls, run_unit


def setup(stub_env, machine="himachal"):
    bindir, env = stub_env
    # Do not let the host's package managers or Flatpak influence the test.
    for name in ("bash", "cat", "chmod", "cmp", "dirname", "head", "install",
                 "mkdir", "mktemp", "rm", "rmdir", "sed", "stat", "touch"):
        (bindir / name).symlink_to(shutil.which(name))
    for key in ("MIC_HARDWARE_VOLUME_PCT", "FIND_FAIL", "RNNOISE", "LV2", "LV2_FAIL", "GNOME_VOLUME",
                "SESSION_FAIL", "RESTART_FAIL", "MIC_LOAD", "FLATPAK_RUNNING", "FLATPAK_INSTALLED",
                "RPM_INSTALLED", "YQ_RESULT", "YQ_RC", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        env.pop(key, None)
    env.update(PATH=str(bindir), DOTFILES_MACHINE=machine, DOTFILES_IS_DESKTOP="1")
    write_stub(bindir, "id", 'echo 1000\n')
    # Arch hosts must not run a real pacman transaction during these tests.
    write_stub(bindir, "pacman", 'exit 0\n')
    write_stub(bindir, "find", '''\
[ "${FIND_FAIL:-0}" = 0 ] || exit 1
[ "${RNNOISE:-1}" = 0 ] || echo /usr/lib/ladspa/librnnoise_ladspa.so
''')
    write_stub(bindir, "lv2ls", '''\
[ "${LV2_FAIL:-0}" = 0 ] || exit 1
[ "${LV2:-1}" = 0 ] || echo http://lsp-plug.in/plugins/lv2/para_equalizer_x16_lr
''')
    write_stub(bindir, "gsettings", '''\
echo "gsettings $*" >> "$HOME/calls"
echo "gsettings-bus $DBUS_SESSION_BUS_ADDRESS" >> "$HOME/calls"
[ "$1" != get ] || echo "${GNOME_VOLUME:-true}"
''')
    write_stub(bindir, "systemctl", '''\
echo "systemctl $*" >> "$HOME/calls"
echo "session $XDG_RUNTIME_DIR $DBUS_SESSION_BUS_ADDRESS" >> "$HOME/calls"
[ "${SESSION_FAIL:-0}" = 0 ] || exit 1
shift
case "$1" in
  list-unit-files|list-units) [ "${MIC_LOAD:-not-found}" = loaded ] && echo mic-dsp-link.service; : ;;
  is-enabled) [ -e "$HOME/.mic-enabled" ] ;;
  is-active) [ -e "$HOME/.mic-active" ] ;;
  enable) touch "$HOME/.mic-enabled" ;;
  disable) rm -f "$HOME/.mic-enabled" ;;
  start) touch "$HOME/.mic-active" ;;
  stop) rm -f "$HOME/.mic-active" ;;
  restart) [ "${RESTART_FAIL:-0}" = 0 ] || exit 1 ;;
esac
''')
    write_stub(bindir, "flatpak", '''\
echo "flatpak $*" >> "$HOME/calls"
case "$1" in
  ps) [ "${FLATPAK_RUNNING:-0}" = 0 ] || echo com.github.wwmm.easyeffects ;;
  list) [ "${FLATPAK_INSTALLED:-0}" = 0 ] || echo com.github.wwmm.easyeffects ;;
esac
''')
    write_stub(bindir, "sudo", '''\
echo "sudo $*" >> "$HOME/calls"
[ "$1" = -n ] && shift
"$@"
''')
    return env


def home(env, path):
    return Path(env["HOME"]) / path


def asset(name):
    return (REPO / "units/pipewire-audio/files" / name).read_bytes()


def test_full_chain_host_volume_services_and_idempotence(stub_env):
    env = setup(stub_env)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert home(env, ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf").read_bytes() == asset("speaker-dsp.conf")
    assert home(env, ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf").read_bytes() == asset("mic-rnnoise.conf")
    service = home(env, ".config/systemd/user/mic-dsp-link.service").read_text()
    assert "set-source-volume $$HW_MIC 75%%" in service
    assert "{{" not in service
    assert "systemctl --user enable mic-dsp-link.service" in calls(env)
    assert "systemctl --user start mic-dsp-link.service" in calls(env)
    assert "systemctl --user restart pipewire pipewire-pulse.socket" in calls(env)
    assert "session /run/user/1000 unix:path=/run/user/1000/bus" in calls(env)
    before = calls(env)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    after = calls(env)[len(before):]
    assert "daemon-reload" not in after
    assert " restart " not in after
    assert " start " not in after
    assert " enable " not in after


def test_original_ansible_microphone_service_is_migrated(stub_env):
    env = setup(stub_env)
    service = home(env, ".config/systemd/user/mic-dsp-link.service")
    service.parent.mkdir(parents=True)
    template = (REPO / "units/pipewire-audio/templates/mic-dsp-link.service.j2").read_text()
    original = template.replace("cut -f 2", 'awk "{print $$2}"').replace("%%", "%")
    service.write_text(original.replace("{{ mic_hardware_volume_pct | default(100) }}", "75"))
    home(env, ".mic-active").touch()
    home(env, ".mic-enabled").touch()
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert service.read_text() == template.replace("{{ mic_hardware_volume_pct | default(100) }}", "75")
    assert "systemctl --user restart mic-dsp-link.service" in calls(env)


def test_rendered_microphone_command_routes_named_source(stub_env):
    env = setup(stub_env)
    bindir = Path(env["PATH"])
    for name in ("grep", "cut"):
        (bindir / name).symlink_to(shutil.which(name))
    write_stub(bindir, "pactl", '''\
if [ "$*" = "list short sources" ]; then
  printf '42\\talsa_input.pci-test.analog-stereo\\tPipeWire\\ts16le 2ch 48000Hz\\tRUNNING\\n'
else
  echo "pactl $*" >> "$HOME/mic-calls"
fi
''')
    write_stub(bindir, "pw-link", 'echo "pw-link $*" >> "$HOME/mic-calls"\n')
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    service = home(env, ".config/systemd/user/mic-dsp-link.service").read_text()
    assert "$$HW_MIC 75%%" in service
    command = service.split("ExecStart=", 1)[1].split("\nRemainAfterExit=", 1)[0].replace("\\\n", "")
    # Model systemd's literal specifier and dollar escaping before sh executes.
    args = shlex.split(command.replace("%%", "%").replace("$$", "$"))
    result = subprocess.run(args, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    logged = home(env, "mic-calls").read_text().splitlines()
    assert "pactl set-source-volume alsa_input.pci-test.analog-stereo 75%" in logged
    assert "pw-link alsa_input.pci-test.analog-stereo:capture_FL effect_input.rnnoise:input_FL" in logged
    assert "pw-link alsa_input.pci-test.analog-stereo:capture_FR effect_input.rnnoise:input_FR" in logged
    assert "pactl set-default-source effect_output.rnnoise" in logged


def test_builtin_eq_absent_mic_and_user_owned_data_survive(stub_env):
    env = setup(stub_env)
    config = home(env, ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf")
    config.parent.mkdir(parents=True)
    config.write_bytes(asset("mic-rnnoise.conf"))
    directory = home(env, ".config/wireplumber/main.lua.d")
    directory.mkdir(parents=True)
    (directory / "51-speaker-dsp-default.lua").write_bytes(asset("51-speaker-dsp-default.lua"))
    (directory / "my-rule.lua").write_text("user rule")
    preset = home(env, ".var/app/com.github.wwmm.easyeffects/config/preset.json")
    preset.parent.mkdir(parents=True)
    preset.write_text("user preset")
    home(env, ".mic-active").touch()
    home(env, ".mic-enabled").touch()
    service = home(env, ".config/systemd/user/mic-dsp-link.service")
    service.parent.mkdir(parents=True)
    template = (REPO / "units/pipewire-audio/templates/mic-dsp-link.service.j2").read_text()
    service.write_text(template.replace("{{ mic_hardware_volume_pct | default(100) }}", "75"))
    result = run_unit("pipewire-audio", env, RNNOISE="0", LV2="0", MIC_LOAD="loaded")
    assert result.returncode == 0, result.stdout + result.stderr
    assert home(env, ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf").read_bytes() == asset("speaker-biquad.conf")
    assert not config.exists()
    assert not (directory / "51-speaker-dsp-default.lua").exists()
    assert (directory / "my-rule.lua").read_text() == "user rule"
    assert preset.read_text() == "user preset"
    assert "systemctl --user stop mic-dsp-link.service" in calls(env)
    assert "systemctl --user disable mic-dsp-link.service" in calls(env)
    assert "systemctl --user restart wireplumber" in calls(env)


def test_mic_search_failure_preserves_config_and_service(stub_env):
    env = setup(stub_env)
    config = home(env, ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf")
    config.parent.mkdir(parents=True)
    config.write_text("existing mic config")
    result = run_unit("pipewire-audio", env, FIND_FAIL="1")
    assert result.returncode == 1
    assert config.read_text() == "existing mic config"
    assert "PARTIAL: microphone DSP unchanged" in result.stdout
    assert "mic-dsp-link.service" not in calls(env)


def test_search_failure_defers_relink_after_daemon_restart(stub_env):
    env = setup(stub_env)
    assert run_unit("pipewire-audio", env).returncode == 0
    state = home(env, ".local/state/pipewire-audio")
    (state / "pipewire").touch()
    before = calls(env)
    result = run_unit("pipewire-audio", env, FIND_FAIL="1")
    assert result.returncode == 1
    assert "systemctl --user restart pipewire" in calls(env)[len(before):]
    assert "mic-dsp-link.service" not in calls(env)[len(before):]
    assert (state / "mic").exists()
    before = calls(env)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "systemctl --user restart mic-dsp-link.service" in calls(env)[len(before):]
    assert not (state / "mic").exists()


def test_session_failure_retries_pending_restarts(stub_env):
    env = setup(stub_env)
    first = run_unit("pipewire-audio", env, SESSION_FAIL="1")
    assert first.returncode == 1
    assert home(env, ".local/state/pipewire-audio/pipewire").exists()
    assert home(env, ".local/state/pipewire-audio/mic").exists()
    second = run_unit("pipewire-audio", env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "systemctl --user restart pipewire pipewire-pulse.socket" in calls(env)
    assert not home(env, ".local/state/pipewire-audio/pipewire").exists()
    assert not home(env, ".local/state/pipewire-audio/mic").exists()


def test_audio_daemon_restarts_relink_managed_microphone_and_retry(stub_env):
    env = setup(stub_env)
    assert run_unit("pipewire-audio", env).returncode == 0
    state = home(env, ".local/state/pipewire-audio")
    for daemon in ("pipewire", "wireplumber"):
        (state / daemon).touch()
        before = calls(env)
        result = run_unit("pipewire-audio", env, RESTART_FAIL="1")
        assert result.returncode == 1
        assert (state / daemon).exists()
        assert (state / "mic").exists()
        assert "systemctl --user restart mic-dsp-link.service" not in calls(env)[len(before):]
        before = calls(env)
        result = run_unit("pipewire-audio", env)
        assert result.returncode == 0, result.stdout + result.stderr
        actions = calls(env)[len(before):]
        assert f"systemctl --user restart {daemon}" in actions
        assert "systemctl --user restart mic-dsp-link.service" in actions
        assert actions.index(f"systemctl --user restart {daemon}") < actions.index("systemctl --user restart mic-dsp-link.service")
        assert not (state / daemon).exists()
        assert not (state / "mic").exists()


def test_audio_daemon_restart_does_not_run_custom_microphone_service(stub_env):
    env = setup(stub_env)
    assert run_unit("pipewire-audio", env).returncode == 0
    service = home(env, ".config/systemd/user/mic-dsp-link.service")
    service.write_text("[Service]\nExecStart=/custom/microphone\n")
    state = home(env, ".local/state/pipewire-audio")
    (state / "pipewire").touch()
    before = calls(env)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "systemctl --user restart pipewire" in calls(env)[len(before):]
    assert "mic-dsp-link.service" not in calls(env)[len(before):]
    assert not (state / "mic").exists()


def test_gates_and_missing_inventory_parser(stub_env):
    env = setup(stub_env, "mumbai")
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not calls(env)
    env["DOTFILES_MACHINE"] = "test-fleet-fedora"
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    env["DOTFILES_MACHINE"] = "himachal"
    env["DOTFILES_IS_DESKTOP"] = "0"
    assert "SKIPPED" in run_unit("pipewire-audio", env).stdout
    env.pop("DOTFILES_IS_DESKTOP")
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 1 and "requires yq" in result.stdout
    assert not calls(env)


def test_inventory_detection_and_parser_errors(stub_env):
    env = setup(stub_env)
    env.pop("DOTFILES_IS_DESKTOP")
    bindir = Path(env["PATH"])
    write_stub(bindir, "yq", 'echo "${YQ_RESULT:-true}"\nexit "${YQ_RC:-0}"\n')
    result = run_unit("pipewire-audio", env, YQ_RESULT="false")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    result = run_unit("pipewire-audio", env, YQ_RC="2")
    assert result.returncode == 1 and "read desktop inventory" in result.stdout
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr


def test_changed_volume_restarts_mic_and_invalid_override_fails(stub_env):
    env = setup(stub_env)
    assert run_unit("pipewire-audio", env).returncode == 0
    before = calls(env)
    result = run_unit("pipewire-audio", env, MIC_HARDWARE_VOLUME_PCT="50")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "set-source-volume $$HW_MIC 50%%" in home(env, ".config/systemd/user/mic-dsp-link.service").read_text()
    assert "systemctl --user restart mic-dsp-link.service" in calls(env)[len(before):]
    before = calls(env)
    result = run_unit("pipewire-audio", env, MIC_HARDWARE_VOLUME_PCT="101")
    assert result.returncode == 1 and "invalid mic_hardware_volume_pct" in result.stdout
    assert calls(env) == before


def test_system_package_and_flatpak_changes(stub_env):
    env = setup(stub_env)
    bindir = Path(env["PATH"])
    write_stub(bindir, "dnf", 'echo "dnf $*" >> "$HOME/calls"\n')
    write_stub(bindir, "rpm", 'exit "${RPM_INSTALLED:-1}"\n')
    result = run_unit("pipewire-audio", env, FLATPAK_RUNNING="1", FLATPAK_INSTALLED="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sudo -n dnf install -y lsp-plugins-lv2 noise-suppression-for-voice" in calls(env)
    assert "flatpak kill com.github.wwmm.easyeffects" in calls(env)
    assert "sudo -n flatpak uninstall --system -y com.github.wwmm.easyeffects" in calls(env)
    before = calls(env)
    result = run_unit("pipewire-audio", env, RPM_INSTALLED="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dnf install" not in calls(env)[len(before):]


def test_ostree_package_failure_is_reported_but_audio_continues(stub_env):
    env = setup(stub_env)
    bindir = Path(env["PATH"])
    write_stub(bindir, "rpm", 'exit 1\n')
    write_stub(bindir, "rpm-ostree", 'echo "rpm-ostree $*" >> "$HOME/calls"\nexit 1\n')
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 1 and "FAIL  DSP prerequisite packages" in result.stdout
    assert "sudo -n rpm-ostree install --apply-live --idempotent" in calls(env)
    assert home(env, ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf").exists()


def test_bootc_never_installs_packages_and_ostree_takes_priority(stub_env):
    env = setup(stub_env)
    bindir = Path(env["PATH"])
    write_stub(bindir, "rpm", 'exit 1\n')
    write_stub(bindir, "dnf", 'echo "dnf $*" >> "$HOME/calls"\n')
    write_stub(bindir, "rpm-ostree", 'echo "rpm-ostree $*" >> "$HOME/calls"\n')
    write_stub(bindir, "bootc", 'exit 0\n')
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bootc DSP prerequisites must be provided by the image" in result.stdout
    assert "dnf install" not in calls(env)
    assert "rpm-ostree install" not in calls(env)
    (bindir / "bootc").unlink()
    before = calls(env)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rpm-ostree install --apply-live --idempotent" in calls(env)[len(before):]
    assert "dnf install" not in calls(env)[len(before):]


def test_default_mic_volume_and_gnome_setting(stub_env):
    env = setup(stub_env, "kanpur")
    result = run_unit("pipewire-audio", env, GNOME_VOLUME="false", DBUS_SESSION_BUS_ADDRESS="unix:path=/custom/bus")
    assert result.returncode == 0, result.stdout + result.stderr
    service = home(env, ".config/systemd/user/mic-dsp-link.service").read_text()
    assert "set-source-volume $$HW_MIC 100%%" in service
    assert "gsettings set org.gnome.desktop.sound allow-volume-above-100-percent true" in calls(env)
    assert "gsettings-bus unix:path=/custom/bus" in calls(env)


def test_missing_plugin_and_service_are_not_an_error(stub_env):
    env = setup(stub_env)
    result = run_unit("pipewire-audio", env, RNNOISE="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "systemctl --user stop mic-dsp-link.service" not in calls(env)
    assert "systemctl --user disable mic-dsp-link.service" not in calls(env)


def test_custom_audio_files_and_service_are_preserved(stub_env):
    env = setup(stub_env)
    paths = [
        ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf",
        ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf",
        ".config/systemd/user/pipewire.service.d/ladspa-path.conf",
        ".config/systemd/user/mic-dsp-link.service",
        ".config/wireplumber/main.lua.d/51-speaker-dsp-default.lua",
    ]
    for path in paths:
        target = home(env, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("custom " + path)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    for path in paths:
        assert home(env, path).read_text() == "custom " + path
        assert path in result.stdout
    assert "systemctl --user start mic-dsp-link.service" not in calls(env)
    assert "systemctl --user restart wireplumber" not in calls(env)
    result = run_unit("pipewire-audio", env, RNNOISE="0", LV2="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert home(env, paths[1]).read_text() == "custom " + paths[1]
    assert home(env, paths[0]).read_text() == "custom " + paths[0]
    assert "systemctl --user stop mic-dsp-link.service" not in calls(env)


def test_custom_service_is_not_started_with_managed_mic_config(stub_env):
    env = setup(stub_env)
    service = home(env, ".config/systemd/user/mic-dsp-link.service")
    service.parent.mkdir(parents=True)
    service.write_text("[Service]\nExecStart=/custom/microphone\n")
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert service.read_text() == "[Service]\nExecStart=/custom/microphone\n"
    assert "retained custom microphone link service" in result.stdout
    assert home(env, ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf").read_bytes() == asset("mic-rnnoise.conf")
    assert "systemctl --user enable mic-dsp-link.service" not in calls(env)
    assert "systemctl --user start mic-dsp-link.service" not in calls(env)


def test_unknown_lv2_preserves_existing_speaker_and_fresh_falls_back(stub_env):
    env = setup(stub_env)
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    speaker = home(env, ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf")
    assert speaker.read_bytes() == asset("speaker-dsp.conf")
    result = run_unit("pipewire-audio", env, LV2_FAIL="1")
    assert result.returncode == 0 and "LSP availability is unknown" in result.stdout
    assert speaker.read_bytes() == asset("speaker-dsp.conf")
    result = run_unit("pipewire-audio", env, LV2="0")
    assert result.returncode == 0 and speaker.read_bytes() == asset("speaker-biquad.conf")
    speaker.unlink()
    Path(env["PATH"], "lv2ls").unlink()
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0 and "LSP availability is unknown" in result.stdout
    assert speaker.read_bytes() == asset("speaker-biquad.conf")


def test_mic_default_and_group_then_host_precedence(stub_env, tmp_path):
    env = setup(stub_env, "audio-test")
    source = tmp_path / "source"
    assets = source / "units/pipewire-audio"
    (assets / "defaults").mkdir(parents=True)
    (assets / "defaults/main.yml").write_text("mic_hardware_volume_pct: 93\n")
    (assets / "files").symlink_to(REPO / "units/pipewire-audio/files", target_is_directory=True)
    (assets / "templates").symlink_to(REPO / "units/pipewire-audio/templates", target_is_directory=True)
    groups = source / "group_vars"
    groups.mkdir()
    hosts = source / "host_vars"
    hosts.mkdir()

    def apply(expected, **extra):
        result = run_unit("pipewire-audio", env, DOTFILES_DIR=str(source), **extra)
        assert result.returncode == 0, result.stdout + result.stderr
        service = home(env, ".config/systemd/user/mic-dsp-link.service").read_text()
        assert f"set-source-volume $$HW_MIC {expected}%%" in service

    apply(93)
    (groups / "all.yml").write_text("mic_hardware_volume_pct: 64\n")
    apply(64)
    (groups / "desktop.yml").write_text("mic_hardware_volume_pct: 42\n")
    apply(42)
    (groups / "special.yml").write_text("mic_hardware_volume_pct: 39\n")
    result = run_unit("pipewire-audio", env, DOTFILES_DIR=str(source))
    assert result.returncode == 1 and "requires yq" in result.stderr
    write_stub(Path(env["PATH"]), "yq", 'echo true\n')
    apply(39)
    (hosts / "audio-test.yml").write_text("mic_hardware_volume_pct: 37\n")
    apply(37)
    apply(29, MIC_HARDWARE_VOLUME_PCT="29")
