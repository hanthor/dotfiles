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
  children:
    desktop:
      hosts:
        himachal:
        kerala:
    vps:
      hosts:
        matrix:
"""


def dev(name, ip, online=False, days_ago=1, tags=(), self_=False, foreign=False):
    return {"id": f"id-{name}-{ip}", "name": name, "ip": ip, "tags": list(tags), "online": online,
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


def test_test_vms_are_deleted_only_when_stale_and_k8s_proxies_only_on_request():
    devs = [dev("gate-old-vm", "100.1.1.1", days_ago=60, tags=["tag:k8s"]),
            dev("gate-new-vm", "100.1.1.2", days_ago=1, tags=["tag:k8s"]),
            dev("grafana", "100.1.1.3", days_ago=100, tags=["tag:k8s"])]
    assert [a["name"] for a in plan(devs)["gc"]] == ["gate-old-vm"]
    assert {a["name"] for a in plan(devs, k8s_days=90)["gc"]} == {"gate-old-vm", "grafana"}


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
