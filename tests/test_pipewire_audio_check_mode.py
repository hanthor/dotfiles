from pathlib import Path

import pytest

from conftest import REPO, write_stub
from test_pipewire_audio_unit import asset, home, setup
from unit_helpers import run_unit


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.lstat().st_mode & 0o777,
            path.read_bytes() if path.is_file() else None,
        )
        for path in root.rglob("*")
    }


def prepare_check(stub_env, tmp_path):
    env = setup(stub_env)
    env.update(UNITS_CHECK="1", CHECK_LOG=str(tmp_path / "audio-calls"))
    bindir = Path(env["PATH"])
    write_stub(bindir, "systemctl", '''
echo "systemctl $*" >> "$CHECK_LOG"
[ "${SESSION_FAIL:-0}" = 0 ] || exit 1
case "$2" in
  show-environment) ;;
  show)
    [ "${SERVICE_FAIL:-0}" = 0 ] || exit 1
    printf 'LoadState=%s\\nActiveState=%s\\nUnitFileState=%s\\n' "${LOAD_STATE:-loaded}" "${ACTIVE_STATE:-active}" "${ENABLED_STATE:-enabled}"
    ;;
  *) echo "unexpected mutating systemctl" >> "$CHECK_LOG"; exit 1 ;;
esac
''')
    write_stub(bindir, "gsettings", '''
echo "gsettings $*" >> "$CHECK_LOG"
[ "$1" = get ] || exit 1
[ "${GSETTINGS_FAIL:-0}" = 0 ] || exit 1
echo "${GNOME_VOLUME:-true}"
''')
    write_stub(bindir, "flatpak", '''
echo "flatpak $*" >> "$CHECK_LOG"
[ "${FLATPAK_FAIL:-0}" = 0 ] || exit 1
case "$1" in
  ps) [ "${FLATPAK_RUNNING:-0}" = 0 ] || echo com.github.wwmm.easyeffects ;;
  list) [ "${FLATPAK_INSTALLED:-0}" = 0 ] || echo com.github.wwmm.easyeffects ;;
  *) exit 1 ;;
esac
''')
    write_stub(bindir, "sudo", 'echo "unexpected sudo $*" >> "$CHECK_LOG"; exit 1\n')
    return env


def put(env, path, data, mode=0o644):
    target = home(env, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(mode)
    return target


def managed_files(env):
    put(env, ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf", asset("speaker-dsp.conf"))
    put(env, ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf", asset("mic-rnnoise.conf"))
    put(env, ".config/systemd/user/pipewire.service.d/ladspa-path.conf", (
        b"[Service]\nEnvironment=LADSPA_PATH=%h/.ladspa:/usr/lib/x86_64-linux-gnu/ladspa:/usr/lib/ladspa:/usr/lib64/ladspa\n"
    ))
    template = (REPO / "units/pipewire-audio/templates/mic-dsp-link.service.j2").read_text()
    put(env, ".config/systemd/user/mic-dsp-link.service", template.replace(
        "{{ mic_hardware_volume_pct | default(100) }}", "75"
    ).encode())
    for path in (".config/pipewire/filter-chain.conf.d", ".ladspa", ".local/state/pipewire-audio"):
        home(env, path).mkdir(parents=True, exist_ok=True)


def test_check_clean_audio_has_no_changes(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD" not in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    log = Path(env["CHECK_LOG"]).read_text()
    assert "systemctl --user show-environment" in log
    assert "unexpected" not in log


def test_check_audio_reports_drift_and_preserves_owned_and_custom_files(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    speaker = home(env, ".config/pipewire/pipewire.conf.d/50-speaker-dsp.conf")
    speaker.write_text("user-owned speaker config")
    mic = home(env, ".config/pipewire/pipewire.conf.d/60-mic-dsp.conf")
    mic.chmod(0o600)
    put(env, ".config/wireplumber/main.lua.d/51-speaker-dsp-default.lua", asset("51-speaker-dsp-default.lua"))
    put(env, ".config/autostart/com.github.wwmm.easyeffects.desktop", b"obsolete\n")
    home(env, ".local/state/pipewire-audio/mic").touch()
    env.update(GNOME_VOLUME="false", FLATPAK_RUNNING="1", FLATPAK_INSTALLED="1", ENABLED_STATE="disabled")
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in (
        "retained custom audio config", "WOULD install audio config", "WOULD remove audio config",
        "WOULD reload user service definitions", "WOULD restart PipeWire", "WOULD restart WirePlumber",
        "WOULD enable microphone link service", "WOULD restart microphone link service",
        "WOULD enable GNOME over-amplification", "WOULD remove Easy Effects autostart",
        "WOULD stop Easy Effects Flatpak", "WOULD uninstall Easy Effects Flatpak",
    ):
        assert expected in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert "unexpected" not in Path(env["CHECK_LOG"]).read_text()


def test_check_absent_plugin_plans_removal_and_disable(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    env.update(RNNOISE="0", LV2="0")
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD remove audio config" in result.stdout
    assert "WOULD stop microphone link service" in result.stdout
    assert "WOULD disable microphone link service" in result.stdout
    assert snapshot(Path(env["HOME"])) == before


def test_check_plans_original_microphone_service_migration(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    service = home(env, ".config/systemd/user/mic-dsp-link.service")
    original = service.read_text().replace("cut -f 2", 'awk "{print $$2}"').replace("%%", "%")
    service.write_text(original)
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD install microphone link service" in result.stdout
    assert "WOULD restart microphone link service" in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert "unexpected" not in Path(env["CHECK_LOG"]).read_text()


@pytest.mark.parametrize("daemon", ["pipewire", "wireplumber"])
def test_check_daemon_restart_plans_managed_microphone_relink(stub_env, tmp_path, daemon):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    home(env, f".local/state/pipewire-audio/{daemon}").touch()
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD restart microphone link service" in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert "unexpected" not in Path(env["CHECK_LOG"]).read_text()


def test_check_bootc_does_not_plan_package_installation(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    bindir = Path(env["PATH"])
    write_stub(bindir, "bootc", 'exit 0\n')
    write_stub(bindir, "dnf", 'echo "unexpected dnf $*" >> "$CHECK_LOG"; exit 1\n')
    write_stub(bindir, "rpm", 'echo "unexpected rpm $*" >> "$CHECK_LOG"; exit 1\n')
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bootc DSP prerequisites must be provided by the image" in result.stdout
    assert "WOULD install DSP package" not in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert "unexpected" not in Path(env["CHECK_LOG"]).read_text()


@pytest.mark.parametrize("error", ["FIND_FAIL", "LV2_FAIL", "SESSION_FAIL", "SERVICE_FAIL", "GSETTINGS_FAIL", "FLATPAK_FAIL"])
def test_check_inspection_errors_fail_without_mutation(stub_env, tmp_path, error):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    env[error] = "1"
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode != 0 and "FAIL" in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    if Path(env["CHECK_LOG"]).exists():
        assert "unexpected" not in Path(env["CHECK_LOG"]).read_text()


def test_check_inspects_missing_packages_and_rpm_errors(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    bindir = Path(env["PATH"])
    write_stub(bindir, "dnf", 'echo "unexpected dnf $*" >> "$CHECK_LOG"; exit 1\n')
    write_stub(bindir, "rpm", '''
[ "${RPM_ERROR:-0}" = 0 ] || { echo "database failure" >&2; exit 1; }
echo "package $2 is not installed"
exit 1
''')
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD install DSP package lsp-plugins-lv2" in result.stdout
    assert "WOULD install DSP package noise-suppression-for-voice" in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    env["RPM_ERROR"] = "1"
    result = run_unit("pipewire-audio", env)
    assert result.returncode != 0 and "FAIL  inspect DSP package" in result.stdout
    assert snapshot(Path(env["HOME"])) == before
    assert "unexpected" not in Path(env["CHECK_LOG"]).read_text()


def test_check_comparison_failure_is_not_drift(stub_env, tmp_path):
    env = prepare_check(stub_env, tmp_path)
    managed_files(env)
    bindir = Path(env["PATH"])
    (bindir / "cmp").unlink()
    write_stub(bindir, "cmp", "exit 2\n")
    before = snapshot(Path(env["HOME"]))
    result = run_unit("pipewire-audio", env)
    assert result.returncode != 0
    assert "FAIL  compare audio config" in result.stderr
    assert snapshot(Path(env["HOME"])) == before
