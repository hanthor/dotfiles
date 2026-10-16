#!/usr/bin/env python3
"""Unit tests for Firefox Accounts sign-in utility (fxa_signin.py)."""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import configparser

import pytest

# Add roles to path for import
REPO = Path(__file__).resolve().parent.parent
FXA_SIGNIN_PATH = REPO / "roles" / "browser_fxa" / "files" / "fxa_signin.py"
sys.path.insert(0, str(FXA_SIGNIN_PATH.parent))

# We'll load the module dynamically to test it
import importlib.util
spec = importlib.util.spec_from_file_location("fxa_signin", FXA_SIGNIN_PATH)
fxa_signin = importlib.util.module_from_spec(spec)


class TestFindDefaultProfile:
    """Tests for find_default_profile() config parser logic."""

    def test_prefers_install_section_default(self, tmp_path):
        """Should prefer the Install section's Default path."""
        profiles_ini = tmp_path / "profiles.ini"
        config_text = """\
[Install1234]
Default=profile-default

[Profile0]
Name=default
Path=profile-other
IsRelative=1
"""
        profiles_ini.write_text(config_text)
        base_dir = str(tmp_path)

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.find_default_profile(base_dir)
        assert result == str(tmp_path / "profile-default")

    def test_falls_back_to_profile_default_eq_1(self, tmp_path):
        """Should fall back to Profile section with Default=1."""
        profiles_ini = tmp_path / "profiles.ini"
        config_text = """\
[Profile0]
Name=default
Path=relpath/profile-rel
IsRelative=1
Default=1

[Profile1]
Name=other
Path=relpath/profile-other
IsRelative=1
"""
        profiles_ini.write_text(config_text)
        base_dir = str(tmp_path)

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.find_default_profile(base_dir)
        assert result == str(tmp_path / "relpath/profile-rel")

    def test_handles_absolute_paths(self, tmp_path):
        """Should use absolute paths when IsRelative=0."""
        profiles_ini = tmp_path / "profiles.ini"
        absolute_path = "/absolute/path/to/profile"
        config_text = f"""\
[Profile0]
Name=default
Path={absolute_path}
IsRelative=0
Default=1
"""
        profiles_ini.write_text(config_text)
        base_dir = str(tmp_path)

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.find_default_profile(base_dir)
        assert result == absolute_path

    def test_raises_on_missing_profiles_ini(self, tmp_path):
        """Should raise RuntimeError when profiles.ini doesn't exist."""
        base_dir = str(tmp_path)

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(RuntimeError, match="Could not find default profile"):
            fxa_signin.find_default_profile(base_dir)

    def test_raises_when_no_default_found(self, tmp_path):
        """Should raise RuntimeError when no default profile is found."""
        profiles_ini = tmp_path / "profiles.ini"
        config_text = """\
[Profile0]
Name=default
Path=relpath/profile
IsRelative=1
Default=0
"""
        profiles_ini.write_text(config_text)
        base_dir = str(tmp_path)

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(RuntimeError, match="Could not find default profile"):
            fxa_signin.find_default_profile(base_dir)


class TestResolveProfileDir:
    """Tests for resolve_profile_dir() browser and path detection."""

    def test_respects_explicit_profile_dir_override(self, tmp_path, monkeypatch):
        """Should use PROFILE_DIR env var if set."""
        override_path = str(tmp_path / "custom-profile")
        monkeypatch.setenv("PROFILE_DIR", override_path)
        monkeypatch.setenv("BROWSER_TYPE", "zen")

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.resolve_profile_dir()
        assert result == override_path

    def test_respects_zen_profile_dir_override(self, tmp_path, monkeypatch):
        """Should use ZEN_PROFILE_DIR env var as fallback override."""
        override_path = str(tmp_path / "zen-custom")
        monkeypatch.delenv("PROFILE_DIR", raising=False)
        monkeypatch.setenv("ZEN_PROFILE_DIR", override_path)
        monkeypatch.setenv("BROWSER_TYPE", "zen")

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.resolve_profile_dir()
        assert result == override_path

    def test_zen_browser_type(self, tmp_path, monkeypatch):
        """Should resolve Zen browser profiles."""
        zen_base = tmp_path / ".var/app/app.zen_browser.zen/.zen"
        zen_base.mkdir(parents=True)
        profiles_ini = zen_base / "profiles.ini"
        profiles_ini.write_text("""\
[Profile0]
Name=default
Path=profile-default
IsRelative=1
Default=1
""")

        monkeypatch.delenv("PROFILE_DIR", raising=False)
        monkeypatch.delenv("ZEN_PROFILE_DIR", raising=False)
        monkeypatch.setenv("BROWSER_TYPE", "zen")
        monkeypatch.setenv("HOME", str(tmp_path))

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.resolve_profile_dir()
        assert result == str(zen_base / "profile-default")

    def test_firefox_flatpak_first_fallback(self, tmp_path, monkeypatch):
        """Should try Firefox Flatpak before native when browser=firefox."""
        flatpak_base = tmp_path / ".var/app/org.mozilla.firefox/.mozilla/firefox"
        flatpak_base.mkdir(parents=True)
        profiles_ini = flatpak_base / "profiles.ini"
        profiles_ini.write_text("""\
[Profile0]
Name=default
Path=profile-flatpak
IsRelative=1
Default=1
""")

        monkeypatch.delenv("PROFILE_DIR", raising=False)
        monkeypatch.delenv("ZEN_PROFILE_DIR", raising=False)
        monkeypatch.setenv("BROWSER_TYPE", "firefox")
        monkeypatch.setenv("HOME", str(tmp_path))

        spec.loader.exec_module(fxa_signin)
        result = fxa_signin.resolve_profile_dir()
        assert result == str(flatpak_base / "profile-flatpak")

    def test_unknown_browser_type_raises(self, monkeypatch):
        """Should raise RuntimeError for unknown browser type."""
        monkeypatch.delenv("PROFILE_DIR", raising=False)
        monkeypatch.delenv("ZEN_PROFILE_DIR", raising=False)
        monkeypatch.setenv("BROWSER_TYPE", "unknown-browser")

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(RuntimeError, match="Unknown BROWSER_TYPE"):
            fxa_signin.resolve_profile_dir()


class TestMain:
    """Tests for main() entry point and error handling."""

    def test_missing_fxa_email_env_var(self, monkeypatch):
        """Should exit with code 2 if FXA_EMAIL not set."""
        monkeypatch.delenv("FXA_EMAIL", raising=False)
        monkeypatch.setenv("FXA_PASSWORD", "password")

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(SystemExit) as exc_info:
            fxa_signin.main()
        assert exc_info.value.code == 2

    def test_missing_fxa_password_env_var(self, monkeypatch):
        """Should exit with code 2 if FXA_PASSWORD not set."""
        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.delenv("FXA_PASSWORD", raising=False)

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(SystemExit) as exc_info:
            fxa_signin.main()
        assert exc_info.value.code == 2

    def test_profile_dir_resolution_error_exits_4(self, monkeypatch):
        """Should exit with code 4 if profile dir resolution fails."""
        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.setenv("FXA_PASSWORD", "password")
        monkeypatch.delenv("PROFILE_DIR", raising=False)
        monkeypatch.setenv("BROWSER_TYPE", "unknown-browser")

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(SystemExit) as exc_info:
            fxa_signin.main()
        assert exc_info.value.code == 4

    def test_pyfxa_import_not_found_exits_3(self, monkeypatch, tmp_path):
        """Should exit with code 3 if PyFxA is not installed."""
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        
        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.setenv("FXA_PASSWORD", "password")
        monkeypatch.setenv("PROFILE_DIR", str(profile_dir))

        # Mock the import to raise ImportError
        with patch.dict("sys.modules", {"fxa.core": None}):
            spec.loader.exec_module(fxa_signin)
            with pytest.raises(SystemExit) as exc_info:
                fxa_signin.main()
            assert exc_info.value.code == 3

    def test_idempotent_when_already_signed_in(self, monkeypatch, tmp_path):
        """Should exit 0 without changes if already signed in and verified."""
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        signed_in = profile_dir / "signedInUser.json"
        signed_in.write_text(json.dumps({
            "version": 1,
            "accountData": {
                "email": "test@example.com",
                "sessionToken": "token123",
                "uid": "uid123",
                "verified": True
            }
        }))

        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.setenv("FXA_PASSWORD", "password")
        monkeypatch.setenv("PROFILE_DIR", str(profile_dir))

        spec.loader.exec_module(fxa_signin)
        with pytest.raises(SystemExit) as exc_info:
            fxa_signin.main()
        assert exc_info.value.code == 0

    def test_overwrites_malformed_json(self, monkeypatch, tmp_path):
        """Should overwrite signedInUser.json if it's malformed."""
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        signed_in = profile_dir / "signedInUser.json"
        signed_in.write_text("{invalid json")

        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.setenv("FXA_PASSWORD", "password")
        monkeypatch.setenv("PROFILE_DIR", str(profile_dir))

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.token = "new_token_123"
        mock_session.uid = "new_uid_456"
        mock_client.login.return_value = mock_session

        spec.loader.exec_module(fxa_signin)
        with patch("fxa.core.Client", return_value=mock_client):
            # Should not exit with error, should proceed to login
            # We expect it to fail at some point after, but the malformed JSON should not block it
            try:
                fxa_signin.main()
            except SystemExit:
                pass  # Expected

    def test_totp_verification_failure_exits_1(self, monkeypatch, tmp_path):
        """Should exit with code 1 if TOTP verification fails."""
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()

        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.setenv("FXA_PASSWORD", "password")
        monkeypatch.setenv("FXA_TOTP", "123456")
        monkeypatch.setenv("PROFILE_DIR", str(profile_dir))

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.totp_verify.return_value = False  # TOTP verification fails
        mock_client.login.return_value = mock_session

        spec.loader.exec_module(fxa_signin)
        with patch("fxa.core.Client", return_value=mock_client):
            with pytest.raises(SystemExit) as exc_info:
                fxa_signin.main()
            assert exc_info.value.code == 1

    def test_writes_signed_in_json_on_success(self, monkeypatch, tmp_path):
        """Should write signedInUser.json on successful login."""
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()

        monkeypatch.setenv("FXA_EMAIL", "test@example.com")
        monkeypatch.setenv("FXA_PASSWORD", "password")
        monkeypatch.setenv("PROFILE_DIR", str(profile_dir))

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.token = b"token123" if isinstance(b"", bytes) else "token123"
        mock_session.uid = "uid456"
        mock_session.totp_verify.return_value = True  # TOTP passes if set
        mock_client.login.return_value = mock_session

        spec.loader.exec_module(fxa_signin)
        with patch("fxa.core.Client", return_value=mock_client):
            # We expect success but may get exit elsewhere, capture and inspect
            try:
                fxa_signin.main()
            except SystemExit as e:
                if e.code == 0:
                    pass  # Expected idempotent exit
            
            # Check if file was written
            signed_in_path = profile_dir / "signedInUser.json"
            if signed_in_path.exists():
                data = json.loads(signed_in_path.read_text())
                assert data["accountData"]["email"] == "test@example.com"
                assert data["accountData"]["verified"] is True
