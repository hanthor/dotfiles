"""Tests for purge-machine.py and register-machine.py."""
import subprocess
from pathlib import Path
import tempfile
import textwrap

import pytest

from conftest import REPO


def run_script(script_name, *args, cwd=None):
    """Run a Python script and return (returncode, stdout, stderr)."""
    return subprocess.run(
        ["python3", str(REPO / "scripts" / script_name), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10
    )


class TestPurgeMachine:
    """Tests for purge-machine.py — inventory and host_vars removal."""

    def test_purge_removes_host_block(self, tmp_path):
        """Purge removes the host block from inventory."""
        inv = tmp_path / "inventory.yml"
        inv.write_text(textwrap.dedent("""
            all:
              hosts:
                host1:
                  ansible_host: 192.168.1.1
                host2:
                  ansible_host: 192.168.1.2
              children:
                webservers:
                  hosts:
                    host1:
        """).strip())
        
        result = run_script("purge-machine.py", "host1", str(inv), cwd=tmp_path)
        assert result.returncode == 0
        assert "Removed host1" in result.stdout
        
        content = inv.read_text()
        assert "host1:" not in content
        assert "host2:" in content

    def test_purge_removes_group_reference(self, tmp_path):
        """Purge removes host reference from group's hosts list."""
        inv = tmp_path / "inventory.yml"
        inv.write_text(textwrap.dedent("""
            all:
              hosts:
                host1:
                  ansible_host: 192.168.1.1
              children:
                webservers:
                  hosts:
                    host1:
                    host2:
        """).strip())
        
        result = run_script("purge-machine.py", "host1", str(inv), cwd=tmp_path)
        assert result.returncode == 0
        
        content = inv.read_text()
        assert "host1:" not in content
        assert "host2:" in content

    def test_purge_removes_host_vars(self, tmp_path):
        """Purge deletes the host_vars/<name>.yml file if present."""
        inv = tmp_path / "inventory.yml"
        host_vars_dir = tmp_path / "host_vars"
        host_vars_dir.mkdir()
        
        inv.write_text(textwrap.dedent("""
            all:
              hosts:
                host1:
                  ansible_host: 192.168.1.1
        """).strip())
        
        hostvars_file = host_vars_dir / "host1.yml"
        hostvars_file.write_text("key: value\n")
        
        result = run_script("purge-machine.py", "host1", str(inv), cwd=tmp_path)
        assert result.returncode == 0
        assert "Deleted" in result.stdout
        assert not hostvars_file.exists()

    def test_purge_not_found(self, tmp_path):
        """Purge fails and returns 1 if host not found."""
        inv = tmp_path / "inventory.yml"
        inv.write_text(textwrap.dedent("""
            all:
              hosts:
                host1:
                  ansible_host: 192.168.1.1
        """).strip())
        
        result = run_script("purge-machine.py", "nonexistent", str(inv), cwd=tmp_path)
        assert result.returncode == 1
        assert "not found" in result.stdout

    def test_purge_preserves_other_hosts(self, tmp_path):
        """Purge leaves other hosts and groups intact."""
        inv = tmp_path / "inventory.yml"
        inv.write_text(textwrap.dedent("""
            all:
              hosts:
                host1:
                  ansible_host: 192.168.1.1
                host2:
                  ansible_host: 192.168.1.2
              children:
                webservers:
                  hosts:
                    host1:
                    host2:
                databases:
                  hosts:
                    host2:
        """).strip())
        
        original = inv.read_text()
        result = run_script("purge-machine.py", "host1", str(inv), cwd=tmp_path)
        assert result.returncode == 0
        
        content = inv.read_text()
        # host1 removed, host2 and groups preserved
        assert "host1:" not in content
        assert "host2:" in content
        assert "webservers:" in content
        assert "databases:" in content
        # host2 should appear in both groups
        lines = content.split("\n")
        webservers_idx = next(i for i, l in enumerate(lines) if "webservers:" in l)
        databases_idx = next(i for i, l in enumerate(lines) if "databases:" in l)
        assert webservers_idx < databases_idx
        assert any("host2" in lines[i] for i in range(webservers_idx, databases_idx))
