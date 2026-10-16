#!/usr/bin/env python3
"""Unit tests for system-mitigator daemon (system-mitigator.py)."""

import sys
import os
import time
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open, call
import subprocess

import pytest

# Add roles to path for import
REPO = Path(__file__).resolve().parent.parent
MITIGATOR_PATH = REPO / "roles" / "systemd" / "files" / "system-mitigator.py"


class TestGetPkgTemp:
    """Tests for get_pkg_temp() CPU temperature reading."""

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    def test_reads_cpu_package_temperature(self, mock_file, mock_glob):
        """Should read x86_pkg_temp from sysfs thermal zone."""
        mock_glob.return_value = ["/sys/class/thermal/thermal_zone0"]
        
        # Mock open to return type and temp
        mock_file.return_value.__enter__.return_value.read.side_effect = [
            "x86_pkg_temp",  # type
            "65000"          # temp in millidegrees
        ]

        # Load and test module
        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        result = mitigator.get_pkg_temp()
        assert result == 65.0

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    def test_returns_none_on_read_error(self, mock_file, mock_glob):
        """Should return None if sysfs read fails."""
        mock_glob.return_value = []

        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        result = mitigator.get_pkg_temp()
        assert result is None

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    def test_skips_non_pkg_temp_zones(self, mock_file, mock_glob):
        """Should skip thermal zones that are not x86_pkg_temp."""
        mock_glob.return_value = [
            "/sys/class/thermal/thermal_zone0",
            "/sys/class/thermal/thermal_zone1"
        ]
        
        mock_file.return_value.__enter__.return_value.read.side_effect = [
            "acpitz",        # zone0 type (not pkg_temp)
            "x86_pkg_temp",  # zone1 type (match!)
            "72000"          # zone1 temp
        ]

        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        result = mitigator.get_pkg_temp()
        assert result == 72.0


class TestCheckCpuThrottling:
    """Tests for check_cpu_throttling() core frequency analysis."""

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    @patch("mitigator.get_pkg_temp")
    def test_detects_all_cores_at_min_frequency(self, mock_temp, mock_file, mock_glob):
        """Should detect when all cores are throttled at minimum frequency."""
        # Simulate 2 cores, both at min freq
        mock_glob.side_effect = [
            # First call: cur_freq files
            ["/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
             "/sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq"],
            # Second call: min_freq files
            ["/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq",
             "/sys/devices/system/cpu/cpu1/cpufreq/scaling_min_freq"]
        ]
        
        mock_file.return_value.__enter__.return_value.read.side_effect = [
            "400000", "400000",  # cur_freq for cpu0, cpu1 (400 MHz)
            "400000", "400000"   # min_freq for cpu0, cpu1 (400 MHz)
        ]

        mock_temp.return_value = 55.0

        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        # Call the function
        mitigator.check_cpu_throttling()
        
        # Verify accumulator increased
        assert mitigator.throttle_seconds_accumulator == 10

    @patch("glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    def test_resets_accumulator_when_cores_recover(self, mock_file, mock_glob):
        """Should reset throttle accumulator when cores recover from throttling."""
        mitigator_module = self._load_mitigator()
        
        mock_glob.side_effect = [
            # First call: cur_freq files
            ["/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"],
            # Second call: min_freq files
            ["/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq"]
        ]
        
        mock_file.return_value.__enter__.return_value.read.side_effect = [
            "2400000", "400000"  # cur_freq above min (2400 MHz), min_freq (400 MHz)
        ]

        # Set initial accumulator state
        mitigator_module.throttle_seconds_accumulator = 50

        mitigator_module.check_cpu_throttling()
        
        # Accumulator should be reset
        assert mitigator_module.throttle_seconds_accumulator == 0

    @staticmethod
    def _load_mitigator():
        """Helper to load the mitigator module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)
        return mitigator


class TestGetJournaldRestarts:
    """Tests for get_journald_restarts() systemctl query."""

    @patch("subprocess.run")
    def test_parses_journald_restart_count(self, mock_run):
        """Should parse NRestarts from systemctl output."""
        mock_run.return_value = MagicMock(
            stdout="NRestarts=5\n",
            returncode=0
        )

        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        result = mitigator.get_journald_restarts()
        assert result == 5

    @patch("subprocess.run")
    def test_returns_none_on_systemctl_error(self, mock_run):
        """Should return None if systemctl query fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "systemctl")

        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        result = mitigator.get_journald_restarts()
        assert result is None

    @patch("subprocess.run")
    def test_handles_malformed_output(self, mock_run):
        """Should return None if output cannot be parsed."""
        mock_run.return_value = MagicMock(
            stdout="InvalidFormat\n",
            returncode=0
        )

        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)

        result = mitigator.get_journald_restarts()
        assert result is None


class TestCheckJournaldHealth:
    """Tests for check_journald_health() crash loop detection."""

    def test_detects_restart_loop_tight_threshold(self):
        """Should detect journald crash loop (2+ restarts in 10s window)."""
        mitigator = self._load_mitigator()
        
        # Simulate initial state and crash loop
        mitigator.last_journal_restarts = 0
        
        with patch.object(mitigator, "get_journald_restarts", return_value=3):
            with patch.object(mitigator, "send_notification") as mock_notify:
                with patch("time.time", return_value=1000.0):
                    mitigator.last_journal_notification_time = 0
                    mitigator.check_journald_health()
                    
                    # Verify crash loop was detected and notification sent
                    assert mitigator.last_journal_restarts == 3
                    assert mock_notify.called  # Should have sent notification

    def test_rate_limits_notifications(self):
        """Should rate-limit crash loop notifications (5-minute intervals)."""
        mitigator = self._load_mitigator()
        
        mitigator.last_journal_restarts = 10
        mitigator.last_journal_notification_time = 1000.0
        
        with patch.object(mitigator, "get_journald_restarts", return_value=12):
            with patch.object(mitigator, "send_notification") as mock_notify:
                # Called at t=1100 (100 seconds after last notification)
                with patch("time.time", return_value=1100.0):
                    mitigator.check_journald_health()
                    
                    # Should NOT send notification (300s rate limit not met)
                    assert not mock_notify.called

    def test_respects_notification_cooldown(self):
        """Should send notification when cooldown expires (300s)."""
        mitigator = self._load_mitigator()
        
        mitigator.last_journal_restarts = 10
        mitigator.last_journal_notification_time = 1000.0
        
        with patch.object(mitigator, "get_journald_restarts", return_value=12):
            with patch.object(mitigator, "send_notification") as mock_notify:
                # Called at t=1350 (350 seconds after last notification, >300s cooldown)
                with patch("time.time", return_value=1350.0):
                    mitigator.check_journald_health()
                    
                    # Should send notification (cooldown expired)
                    assert mock_notify.called

    @staticmethod
    def _load_mitigator():
        """Helper to load the mitigator module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)
        return mitigator


class TestSendNotification:
    """Tests for send_notification() desktop notification dispatch."""

    @patch("subprocess.run")
    def test_sends_normal_notification(self, mock_run):
        """Should dispatch normal-urgency notification."""
        mitigator = self._load_mitigator()
        
        mitigator.send_notification("Test Title", "Test message", critical=False)
        
        # Verify notify-send was called with correct args
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "notify-send" in call_args
        assert "-u" in call_args and "normal" in call_args
        assert "Test Title" in call_args

    @patch("subprocess.run")
    def test_sends_critical_notification(self, mock_run):
        """Should dispatch critical-urgency notification."""
        mitigator = self._load_mitigator()
        
        mitigator.send_notification("Alert", "Critical issue", critical=True)
        
        call_args = mock_run.call_args[0][0]
        assert "-u" in call_args and "critical" in call_args
        assert "dialog-warning" in call_args

    @patch("subprocess.run")
    def test_handles_notification_dispatch_failure(self, mock_run):
        """Should not crash if notify-send fails."""
        mock_run.side_effect = Exception("notify-send not found")
        
        mitigator = self._load_mitigator()
        
        # Should not raise, just log the error
        mitigator.send_notification("Test", "Test", critical=False)
        # Test passes if no exception is raised

    @staticmethod
    def _load_mitigator():
        """Helper to load the mitigator module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("system_mitigator", MITIGATOR_PATH)
        mitigator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mitigator)
        return mitigator
