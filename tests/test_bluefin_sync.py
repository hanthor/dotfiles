"""Unit tests for bluefin-sync.py — gsettings/dconf configuration application.

Tests the pure functions and error-handling paths without requiring actual
gsettings/dconf/gschema infrastructure. All Homebrew Ansible-copied files use
hyphens (bluefin-sync.py, not bluefin_sync.py), which isn't an importable
module name, so it's loaded via importlib like talos-k8s/hive/discord/report.py.
"""
import importlib.util
from unittest import mock

import pytest

from conftest import REPO

SRC = REPO / "roles/bluefin_common/files/bluefin-sync.py"
spec = importlib.util.spec_from_file_location("bluefin_sync", SRC)
bluefin_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bluefin_sync)


class TestRunCmd:
    """Tests for the subprocess wrapper."""

    def test_run_cmd_success(self):
        """Successful command returns stdout."""
        result = bluefin_sync.run_cmd(["echo", "test"])
        assert result.returncode == 0
        assert "test" in result.stdout

    def test_run_cmd_failure(self):
        """Failed command returns non-zero returncode."""
        result = bluefin_sync.run_cmd(["false"])
        assert result.returncode != 0

    def test_run_cmd_stderr_capture(self):
        """Stderr is captured."""
        result = bluefin_sync.run_cmd(["sh", "-c", "echo err >&2"])
        assert "err" in result.stderr


class TestApplyGschemaOverride:
    """Tests for gschema override file application."""

    def test_parses_schema_id_and_calls_gsettings(self, tmp_path):
        """Parses the [schema.id] section header and calls gsettings set for each key."""
        override = tmp_path / "zz0-bluefin-modifications.gschema.override"
        override.write_text(
            "[org.gnome.desktop.interface]\n"
            "gtk-theme='Adwaita'\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            bluefin_sync.apply_gschema_override(str(override))
            mock_run.assert_called_once_with(
                ["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", "'Adwaita'"]
            )

    def test_skips_comment_and_blank_lines(self, tmp_path):
        """Comment and blank lines inside a section are not applied."""
        override = tmp_path / "test.gschema.override"
        override.write_text(
            "[org.gnome.shell]\n"
            "# a comment\n"
            "\n"
            "favorite-apps=['app1']\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            bluefin_sync.apply_gschema_override(str(override))
            assert mock_run.call_count == 1
            mock_run.assert_called_once_with(
                ["gsettings", "set", "org.gnome.shell", "favorite-apps", "['app1']"]
            )

    def test_handles_empty_file(self, tmp_path):
        """An override file with no sections applies nothing and does not raise."""
        override = tmp_path / "empty.gschema.override"
        override.write_text("")
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            bluefin_sync.apply_gschema_override(str(override))
            mock_run.assert_not_called()

    def test_multiple_sections_each_applied(self, tmp_path):
        """Each [schema.id] section's keys are applied independently."""
        override = tmp_path / "multi.gschema.override"
        override.write_text(
            "[org.gnome.shell]\n"
            "enabled-extensions=['ext1']\n"
            "\n"
            "[org.gnome.desktop.interface]\n"
            "gtk-theme='Adwaita'\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            bluefin_sync.apply_gschema_override(str(override))
            assert mock_run.call_count == 2

    def test_redirects_system_background_path_to_local(self, tmp_path):
        """A /usr/share/backgrounds/bluefin value is rewritten under ~/.local/share."""
        override = tmp_path / "bg.gschema.override"
        override.write_text(
            "[org.gnome.desktop.background]\n"
            "picture-uri='file:///usr/share/backgrounds/bluefin/foo.webp'\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            bluefin_sync.apply_gschema_override(str(override))
            args = mock_run.call_args[0][0]
            value = args[-1]
            assert "/usr/share/backgrounds/bluefin" not in value
            assert ".local/share/backgrounds/bluefin" in value

    def test_adds_caffeine_to_enabled_extensions_when_missing(self, tmp_path):
        """caffeine@patapon.info is appended when enabled-extensions omits it."""
        override = tmp_path / "ext.gschema.override"
        override.write_text(
            "[org.gnome.shell]\n"
            "enabled-extensions=['dash-to-dock@micxjo.gmail.com']\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            bluefin_sync.apply_gschema_override(str(override))
            args = mock_run.call_args[0][0]
            value = args[-1]
            assert "caffeine@patapon.info" in value
            assert "dash-to-dock@micxjo.gmail.com" in value

    def test_does_not_duplicate_caffeine_when_already_present(self, tmp_path):
        """caffeine@patapon.info is left alone (not duplicated) when already listed."""
        override = tmp_path / "ext2.gschema.override"
        override.write_text(
            "[org.gnome.shell]\n"
            "enabled-extensions=['caffeine@patapon.info']\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            bluefin_sync.apply_gschema_override(str(override))
            args = mock_run.call_args[0][0]
            value = args[-1]
            assert value.count("caffeine@patapon.info") == 1

    def test_malformed_enabled_extensions_value_does_not_raise(self, tmp_path):
        """A value that ast.literal_eval can't parse still results in a gsettings call, unpatched."""
        override = tmp_path / "bad.gschema.override"
        override.write_text(
            "[org.gnome.shell]\n"
            "enabled-extensions=not a python literal\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            # Should not raise even though ast.literal_eval fails internally.
            bluefin_sync.apply_gschema_override(str(override))
            mock_run.assert_called_once()

    def test_missing_file_raises_file_not_found(self):
        """A nonexistent override path raises FileNotFoundError from open()."""
        with pytest.raises(FileNotFoundError):
            bluefin_sync.apply_gschema_override("/nonexistent/file.gschema.override")

    def test_directory_path_raises(self, tmp_path):
        """Passing a directory instead of a file raises (IsADirectoryError)."""
        with pytest.raises((IsADirectoryError, OSError)):
            bluefin_sync.apply_gschema_override(str(tmp_path))

    def test_logs_warning_when_gsettings_fails(self, tmp_path, capsys):
        """A non-zero gsettings return code is reported, not raised."""
        override = tmp_path / "fail.gschema.override"
        override.write_text(
            "[org.gnome.shell]\n"
            "favorite-apps=['app1']\n"
        )
        with mock.patch.object(bluefin_sync, "run_cmd") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1, stderr="Could not connect to system dbus")
            bluefin_sync.apply_gschema_override(str(override))
        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "Could not connect to system dbus" in captured.out


class TestApplyDconfKeyfile:
    """Tests for the dconf keyfile loader."""

    def test_loads_file_into_dconf(self, tmp_path):
        """The keyfile's contents are piped into `dconf load /` via stdin."""
        keyfile = tmp_path / "01-bluefin"
        keyfile.write_text("[/org/gnome/desktop/interface/]\ngtk-theme='Adwaita'\n")
        with mock.patch("subprocess.run") as mock_run:
            bluefin_sync.apply_dconf_keyfile(str(keyfile))
            assert mock_run.called
            args, kwargs = mock_run.call_args
            assert args[0] == ["dconf", "load", "/"]
            assert "stdin" in kwargs

    def test_missing_keyfile_raises(self):
        """A nonexistent keyfile path raises FileNotFoundError from open()."""
        with pytest.raises(FileNotFoundError):
            bluefin_sync.apply_dconf_keyfile("/nonexistent/dconf/01-bluefin")


class TestMainEntryPoint:
    """Tests for the CLI entry point's file-discovery logic (module executed as __main__)."""

    def test_no_args_prints_usage_and_exits(self):
        """Running the script with no sync-dir argument exits non-zero."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, str(SRC)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Usage" in result.stdout

    def test_missing_sync_dir_files_are_skipped_without_error(self, tmp_path):
        """An empty sync dir (no override file, no dconf dir) exits cleanly."""
        import subprocess
        import sys

        empty_dir = tmp_path / "empty-sync"
        empty_dir.mkdir()
        result = subprocess.run(
            [sys.executable, str(SRC), str(empty_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
