import sys
from datetime import datetime, timedelta, timezone

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "scripts"))
import tailnet  # noqa: E402
from inventory_parser import parse_host_vars, set_host_var  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

INVENTORY = """\
---
all:
  hosts:
    himachal:
      ansible_host: 100.73.3.51
      ansible_connection: ssh
    kerala:
      ansible_host: 100.96.124.92  # keep this comment
      ansible_user: james
      tailnet_name: kerala-1
    goa:
      ansible_host: localhost
      ansible_connection: local
    matrix:
      ansible_host: 100.73.19.81
      tailnet_name: reilly-asia-matrix
    telengana:
      ansible_host: 100.101.234.32
  children:
    desktop:
      hosts:
        himachal:
        kerala:
    vps:
      hosts:
        matrix:
        telengana:
"""


def dev(name, ip, online=False, days_ago=1, tags=(), self_=False, foreign=False):
    return {"id": f"id-{name}-{ip.replace('.', '-')}", "name": name, "ip": ip, "tags": list(tags), "online": online,
            "seen": NOW if online else NOW - timedelta(days=days_ago), "self": self_, "foreign": foreign}


def plan(devs, **kw):
    return tailnet.build_plan(devs, tailnet.load_inventory(INVENTORY), NOW, **kw)


def test_stale_duplicate_is_deleted_and_live_device_takes_the_name():
    p = plan([dev("himachal", "100.73.3.51", days_ago=24), dev("himachal-1", "100.79.182.70", online=True)])
    assert [a["name"] for a in p["gc"]] == ["himachal"]
    assert [(a["from"], a["to"]) for a in p["rename"]] == [("himachal-1", "himachal")]
    # inventory follows the live device's address
    assert {"op": "inventory", "host": "himachal", "key": "ansible_host", "from": "100.73.3.51", "to": "100.79.182.70"} in p["inventory"]


def test_auto_suffix_override_means_the_base_name_and_is_dropped_once_renamed():
    devs = [dev("kerala", "100.67.142.116", days_ago=57), dev("kerala-1", "100.96.124.92", days_ago=1)]
    p = plan(devs)
    assert [a["name"] for a in p["gc"]] == ["kerala"]
    assert [(a["from"], a["to"]) for a in p["rename"]] == [("kerala-1", "kerala")]
    assert {"op": "inventory", "host": "kerala", "key": "tailnet_name", "from": "kerala-1", "to": None} in p["inventory"]
    # standalone inventory fix must not drop the override before the rename really happened
    inv, _ = tailnet.plan_inventory(devs, tailnet.load_inventory(INVENTORY))
    assert inv == []


def test_the_newer_device_is_never_the_one_deleted():
    # the suffixed device is older than the plain-named one: keep the newer, delete the older
    p = plan([dev("kerala", "100.1.1.1", days_ago=1), dev("kerala-1", "100.2.2.2", days_ago=30)])
    assert [a["name"] for a in p["gc"]] == ["kerala-1"]
    assert p["rename"] == []


def test_online_self_and_foreign_devices_are_never_deleted():
    devs = [dev("himachal", "100.1.1.1", online=True), dev("himachal-1", "100.1.1.2", online=True),
            dev("gate-x-vm", "100.1.1.3", days_ago=90, self_=True), dev("gate-y-vm", "100.1.1.4", days_ago=90, foreign=True)]
    assert plan(devs)["gc"] == []


def test_stale_vms_are_deleted_but_k8s_proxies_are_reported_not_deleted():
    devs = [dev("gate-old-vm", "100.1.1.1", days_ago=60),
            dev("gate-k8s-vm", "100.1.1.2", days_ago=60, tags=["tag:k8s"]),
            dev("gate-new-vm", "100.1.1.3", days_ago=1),
            dev("grafana", "100.1.1.4", days_ago=100, tags=["tag:k8s"])]
    assert [a["name"] for a in plan(devs)["gc"]] == ["gate-old-vm"]
    p = plan(devs, k8s_days=90)
    assert [a["name"] for a in p["gc"]] == ["gate-old-vm"]
    assert any("gate-k8s-vm" in n and "unverifiable" in n for n in p["notes"])
    assert any("grafana" in n and "unverifiable" in n for n in p["notes"])


def test_two_live_devices_for_one_host_are_left_alone():
    p = plan([dev("kerala", "100.1.1.1", online=True), dev("kerala-1", "100.1.1.2", online=True)])
    assert p["gc"] == [] and p["rename"] == []


def test_retired_vps_hosts_are_ignored():
    p = plan([dev("reilly-asia-matrix", "100.73.19.81", days_ago=50)])
    assert p["gc"] == [] and p["rename"] == [] and p["inventory"] == []
    assert not any("matrix" in n for n in p["notes"])


def test_inventory_edits_keep_comments_and_other_hosts():
    out = tailnet.apply_inventory(INVENTORY, [
        {"host": "kerala", "key": "tailnet_name", "to": None},
        {"host": "kerala", "key": "ansible_host", "to": "100.9.9.9"},
    ])
    assert "tailnet_name: kerala-1" not in out
    assert "ansible_host: 100.9.9.9  # keep this comment" in out
    assert parse_host_vars(out)["himachal"] == parse_host_vars(INVENTORY)["himachal"]
    assert "reilly-asia-matrix" in out


def test_set_host_var_appends_a_missing_key_inside_the_block():
    out = set_host_var(INVENTORY, "goa", "tailnet_name", "goa-x")
    assert parse_host_vars(out)["goa"]["tailnet_name"] == "goa-x"
    assert parse_host_vars(out)["kerala"] == parse_host_vars(INVENTORY)["kerala"]
    assert set_host_var(INVENTORY, "nope", "k", "v") == INVENTORY


def test_status_normalisation_marks_shared_in_devices_foreign():
    status = {"MagicDNSSuffix": "tn.ts.net", "Self": {"ID": "n1", "DNSName": "me.tn.ts.net.", "TailscaleIPs": ["100.1.1.1"], "Online": True},
              "Peer": {"a": {"ID": "n2", "DNSName": "chuppvm.other.ts.net.", "TailscaleIPs": ["100.1.1.2"], "Online": False, "LastSeen": "2026-04-24T00:00:00Z"},
                       "b": {"ID": "n3", "DNSName": "dilli.tn.ts.net.", "TailscaleIPs": ["100.1.1.3"], "Online": False, "LastSeen": "0001-01-01T00:00:00Z", "Tags": ["tag:fleet"]}}}
    d = {x["name"]: x for x in tailnet.devices_from_status(status, NOW)}
    assert d["me"]["self"] and d["me"]["online"]
    assert d["chuppvm"]["foreign"] and not d["dilli"]["foreign"]
    assert d["dilli"]["seen"] is None and d["dilli"]["tags"] == ["tag:fleet"]


def api_device(device_name, node_id, **overrides):
    device = {"nodeId": node_id, "name": f"{device_name}.example.ts.net", "addresses": ["100.1.1.1"],
              "connectedToControl": False, "lastSeen": "2020-01-01T00:00:00Z"}
    device.update(overrides)
    return device


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    inventory = tmp_path / "inventory.yml"
    inventory.write_text(INVENTORY)
    monkeypatch.setattr(tailnet, "INVENTORY", str(inventory))
    monkeypatch.setattr(tailnet, "_secret", lambda: "test-secret")
    monkeypatch.setattr(tailnet, "local_status", lambda: {"Self": {"ID": "self-id"}})

    class FakeApi:
        def __init__(self):
            self.devices = []
            self.deletes = []
            self.renames = []
            self.reads = 0

        def list_devices(self):
            self.reads += 1
            return {"devices": self.devices}

        def delete(self, device_id):
            self.deletes.append(device_id)

        def rename(self, device_id, name):
            self.renames.append((device_id, name))

    api = FakeApi()
    monkeypatch.setattr(tailnet, "Api", lambda secret: api)
    return api, inventory


@pytest.mark.parametrize("presence", ["missing", None, "false", 0, 1, []])
@pytest.mark.parametrize("command", [["release", "himachal"], ["gc", "--apply"]])
def test_unverifiable_presence_blocks_all_deletions(fake_api, capsys, presence, command):
    api, inventory = fake_api
    uncertain = api_device("himachal", "uncertain")
    if presence == "missing":
        del uncertain["connectedToControl"]
    else:
        uncertain["connectedToControl"] = presence
    api.devices = [api_device("himachal-1", "candidate"), uncertain,
                   api_device("gate-old-vm", "test-vm")]
    original = inventory.read_text()
    assert tailnet.main(command) == 2
    assert api.deletes == [] and api.renames == []
    assert inventory.read_text() == original
    assert "presence is missing or not boolean" in capsys.readouterr().err


@pytest.mark.parametrize("field,value", [("nodeId", None), ("nodeId", ""),
                                        ("nodeId", "../other"), ("nodeId", "x?other"),
                                        ("name", ""), ("name", "invalid/name.example.ts.net")])
@pytest.mark.parametrize("command", [["release", "himachal"], ["sync", "--apply"]])
def test_invalid_identifiers_block_all_writes(fake_api, capsys, field, value, command):
    api, inventory = fake_api
    invalid = api_device("himachal", "bad-id", **{field: value})
    api.devices = [api_device("himachal-1", "candidate"), invalid,
                   api_device("gate-old-vm", "test-vm")]
    original = inventory.read_text()
    assert tailnet.main(command) == 2
    assert api.deletes == [] and api.renames == []
    assert inventory.read_text() == original
    assert "unverifiable:" in capsys.readouterr().err


def test_audit_reports_uncertain_presence_without_claiming_agreement(fake_api, capsys):
    api, _ = fake_api
    api.devices = [api_device("himachal", "node", connectedToControl=None)]
    assert tailnet.main(["audit"]) == 1
    captured = capsys.readouterr()
    assert "unverifiable:" in captured.err
    assert "agree" not in captured.out
    assert api.deletes == []


@pytest.mark.parametrize("name", ["matrix", "matrix-1", "matrix-1-2", "reilly-asia-matrix",
                                   "reilly-asia-matrix-17", "telengana", "TELENGANA-2"])
def test_release_refuses_retired_names_and_aliases_without_contacting_api(fake_api, capsys, name):
    api, _ = fake_api
    api.devices = [api_device(name.lower(), "retired")]
    assert tailnet.main(["release", name]) == 2
    assert api.reads == 0 and api.deletes == []
    assert "retired VPS" in capsys.readouterr().err


def test_release_deletes_only_confirmed_offline_nonself_owned_devices(fake_api):
    api, _ = fake_api
    api.devices = [api_device("himachal", "offline"),
                   api_device("himachal-1", "online", connectedToControl=True),
                   api_device("himachal-2", "self-id"),
                   api_device("himachal-3", "shared", isExternal=True),
                   api_device("himachal-4", "another-offline")]
    assert tailnet.main(["release", "himachal"]) == 0
    assert api.deletes == ["offline", "another-offline"]


def test_gc_keeps_retired_devices_even_if_tagged_as_stale_k8s_proxies(fake_api):
    api, _ = fake_api
    api.devices = [api_device("reilly-asia-matrix-1", "matrix", tags=["tag:k8s"]),
                   api_device("telengana", "telengana", tags=["tag:k8s"]),
                   api_device("gate-old-vm", "candidate")]
    assert tailnet.main(["gc", "--apply", "--k8s-days", "14"]) == 0
    assert api.deletes == ["candidate"]


def test_duplicate_ids_block_deletions(fake_api, capsys):
    api, _ = fake_api
    api.devices = [api_device("himachal", "duplicate"), api_device("himachal-1", "duplicate")]
    assert tailnet.main(["release", "himachal"]) == 2
    assert api.deletes == []
    assert "duplicate device ID" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["bihar", "bihar-1", "karnataka", "karnataka-1"])
def test_release_refuses_offline_home_cluster_nodes(fake_api, name):
    api, _ = fake_api
    api.devices = [api_device(name, "home-node")]
    assert tailnet.main(["release", name]) == 2
    assert api.reads == 0 and api.deletes == []


def test_gc_keeps_home_cluster_nodes_with_explicit_k8s_gc(fake_api):
    api, _ = fake_api
    api.devices = [api_device("bihar", "bihar-node", tags=["tag:k8s"]),
                   api_device("karnataka-1", "worker-node", tags=["tag:k8s"]),
                   api_device("gate-old-vm", "candidate")]
    assert tailnet.main(["gc", "--apply", "--k8s-days", "14"]) == 0
    assert api.deletes == ["candidate"]


def test_k8s_gc_apply_refuses_unverifiable_proxies_but_audit_reports_them(fake_api, capsys):
    api, _ = fake_api
    api.devices = [api_device("lemonade", "proxy", tags=["tag:k8s"]),
                   api_device("gate-old-vm", "candidate")]
    assert tailnet.main(["audit", "--k8s-days", "14"]) == 1
    assert "lemonade" in capsys.readouterr().out
    assert tailnet.main(["gc", "--apply", "--k8s-days", "14"]) == 2
    assert api.deletes == []
    assert "ownership unverifiable" in capsys.readouterr().out


def test_release_refuses_k8s_proxy_without_deleting_other_matches(fake_api, capsys):
    api, _ = fake_api
    api.devices = [api_device("lemonade", "proxy", tags=["tag:k8s"]),
                   api_device("lemonade-1", "candidate")]
    assert tailnet.main(["release", "lemonade"]) == 2
    assert api.deletes == []
    assert "ownership unverifiable" in capsys.readouterr().err
