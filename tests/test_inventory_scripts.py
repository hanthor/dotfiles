#!/usr/bin/env python3
"""Unit tests for purge-machine.py and register-machine.py via inventory_parser.py"""

import os
import tempfile
import unittest
import yaml
from pathlib import Path

# Add scripts directory to path
import sys
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from inventory_parser import parse_inventory, register_host, purge_host, UnknownGroupError, host_groups


class TestParseInventory(unittest.TestCase):
    """Test inventory parsing."""

    def test_parse_empty_inventory(self) -> None:
        """parse_inventory handles empty inventory."""
        text = ""
        all_hosts, vps = parse_inventory(text)
        self.assertEqual(all_hosts, set())
        self.assertEqual(vps, set())

    def test_parse_all_hosts(self) -> None:
        """parse_inventory extracts all.hosts entries."""
        text = """all:
  hosts:
    host1:
      ansible_host: 10.0.0.1
    host2:
      ansible_host: 10.0.0.2
"""
        all_hosts, vps = parse_inventory(text)
        self.assertEqual(all_hosts, {"host1", "host2"})
        self.assertEqual(vps, set())

    def test_parse_vps_hosts(self) -> None:
        """parse_inventory extracts vps hosts from children."""
        text = """all:
  hosts:
    host1:
      ansible_host: localhost
  children:
    vps:
      hosts:
        vps1:
        vps2:
"""
        all_hosts, vps = parse_inventory(text)
        self.assertEqual(all_hosts, {"host1"})
        self.assertEqual(vps, {"vps1", "vps2"})

    def test_parse_ignores_comments(self) -> None:
        """parse_inventory ignores comment lines."""
        text = """all:
  hosts:
    # This is a comment
    host1:
      # Another comment
      ansible_host: localhost
"""
        all_hosts, vps = parse_inventory(text)
        self.assertEqual(all_hosts, {"host1"})

    def test_parse_ignores_blank_lines(self) -> None:
        """parse_inventory ignores blank lines."""
        text = """all:
  hosts:

    host1:
      ansible_host: localhost

  children:

    vps:
      hosts:
        vps1:
"""
        all_hosts, vps = parse_inventory(text)
        self.assertEqual(all_hosts, {"host1"})
        self.assertEqual(vps, {"vps1"})


class TestRegisterHost(unittest.TestCase):
    """Test register_host function."""

    def setUp(self) -> None:
        """Create temporary inventory for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.inv_path = Path(self.temp_dir.name) / "inventory.yml"
        self.inv_path.write_text("""all:
  hosts:
  children:
    desktop:
      hosts:
    laptop:
      hosts:
    vps:
      hosts:
""")

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_register_host_new_desktop(self) -> None:
        """register_host adds new desktop host."""
        result = register_host("myhost", "desktop", str(self.inv_path))
        self.assertTrue(result)
        content = self.inv_path.read_text()
        self.assertIn("    myhost:", content)
        self.assertIn("      ansible_host: localhost", content)

    def test_register_host_already_exists(self) -> None:
        """register_host returns False when host exists."""
        register_host("myhost", "desktop", str(self.inv_path))
        result = register_host("myhost", "desktop", str(self.inv_path))
        self.assertFalse(result)

    def test_register_host_unknown_group(self) -> None:
        """register_host raises UnknownGroupError for invalid group."""
        with self.assertRaises(UnknownGroupError):
            register_host("myhost", "unknown-group", str(self.inv_path))

    def test_register_host_in_group(self) -> None:
        """register_host adds host to correct group."""
        register_host("host1", "desktop", str(self.inv_path))
        register_host("host2", "laptop", str(self.inv_path))
        content = self.inv_path.read_text()
        # Verify host1 is under desktop
        self.assertIn("    desktop:\n      hosts:\n        host1:", content)
        # Verify host2 is under laptop
        self.assertIn("    laptop:\n      hosts:\n        host2:", content)

    def test_group_name_is_not_mistaken_for_existing_host(self) -> None:
        self.assertTrue(register_host("vps", "desktop", str(self.inv_path)))
        data = yaml.safe_load(self.inv_path.read_text())
        self.assertIn("vps", data["all"]["hosts"])
        self.assertIn("vps", data["all"]["children"]["desktop"]["hosts"])

    def test_invalid_name_cannot_mutate_inventory(self) -> None:
        before = self.inv_path.read_text()
        with self.assertRaises(ValueError):
            register_host("../escape", "desktop", str(self.inv_path))
        self.assertEqual(self.inv_path.read_text(), before)

    def test_group_detection_is_not_limited_to_first_300_characters(self) -> None:
        hosts = "".join(f"        item{i}: {{}}\n" for i in range(50))
        text = f"all:\n  hosts:\n    target: {{}}\n  children:\n    server:\n      hosts:\n{hosts}        target: {{}} # entry\n"
        self.assertEqual(host_groups(text, "target"), {"server"})
        self.assertEqual(parse_inventory(text)[0], {"target"})


class TestPurgeHost(unittest.TestCase):
    """Test purge_host function."""

    def setUp(self) -> None:
        """Create temporary inventory and host_vars."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.inv_path = self.temp_path / "inventory.yml"
        self.hostvars_dir = self.temp_path / "host_vars"
        self.hostvars_dir.mkdir()
        
        # Create inventory with some hosts
        self.inv_path.write_text("""all:
  hosts:
    host1:
      ansible_host: localhost
    host2:
      ansible_host: 10.0.0.2
  children:
    desktop:
      hosts:
        host1:
    vps:
      hosts:
        host2:
""")

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_purge_host_removes_from_all_hosts(self) -> None:
        """purge_host removes host from all.hosts section."""
        purge_host("host1", str(self.inv_path))
        content = self.inv_path.read_text()
        self.assertNotIn("    host1:", content)

    def test_purge_host_removes_from_group(self) -> None:
        """purge_host removes host from group hosts list."""
        purge_host("host1", str(self.inv_path))
        content = self.inv_path.read_text()
        self.assertNotIn("        host1:", content)

    def test_purge_host_removes_hostvars_file(self) -> None:
        """purge_host removes host_vars file if it exists."""
        hostvars_file = self.hostvars_dir / "host1.yml"
        hostvars_file.write_text("ansible_port: 2222\n")
        
        purge_host("host1", str(self.inv_path))
        self.assertFalse(hostvars_file.exists())

    def test_purge_host_nonexistent_hostvars_ok(self) -> None:
        """purge_host succeeds even if hostvars doesn't exist."""
        result = purge_host("host1", str(self.inv_path))
        self.assertTrue(result)

    def test_purge_host_nonexistent_host(self) -> None:
        """purge_host returns False when host doesn't exist."""
        result = purge_host("nonexistent", str(self.inv_path))
        self.assertFalse(result)

    def test_purge_host_preserves_other_hosts(self) -> None:
        """purge_host doesn't affect other hosts."""
        purge_host("host1", str(self.inv_path))
        content = self.inv_path.read_text()
        self.assertIn("    host2:", content)
        self.assertIn("        host2:", content)

    def test_purge_and_reregister_cycle(self) -> None:
        """Host can be purged and re-registered."""
        purge_host("host1", str(self.inv_path))
        content = self.inv_path.read_text()
        self.assertNotIn("host1", content)
        
        # Re-register should work
        result = register_host("host1", "desktop", str(self.inv_path))
        self.assertTrue(result)
        content = self.inv_path.read_text()
        self.assertIn("    host1:", content)

    def test_purge_last_host_does_not_leak_vars_into_previous(self) -> None:
        """Purging the host right before `children:` takes its vars with it.

        Its last var line has no newline once the file is split at
        `children:`; leaving it behind would hand host1 host2's address.
        """
        purge_host("host2", str(self.inv_path))
        inv = yaml.safe_load(self.inv_path.read_text())
        self.assertEqual(inv["all"]["hosts"], {"host1": {"ansible_host": "localhost"}})
        self.assertIsNone(inv["all"]["children"]["vps"]["hosts"])

    def test_purge_group_ref_on_last_line_without_newline(self) -> None:
        """A group reference on the file's final, unterminated line is removed."""
        self.inv_path.write_text(self.inv_path.read_text().rstrip("\n"))
        self.assertTrue(purge_host("host2", str(self.inv_path)))
        inv = yaml.safe_load(self.inv_path.read_text())
        self.assertNotIn("host2", inv["all"]["hosts"])
        self.assertIsNone(inv["all"]["children"]["vps"]["hosts"])


class TestInventoryIntegrity(unittest.TestCase):
    """Test inventory structure preservation."""

    def setUp(self) -> None:
        """Create temporary inventory with comments."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.inv_path = Path(self.temp_dir.name) / "inventory.yml"
        self.inv_path.write_text("""all:
  # Production hosts
  hosts:
    prod1:
      ansible_host: 10.0.0.1
  # Development and test environment
  children:
    desktop:
      hosts:
    vps:
      hosts:
        vps1:
          # Important server
""")

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_register_preserves_comments(self) -> None:
        """register_host preserves comments in file."""
        register_host("newhost", "desktop", str(self.inv_path))
        content = self.inv_path.read_text()
        self.assertIn("# Production hosts", content)
        self.assertIn("# Development and test environment", content)
        inventory = yaml.safe_load(content)
        self.assertIn("prod1", inventory["all"]["hosts"])
        self.assertEqual(inventory["all"]["hosts"]["newhost"], {
            "ansible_host": "localhost", "ansible_connection": "local"})
        self.assertIn("newhost", inventory["all"]["children"]["desktop"]["hosts"])

    def test_registration_rejects_missing_all_hosts_without_writing(self) -> None:
        content = "all:\n  children:\n    desktop:\n      hosts:\n"
        self.inv_path.write_text(content)
        with self.assertRaises(ValueError):
            register_host("newhost", "desktop", str(self.inv_path))
        self.assertEqual(self.inv_path.read_text(), content)

    def test_purge_preserves_comments(self) -> None:
        """purge_host preserves comments in file."""
        purge_host("prod1", str(self.inv_path))
        content = self.inv_path.read_text()
        self.assertIn("# Development and test environment", content)
        self.assertNotIn("prod1", content)


if __name__ == "__main__":
    unittest.main()
