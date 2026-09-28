"""Unit tests for the bw_credential Ansible module.

Tests the Bitwarden credential extraction library with mocked subprocess calls
and realistic JSON fixtures.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

# Import the module functions
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / "library"))
import bw_credential as bw


class TestRunBw:
    """Tests for the bw command execution wrapper."""

    def test_run_bw_success(self):
        """Successful bw command returns rc=0 and stdout."""
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "test output\n"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            rc, stdout, stderr = bw.run_bw(["status"])
            assert rc == 0
            assert stdout == "test output"
            assert stderr == ""

    def test_run_bw_failure(self):
        """Failed bw command returns non-zero rc."""
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.stdout = ""
            mock_proc.stderr = "error message"
            mock_run.return_value = mock_proc

            rc, stdout, stderr = bw.run_bw(["get", "item", "missing"])
            assert rc == 1
            assert stdout == ""
            assert stderr == "error message"

    def test_run_bw_strips_whitespace(self):
        """run_bw strips leading/trailing whitespace from output."""
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "  output with spaces  \n"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            rc, stdout, stderr = bw.run_bw(["test"])
            assert stdout == "output with spaces"


class TestBwStatus:
    """Tests for bw vault status detection."""

    def test_status_unlocked(self):
        """Recognizes unlocked vault."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, '{"status":"unlocked"}', "")
            assert bw.bw_status() == "unlocked"

    def test_status_locked(self):
        """Recognizes locked vault."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, '{"status":"locked"}', "")
            assert bw.bw_status() == "locked"

    def test_status_unauthenticated(self):
        """Recognizes unauthenticated vault."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, '{"status":"unauthenticated"}', "")
            assert bw.bw_status() == "unauthenticated"

    def test_status_missing_bw(self):
        """Returns 'missing' when bw command is not found."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (127, "No such file or directory", "")
            assert bw.bw_status() == "missing"

    def test_status_command_not_found(self):
        """Returns 'missing' on 'command not found' error."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (127, "bw: command not found", "")
            assert bw.bw_status() == "missing"

    def test_status_invalid_json(self):
        """Returns 'unknown' when JSON is invalid."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "not json", "")
            assert bw.bw_status() == "unknown"

    def test_status_nonzero_exit(self):
        """Returns 'unknown' on non-zero exit (not 'missing')."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (1, "error", "")
            assert bw.bw_status() == "unknown"


class TestBwGetItem:
    """Tests for fetching a single Bitwarden item."""

    def test_get_item_success(self):
        """Successfully fetches and parses an item."""
        item_json = json.dumps({"id": "123", "name": "test", "login": {"username": "user"}})
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, item_json, "")
            result = bw.bw_get_item("test")
            assert result == {"id": "123", "name": "test", "login": {"username": "user"}}

    def test_get_item_not_found(self):
        """Returns None when item is not found (rc != 0)."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (1, "", "")
            assert bw.bw_get_item("missing") is None

    def test_get_item_empty_stdout(self):
        """Returns None on empty stdout."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "", "")
            assert bw.bw_get_item("test") is None

    def test_get_item_invalid_json(self):
        """Returns None when JSON is invalid."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "not valid json", "")
            assert bw.bw_get_item("test") is None


class TestBwGetTotp:
    """Tests for TOTP retrieval."""

    def test_get_totp_success(self):
        """Successfully retrieves TOTP code."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "123456", "")
            assert bw.bw_get_totp("item-id") == "123456"

    def test_get_totp_with_whitespace(self):
        """Strips whitespace from TOTP code."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "  123456  \n", "")
            assert bw.bw_get_totp("item-id") == "123456"

    def test_get_totp_failure(self):
        """Returns None when TOTP fetch fails."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (1, "", "")
            assert bw.bw_get_totp("item-id") is None

    def test_get_totp_empty_response(self):
        """Returns None on empty response."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "", "")
            assert bw.bw_get_totp("item-id") is None


class TestBwListItems:
    """Tests for searching and listing items."""

    def test_list_items_success(self):
        """Successfully lists matching items."""
        items_json = json.dumps([
            {"id": "1", "name": "aws"},
            {"id": "2", "name": "aws-prod"}
        ])
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, items_json, "")
            result = bw.bw_list_items("aws")
            assert len(result) == 2
            assert result[0]["name"] == "aws"

    def test_list_items_empty_search(self):
        """Returns empty list when no items match."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "[]", "")
            result = bw.bw_list_items("nonexistent")
            assert result == []

    def test_list_items_command_fails(self):
        """Returns empty list on command failure."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (1, "", "")
            result = bw.bw_list_items("test")
            assert result == []

    def test_list_items_invalid_json(self):
        """Returns empty list on invalid JSON."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, "not json", "")
            result = bw.bw_list_items("test")
            assert result == []

    def test_list_items_non_list_response(self):
        """Returns empty list when response is not a JSON array."""
        with patch.object(bw, "run_bw") as mock_run:
            mock_run.return_value = (0, '{"not":"a_list"}', "")
            result = bw.bw_list_items("test")
            assert result == []


class TestExtractField:
    """Tests for field extraction from Bitwarden items."""

    @pytest.fixture
    def sample_item(self):
        """A realistic Bitwarden item fixture."""
        return {
            "id": "item-123",
            "name": "prod-db",
            "login": {
                "username": "admin",
                "password": "secret123",
                "totp": None,
            },
            "notes": "Production database credentials",
            "sshKey": {
                "privateKey": "-----BEGIN RSA PRIVATE KEY-----\n...",
                "publicKey": "ssh-rsa AAAA...",
            },
            "fields": [
                {"name": "env", "value": "production"},
                {"name": "region", "value": "us-east-1"},
            ]
        }

    def test_extract_password_success(self, sample_item):
        """Extracts password field."""
        found, value = bw.extract_field(sample_item, "password")
        assert found is True
        assert value == "secret123"

    def test_extract_password_missing(self):
        """Returns (False, '') when password is missing."""
        item = {"login": {}}
        found, value = bw.extract_field(item, "password")
        assert found is False
        assert value == ""

    def test_extract_username(self, sample_item):
        """Extracts username field."""
        found, value = bw.extract_field(sample_item, "username")
        assert found is True
        assert value == "admin"

    def test_extract_username_empty_but_exists(self):
        """Returns (True, '') when username is empty (field exists)."""
        item = {"login": {"username": ""}}
        found, value = bw.extract_field(item, "username")
        assert found is True
        assert value == ""

    def test_extract_notes(self, sample_item):
        """Extracts notes field."""
        found, value = bw.extract_field(sample_item, "notes")
        assert found is True
        assert value == "Production database credentials"

    def test_extract_ssh_private_key(self, sample_item):
        """Extracts SSH private key."""
        found, value = bw.extract_field(sample_item, "ssh_private_key")
        assert found is True
        assert value.startswith("-----BEGIN RSA PRIVATE KEY-----")

    def test_extract_ssh_public_key(self, sample_item):
        """Extracts SSH public key."""
        found, value = bw.extract_field(sample_item, "ssh_public_key")
        assert found is True
        assert value.startswith("ssh-rsa")

    def test_extract_custom_field(self, sample_item):
        """Extracts custom field by name."""
        found, value = bw.extract_field(sample_item, "custom:env")
        assert found is True
        assert value == "production"

    def test_extract_custom_field_missing(self, sample_item):
        """Returns (False, '') for missing custom field."""
        found, value = bw.extract_field(sample_item, "custom:missing")
        assert found is False
        assert value == ""

    def test_extract_totp_with_mocking(self, sample_item):
        """Extracts TOTP by calling bw_get_totp."""
        with patch.object(bw, "bw_get_totp") as mock_totp:
            mock_totp.return_value = "654321"
            found, value = bw.extract_field(sample_item, "totp")
            assert found is True
            assert value == "654321"
            mock_totp.assert_called_once_with("item-123")

    def test_extract_totp_missing_id(self):
        """Returns (False, '') when item has no ID (totp fetch would fail)."""
        item = {"login": {}}  # No ID
        with patch.object(bw, "bw_get_totp"):
            found, value = bw.extract_field(item, "totp")
            assert found is False
            assert value == ""

    def test_extract_unknown_field(self, sample_item):
        """Returns (False, '') for completely unknown fields."""
        found, value = bw.extract_field(sample_item, "unknown_field")
        assert found is False
        assert value == ""


class TestMainFunction:
    """Integration tests for the module's main entry point."""

    def test_main_missing_item_name(self, tmp_path, monkeypatch):
        """Returns error when item name is missing."""
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
        with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
            bw.main()
            output = json.loads(mock_stdout.getvalue())
            assert output["found"] is False
            assert output["reason"] == "item_required"

    def test_main_vault_locked(self, monkeypatch):
        """Returns error when vault is locked."""
        args = json.dumps({"item": "test", "field": "password"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "locked"
            with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                bw.main()
                output = json.loads(mock_stdout.getvalue())
                assert output["found"] is False
                assert output["reason"] == "vault_locked"

    def test_main_bw_missing(self, monkeypatch):
        """Returns error when bw is not installed."""
        args = json.dumps({"item": "test", "field": "password"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "missing"
            with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                bw.main()
                output = json.loads(mock_stdout.getvalue())
                assert output["found"] is False
                assert output["reason"] == "bw_missing"

    def test_main_item_not_found(self, monkeypatch):
        """Returns error when item doesn't exist in vault."""
        args = json.dumps({"item": "missing", "field": "password"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "unlocked"
            with patch.object(bw, "bw_get_item") as mock_get:
                mock_get.return_value = None
                with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                    bw.main()
                    output = json.loads(mock_stdout.getvalue())
                    assert output["found"] is False
                    assert output["reason"] == "item_not_found"

    def test_main_field_not_found(self, monkeypatch):
        """Returns error when field doesn't exist in item."""
        args = json.dumps({"item": "test", "field": "password"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "unlocked"
            with patch.object(bw, "bw_get_item") as mock_get:
                mock_get.return_value = {"login": {}}  # No password
                with patch.object(bw, "extract_field") as mock_extract:
                    mock_extract.return_value = (False, "")
                    with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                        bw.main()
                        output = json.loads(mock_stdout.getvalue())
                        assert output["found"] is False
                        assert output["reason"] == "field_not_found"

    def test_main_success(self, monkeypatch):
        """Successfully retrieves a field value."""
        args = json.dumps({"item": "test", "field": "password"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "unlocked"
            with patch.object(bw, "bw_get_item") as mock_get:
                mock_get.return_value = {"login": {"password": "secret"}}
                with patch.object(bw, "extract_field") as mock_extract:
                    mock_extract.return_value = (True, "secret")
                    with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                        bw.main()
                        output = json.loads(mock_stdout.getvalue())
                        assert output["found"] is True
                        assert output["value"] == "secret"


class TestMainListMode:
    """Tests for list_mode=true in main()."""

    def test_main_list_no_search(self, monkeypatch):
        """Returns error when list_mode is true but search is empty."""
        args = json.dumps({"list_mode": True, "search": ""})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
            bw.main()
            output = json.loads(mock_stdout.getvalue())
            assert output["found"] is False
            assert output["reason"] == "search_required"
            assert output["items"] == []

    def test_main_list_vault_locked(self, monkeypatch):
        """Returns error in list mode when vault is locked."""
        args = json.dumps({"list_mode": True, "search": "aws"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "locked"
            with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                bw.main()
                output = json.loads(mock_stdout.getvalue())
                assert output["found"] is False
                assert output["reason"] == "vault_locked"

    def test_main_list_success(self, monkeypatch):
        """Successfully lists matching items."""
        args = json.dumps({"list_mode": True, "search": "aws"})
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(args))
        items = [{"id": "1", "name": "aws-prod"}]
        with patch.object(bw, "bw_status") as mock_status:
            mock_status.return_value = "unlocked"
            with patch.object(bw, "bw_list_items") as mock_list:
                mock_list.return_value = items
                with patch("sys.stdout", new_callable=__import__("io").StringIO) as mock_stdout:
                    bw.main()
                    output = json.loads(mock_stdout.getvalue())
                    assert output["found"] is True
                    assert output["items"] == items
