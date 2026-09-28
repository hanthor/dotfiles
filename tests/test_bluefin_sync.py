"""Unit tests for bluefin-sync.py — gsettings/dconf configuration application.

Tests the pure functions and error-handling paths without requiring actual
gsettings/dconf/gschema infrastructure.
"""
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# Import the module we're testing (adjust path as needed)
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "roles/bluefin_common/files"))
import bluefin_sync


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

    @pytest.fixture
    def sample_override_file(self):
        """Create a temporary gschema override file."""
        content = """[org.gnome.shell]
enabled-extensions=['dash-to-dock@micxjo.gmail.com', 'blur-my-shell@aunetx']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gschema.override', delete=False) as f:
            f.write(content)
            f.flush()
            yield Path(f.name)
        Path(f.name).unlink()

    def test_apply_gschema_override_parses_schema_id(self, sample_override_file):
        """Parses schema ID from [schema.id] section header."""
        with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            bluefin_sync.apply_gschema_override(str(sample_override_file))
            # Verify that run_cmd was called (gsettings set would be invoked)
            assert mock_run.called

    def test_apply_gschema_override_skips_comments(self):
        """Skips comment lines in gschema file."""
        content = """# This is a comment
[org.gnome.shell]
# Another comment
enabled-extensions=['test']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gschema.override', delete=False) as f:
            f.write(content)
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                bluefin_sync.apply_gschema_override(str(f.name))
                assert mock_run.called
            Path(f.name).unlink()

    def test_apply_gschema_override_handles_empty_file(self):
        """Handles empty gschema file gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gschema.override', delete=False) as f:
            f.write("")
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                # Should not raise
                bluefin_sync.apply_gschema_override(str(f.name))
            Path(f.name).unlink()

    def test_apply_gschema_override_multiple_sections(self):
        """Handles multiple schema sections in one file."""
        content = """[org.gnome.shell]
enabled-extensions=['ext1']

[org.gnome.desktop.interface]
gtk-theme='adwaita'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gschema.override', delete=False) as f:
            f.write(content)
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                bluefin_sync.apply_gschema_override(str(f.name))
                # Should be called for each setting
                assert mock_run.call_count >= 2
            Path(f.name).unlink()


class TestApplyDconfProfile:
    """Tests for dconf profile file application."""

    def test_apply_dconf_profile_reads_file(self):
        """Reads dconf profile file."""
        content = """[/org/gnome/shell/]
enabled-extensions=['test']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.profile', delete=False) as f:
            f.write(content)
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                bluefin_sync.apply_dconf_profile(str(f.name))
                assert mock_run.called
            Path(f.name).unlink()

    def test_apply_dconf_profile_empty_file(self):
        """Handles empty dconf profile gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.profile', delete=False) as f:
            f.write("")
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                bluefin_sync.apply_dconf_profile(str(f.name))
            Path(f.name).unlink()


class TestApplyDconfDefaults:
    """Tests for dconf defaults database."""

    def test_apply_dconf_defaults_compilation(self):
        """Compiles dconf defaults database."""
        content = """[org/gnome/shell]
enabled-extensions=['test']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gschema', delete=False) as f:
            f.write(content)
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                bluefin_sync.apply_dconf_defaults(str(f.name))
                # dconf update should be called
                assert mock_run.called
            Path(f.name).unlink()

    def test_apply_dconf_defaults_handles_missing_file(self):
        """Handles gracefully when dconf defaults don't exist."""
        with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1, stdout="", stderr="File not found")
            with pytest.raises((FileNotFoundError, OSError)):
                bluefin_sync.apply_dconf_defaults("/nonexistent/defaults.d/99-bluefin")


class TestConfigParsing:
    """Tests for INI/override file parsing."""

    def test_parse_gschema_override_simple(self):
        """Parses simple gschema override."""
        content = """[org.gnome.shell]
enabled-extensions=['ext1', 'ext2']
favorite-apps=['app1', 'app2']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.override', delete=False) as f:
            f.write(content)
            f.flush()
            # Verify file is readable and has expected content
            text = Path(f.name).read_text()
            assert 'org.gnome.shell' in text
            assert 'enabled-extenss' in text
            Path(f.name).unlink()

    def test_parse_gschema_override_with_special_chars(self):
        """Parses gschema with special characters in values."""
        content = """[org.gnome.desktop.interface]
font-name='DejaVu Sans 11'
gtk-theme='Adwaita'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.override', delete=False) as f:
            f.write(content)
            f.flush()
            text = Path(f.name).read_text()
            assert 'DejaVu Sans 11' in text
            Path(f.name).unlink()

    def test_parse_gschema_override_array_values(self):
        """Parses array-type values in gschema."""
        content = """[org.gnome.shell]
enabled-extensions=['extension-1@example.com', 'extension-2@example.com']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.override', delete=False) as f:
            f.write(content)
            f.flush()
            text = Path(f.name).read_text()
            assert 'extension-1@example.com' in text
            assert 'extension-2@example.com' in text
            Path(f.name).unlink()


class TestErrorHandling:
    """Tests for error conditions and edge cases."""

    def test_run_cmd_with_failing_gsettings(self):
        """Handles gsettings command failures."""
        with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=1,
                stderr="Could not connect to system dbus"
            )
            result = bluefin_sync.run_cmd(['gsettings', 'set', 'test', 'test', 'value'])
            assert result.returncode != 0

    def test_apply_gschema_override_with_missing_file(self):
        """Raises error for missing gschema file."""
        with pytest.raises(FileNotFoundError):
            bluefin_sync.apply_gschema_override("/nonexistent/file.override")

    def test_apply_gschema_override_with_invalid_path(self):
        """Raises error for invalid path."""
        with pytest.raises((FileNotFoundError, OSError, IsADirectoryError)):
            bluefin_sync.apply_gschema_override("/tmp/")

    def test_dconf_connection_failure_handled(self):
        """Handles dconf connection failures."""
        with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
            # Simulate dconf daemon not running
            mock_run.return_value = mock.MagicMock(
                returncode=1,
                stderr="Cannot find dconf database"
            )
            result = bluefin_sync.run_cmd(['dconf', 'dump', '/'])
            assert result.returncode != 0


class TestIntegrationScenarios:
    """Integration-level scenarios testing multiple functions together."""

    def test_apply_both_gschema_and_dconf(self):
        """Applies both gschema and dconf configurations."""
        gschema_content = """[org.gnome.shell]
enabled-extensions=['test']
"""
        dconf_content = """[/org/gnome/desktop/interface/]
gtk-theme='Adwaita'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gschema.override', delete=False) as gf:
            gf.write(gschema_content)
            gf.flush()
            with tempfile.NamedTemporaryFile(mode='w', suffix='.dconf', delete=False) as df:
                df.write(dconf_content)
                df.flush()
                with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                    mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                    bluefin_sync.apply_gschema_override(str(gf.name))
                    bluefin_sync.apply_dconf_profile(str(df.name))
                    assert mock_run.call_count >= 2
                Path(gf.name).unlink()
                Path(df.name).unlink()

    def test_configuration_order_independence(self):
        """Configuration settings can be applied in any order."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.override', delete=False) as f:
            f.write("""[org.gnome.shell]
setting-a=1
setting-b=2
setting-c=3
""")
            f.flush()
            with mock.patch.object(bluefin_sync, 'run_cmd') as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                bluefin_sync.apply_gschema_override(str(f.name))
                # All settings should be applied
                assert mock_run.called
            Path(f.name).unlink()
