#!/usr/bin/env python3
"""Unit tests for bluefin-wallpaper-rotate.py"""

import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
from datetime import datetime

# Import the module under test
sys.path.insert(0, os.path.dirname(__file__))
import bluefin_wallpaper_rotate as wallpaper_rotate


class TestSetWallpaper(unittest.TestCase):
    """Test suite for set_wallpaper() function"""

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_set_for_current_month(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that wallpaper is set to current month when file exists"""
        mock_datetime.datetime.now.return_value = datetime(2026, 3, 15)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        expected_uri = "file:///home/user/.local/share/backgrounds/bluefin/03-bluefin.xml"
        mock_run.assert_any_call(
            ['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri', expected_uri]
        )
        mock_run.assert_any_call(
            ['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri-dark', expected_uri]
        )

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_skipped_when_file_missing(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that wallpaper setting is skipped when file does not exist"""
        mock_datetime.datetime.now.return_value = datetime(2026, 7, 1)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = False

        wallpaper_rotate.set_wallpaper()

        mock_run.assert_not_called()

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    @patch('builtins.print')
    def test_wallpaper_not_found_message(self, mock_print, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that missing wallpaper message is printed"""
        mock_datetime.datetime.now.return_value = datetime(2026, 12, 25)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = False

        wallpaper_rotate.set_wallpaper()

        mock_print.assert_called_with("Wallpaper /home/user/.local/share/backgrounds/bluefin/12-bluefin.xml not found, skipping rotation.")

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    @patch('builtins.print')
    def test_wallpaper_rotation_message(self, mock_print, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that wallpaper rotation message is printed"""
        mock_datetime.datetime.now.return_value = datetime(2026, 1, 1)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        expected_uri = "file:///home/user/.local/share/backgrounds/bluefin/01-bluefin.xml"
        mock_print.assert_called_with(f"Rotating wallpaper to {expected_uri}")

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_month_padding_january(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that January is padded to 01"""
        mock_datetime.datetime.now.return_value = datetime(2026, 1, 15)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        expected_uri = "file:///home/user/.local/share/backgrounds/bluefin/01-bluefin.xml"
        calls = mock_run.call_args_list
        assert any(expected_uri in str(call) for call in calls), \
            f"Expected URI not found in calls: {calls}"

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_month_padding_september(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that September is padded to 09"""
        mock_datetime.datetime.now.return_value = datetime(2026, 9, 15)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        expected_uri = "file:///home/user/.local/share/backgrounds/bluefin/09-bluefin.xml"
        calls = mock_run.call_args_list
        assert any(expected_uri in str(call) for call in calls), \
            f"Expected URI not found in calls: {calls}"

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_sets_both_light_and_dark(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that both picture-uri and picture-uri-dark are set"""
        mock_datetime.datetime.now.return_value = datetime(2026, 6, 15)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        # Verify two gsettings calls were made
        assert mock_run.call_count == 2, f"Expected 2 calls, got {mock_run.call_count}"

        # Verify both light and dark settings were updated
        calls = [str(call) for call in mock_run.call_args_list]
        has_picture_uri = any('picture-uri' in call and 'picture-uri-dark' not in call for call in calls)
        has_picture_uri_dark = any('picture-uri-dark' in call for call in calls)

        assert has_picture_uri, "picture-uri setting not found"
        assert has_picture_uri_dark, "picture-uri-dark setting not found"

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_path_expansion(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that ~ is expanded to home directory path"""
        mock_datetime.datetime.now.return_value = datetime(2026, 5, 15)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        # Path should be expanded (starts with / not ~)
        calls = [str(call) for call in mock_run.call_args_list]
        has_tilde = any('~' in call for call in calls)
        assert not has_tilde, "Tilde found in path; should have been expanded"

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_wallpaper_file_uri_format(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that wallpaper URI uses file:// protocol"""
        mock_datetime.datetime.now.return_value = datetime(2026, 8, 15)
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True

        wallpaper_rotate.set_wallpaper()

        calls = [str(call) for call in mock_run.call_args_list]
        has_file_uri = any('file://' in call for call in calls)
        assert has_file_uri, "file:// URI not found in calls"


class TestMonthMapping(unittest.TestCase):
    """Test wallpaper name mapping for each month"""

    @patch('bluefin_wallpaper_rotate.subprocess.run')
    @patch('bluefin_wallpaper_rotate.os.path.expanduser')
    @patch('bluefin_wallpaper_rotate.os.path.exists')
    @patch('bluefin_wallpaper_rotate.datetime')
    def test_all_months_generate_correct_names(self, mock_datetime, mock_exists, mock_expanduser, mock_run):
        """Test that all 12 months map to correctly formatted wallpaper names"""
        mock_expanduser.side_effect = lambda x: x.replace('~', '/home/user')
        mock_exists.return_value = True
        expected_months = [
            '01', '02', '03', '04', '05', '06',
            '07', '08', '09', '10', '11', '12'
        ]

        for month_num, month_str in enumerate(expected_months, 1):
            mock_run.reset_mock()
            mock_datetime.datetime.now.return_value = datetime(2026, month_num, 1)

            wallpaper_rotate.set_wallpaper()

            expected_uri = f"file:///home/user/.local/share/backgrounds/bluefin/{month_str}-bluefin.xml"
            calls = [str(call) for call in mock_run.call_args_list]
            assert any(expected_uri in call for call in calls), \
                f"Month {month_num}: Expected URI not found: {expected_uri}"


if __name__ == '__main__':
    unittest.main()
