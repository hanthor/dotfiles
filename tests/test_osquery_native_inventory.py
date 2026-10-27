import importlib.util
import json
import sys
import shutil

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "units"))
sys.path.insert(0, str(REPO / "scripts"))
import osquery_native_inventory as native

spec = importlib.util.spec_from_file_location("osquery_fleet_native_test", REPO / "scripts/osquery-fleet.py")
fleet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fleet)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_effective_variables_nested_groups_and_alias_targets(tmp_path):
    path = tmp_path / "inventory.yml"
    put(path, {"all": {"vars": {"ansible_user": "base"}, "hosts": {
        "controller": {"ansible_connection": "local"}, "phone": {"ansible_host": "100.86.202.86"}},
        "children": {"vps": {"children": {"retired": {"hosts": {"old": {}}}}},
                     "mobile": {"vars": {"ansible_port": 2222, "ansible_connection": "local"}, "children": {
                         "phones": {"hosts": {"phone": {"tailnet_name": "mumbai"}}}}}}}})
    put(tmp_path / "group_vars/all.yml", {"ansible_user": "all-user", "ansible_connection": "ssh", "secret": "do-not-copy"})
    put(tmp_path / "group_vars/mobile.yml", {"ansible_user": "mobile-user", "ansible_port": 2022})
    put(tmp_path / "group_vars/phones.yml", {"ansible_user": "phone-user"})
    put(tmp_path / "host_vars/phone.yml", {"ansible_user": "host-user", "ansible_port": 3333})
    got = native.load_inventory(path)
    assert fleet.group_hosts(got, "vps") == {"old"}
    variables = got["_meta"]["hostvars"]["phone"]
    assert variables == {"ansible_host": "100.86.202.86", "tailnet_name": "mumbai",
                         "ansible_user": "host-user", "ansible_port": 3333, "ansible_connection": "ssh"}
    command = fleet.report_command("phone", variables, {"controller"})
    assert command[command.index("-l") + 1] == "host-user"
    assert command[command.index("-p") + 1] == "3333"
    assert command[-2] == "100.86.202.86"
    assert "do-not-copy" not in repr(got)


def test_same_depth_group_priority_and_inventory_host_override(tmp_path):
    path = tmp_path / "inventory.yml"
    put(path, {"all": {"hosts": {"host": {"ansible_user": "inventory-host"}}, "children": {
        "alpha": {"vars": {"ansible_group_priority": 20, "ansible_port": 2020}, "hosts": {"host": {}}},
        "zulu": {"vars": {"ansible_group_priority": 1, "ansible_port": 3030}, "hosts": {"host": {}}}}}})
    values = native.load_inventory(path)["_meta"]["hostvars"]["host"]
    assert values["ansible_user"] == "inventory-host"
    assert values["ansible_port"] == 2020


def test_cycle_and_bad_inventory_fail_without_leaking_values(tmp_path, capsys):
    path = tmp_path / "inventory.yml"
    put(path, {"all": {"children": {"parent": {"children": {"all": None}}}}})
    with pytest.raises(ValueError, match="cycle"):
        native.load_inventory(path)
    put(path, {"all": {"hosts": {"host": {"ansible_host": "{{ super_secret }}"}}}})
    assert fleet.main(["--inventory", str(path)]) == 1
    captured = capsys.readouterr()
    assert "super_secret" not in captured.out + captured.err
    assert "unresolved templates" in captured.err


def test_sanitized_snapshot_preserves_exclusions_without_yaml_dependency(tmp_path):
    path = tmp_path / "snapshot.yml"
    put(path, {"all": {"hosts": {"kerala": {"osquery_supported": False}},
                       "children": {"vps": {"hosts": {"matrix": {}}}}}})
    got = native.load_inventory(path)
    assert fleet.group_hosts(got, "vps") == {"matrix"}
    assert got["_meta"]["hostvars"]["kerala"]["osquery_supported"] is False


@pytest.mark.skipif(shutil.which("yq") is None, reason="yq is required to parse the real inventory")
def test_real_inventory_poller_snapshot_preserves_effective_hosts_and_exclusions(tmp_path):
    renderer_spec = importlib.util.spec_from_file_location(
        "osquery_poller_renderer", REPO / "units/osquery-poller-render.py")
    renderer = importlib.util.module_from_spec(renderer_spec)
    renderer_spec.loader.exec_module(renderer)
    source = REPO / "inventory.yml"
    expected = native.load_inventory(source)
    snapshot = tmp_path / "inventory.yml"
    put(snapshot, renderer.inventory(source))
    installed = native.load_inventory(snapshot)

    assert installed["_meta"]["hostvars"] == expected["_meta"]["hostvars"]
    for group in ("vps", "test_fleet", "termux_hosts"):
        assert fleet.group_hosts(installed, group) == fleet.group_hosts(expected, group)


@pytest.mark.skipif(shutil.which("yq") is None, reason="yq is required to parse the real inventory")
def test_real_inventory_unavailable_discovery_is_not_offline(monkeypatch):
    inventory = native.load_inventory(REPO / "inventory.yml")
    calls = []
    monkeypatch.setattr(fleet, "command_json", lambda command, label: calls.append(command) or {})
    result = fleet.collect_fleet(inventory, {}, identities={"punjab"},
                                 discovery_error="Tailscale could not run")
    by_host = {host["inventory_host"]: host for host in result["hosts"]}
    for host in ("mumbai", "dilli"):
        assert by_host[host]["status"] == "error"
        assert by_host[host]["reason"] == "Tailscale could not run"
    assert not any(host["status"] == "offline" for host in result["hosts"])
    assert calls == [["sudo", "-n", "cat", fleet.REPORT_PATH]]

def test_host_gate_checks_nested_vps_and_rejects_unknown_machine(tmp_path, capsys):
    path = tmp_path / "inventory.yml"
    put(path, {"all": {"children": {"vps": {"children": {
        "retired": {"hosts": {"old": {}}}}}, "server": {"hosts": {"current": {}}}}}})
    assert native.main(["groups", str(path), "old", "vps", "server"]) == 0
    assert capsys.readouterr().out.strip() == "true false"
    assert native.main(["groups", str(path), "mystery", "vps"]) == 1
    assert "absent from inventory" in capsys.readouterr().err


def test_osquery_gates_inherit_group_settings_and_host_overrides(tmp_path, capsys):
    path = tmp_path / "inventory.yml"
    put(path, {"all": {"children": {"server": {"hosts": {"node": {}},
                                                 "vars": {"skip_osquery": True}}}}})
    put(tmp_path / "group_vars/server.yml", {"osquery_supported": False, "osquery_poller_enabled": True})
    put(tmp_path / "host_vars/node.yml", {"skip_osquery": False, "osquery_version": "5.23.1"})
    assert native.main(["osquery-settings", str(path), "node"]) == 0
    assert json.loads(capsys.readouterr().out) == {"skip_osquery": False, "osquery_supported": False,
                                                 "osquery_poller_enabled": True, "osquery_version": "5.23.1"}
