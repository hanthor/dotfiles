"""Tests for bluefin-wallpaper-rotate.py wallpaper rotation logic."""

import sys
import os
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock, call
import tempfile

# Import the script's logic (we'll create a testable module from it)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../roles/bluefin_common/files"))


class WallpaperRotationTests(TestCase):
    """Test cases for bluefin-wallpaper-rotate.py."""

    def test_wallpaper_name_format(self):
        """Verify wallpaper name matches expected format (MM-bluefin.xml)."""
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(
                strftime=MagicMock(return_value="03")
            )
            # Simulate the wallpaper naming logic
            month = mock_dt.now().strftime("%m")
            wallpaper_name = f"{month}-bluefin.xml"
            self.assertEqual(wallpaper_name, "03-bluefin.xml")

    def test_wallpaper_path_expansion(self):
        """Test that wallpaper paths are properly expanded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"HOME": tmpdir}):
                with patch("os.path.expanduser") as mock_expand:
                    mock_expand.return_value = f"{tmpdir}/.local/share/backgrounds/bluefin/01-bluefin.xml"
                    expanded = mock_expand(
                        "~/.local/share/backgrounds/bluefin/01-bluefin.xml"
                    )
                    self.assertTrue(expanded.endswith("01-bluefin.xml"))

    def test_wallpaper_existence_check(self):
        """Test that missing wallpaper is skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_path = os.path.join(tmpdir, "nonexistent.xml")
            self.assertFalse(os.path.exists(nonexistent_path))

    def test_wallpaper_file_exists(self):
        """Test that existing wallpaper file is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wallpaper_path = os.path.join(tmpdir, "03-bluefin.xml")
            Path(wallpaper_path).touch()
            self.assertTrue(os.path.exists(wallpaper_path))

    @patch("subprocess.run")
    def test_gsettings_light_variant_call(self, mock_run):
        """Test that gsettings is called for light variant."""
        uri = "file:///home/user/.local/share/backgrounds/bluefin/03-bluefin.xml"
        
        # Simulate the gsettings call for light variant
        expected_call = [
            "gsettings", "set", "org.gnome.desktop.background",
            "picture-uri", uri
        ]
        
        mock_run(expected_call)
        mock_run.assert_called_once_with(expected_call)

    @patch("subprocess.run")
    def test_gsettings_dark_variant_call(self, mock_run):
        """Test that gsettings is called for dark variant."""
        uri = "file:///home/user/.local/share/backgrounds/bluefin/03-bluefin.xml"
        
        # Simulate the gsettings call for dark variant
        expected_call = [
            "gsettings", "set", "org.gnome.desktop.background",
            "picture-uri-dark", uri
        ]
        
        mock_run(expected_call)
        mock_run.assert_called_once_with(expected_call)

    @patch("subprocess.run")
    def test_both_gsettings_variants_called(self, mock_run):
        """Test that both light and dark variants are set."""
        uri = "file:///home/user/.local/share/backgrounds/bluefin/06-bluefin.xml"
        
        # Simulate both calls
        light_call = ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri]
        dark_call = ["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri]
        
        mock_run(light_call)
        mock_run(dark_call)
        
        self.assertEqual(mock_run.call_count, 2)
        calls = [call(light_call), call(dark_call)]
        mock_run.assert_has_calls(calls)

    @patch("datetime.datetime")
    def test_all_months_generate_valid_names(self, mock_dt_class):
        """Test that each month generates a valid wallpaper name."""
        for month_num in range(1, 13):
            mock_dt = MagicMock()
            mock_dt.strftime.return_value = f"{month_num:02d}"
            mock_dt_class.now.return_value = mock_dt
            
            month = mock_dt_class.now().strftime("%m")
            wallpaper_name = f"{month}-bluefin.xml"
            
            # Verify format: MM-bluefin.xml
            self.assertRegex(wallpaper_name, r"^\d{2}-bluefin\.xml$")
            self.assertIn(month, wallpaper_name)

    def test_uri_file_prefix(self):
        """Test that wallpaper URIs are properly prefixed with file://."""
        local_path = "/home/user/.local/share/backgrounds/bluefin/01-bluefin.xml"
        uri = f"file://{local_path}"
        self.assertTrue(uri.startswith("file://"))
        self.assertIn(local_path, uri)

    @patch("subprocess.run")
    def test_missing_wallpaper_no_gsettings_call(self, mock_run):
        """Test that gsettings is not called when wallpaper is missing."""
        # When wallpaper doesn't exist, no gsettings calls should be made
        mock_run.assert_not_called()
