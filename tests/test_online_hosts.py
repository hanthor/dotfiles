import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from conftest import REPO, write_stub

sys.path.insert(0, str(REPO / "scripts"))
from inventory_parser import parse_inventory
from online_hosts import online_peers, tailnet_names

INVENTORY = (REPO / "inventory.yml").read_text()
GROUPS = {"all", "hosts", "children", "desktop", "server", "vps", "test_fleet", "termux_hosts"}


def test_real_inventory_matches_yaml():
    all_hosts, vps = parse_inventory(INVENTORY)
    inv = yaml.safe_load(INVENTORY)["all"]
    assert all_hosts == set(inv["hosts"])
    assert vps == set(inv["children"]["vps"]["hosts"])


def test_real_inventory_vps_and_groups():
    all_hosts, vps = parse_inventory(INVENTORY)
    assert {"matrix", "telengana"} <= vps
    assert {"matrix", "telengana"} <= all_hosts
    assert not (all_hosts | vps) & GROUPS
    assert {"test-fleet-fedora", "test-fleet-node2"} <= all_hosts


def test_parse_ignores_comments_and_other_groups():
    text = (
        "all:\n  hosts:\n    a:\n      ansible_host: x\n    # b:\n"
        "  children:\n    desktop:\n      hosts:\n        a:\n"
        "    # vps:\n    vps:\n      hosts:\n        z:\n"
    )
    assert parse_inventory(text) == ({"a"}, {"z"})


def test_online_peers():
    status = {"Peer": {
        "1": {"Online": True, "DNSName": "Kerala.tail.ts.net.", "HostName": "kerala-laptop"},
        "2": {"Online": False, "DNSName": "goa.tail.ts.net.", "HostName": "goa"},
        "3": {"Online": True, "HostName": "Dilli"},
        "4": {"Online": True, "DNSName": "mumbai.tail.ts.net."},
        "5": {"Online": True, "DNSName": "pixel-9a.tail.ts.net.", "HostName": "localhost"},
    }}
    # MagicDNS name wins; HostName (not unique: "localhost") only without one.
    assert online_peers(status) == {"kerala", "dilli", "mumbai", "pixel-9a"}
    assert online_peers({}) == set()
    assert online_peers({"Peer": None}) == set()


def test_real_inventory_tailnet_names():
    inv = yaml.safe_load(INVENTORY)["all"]["hosts"]
    expected = {h: v["tailnet_name"] for h, v in inv.items() if v and "tailnet_name" in v}
    assert tailnet_names(INVENTORY) == expected
    assert expected["termux"] == "pixel-9a"


def run_script(bindir, env, tailscale_body):
    write_stub(bindir, "tailscale", tailscale_body)
    return subprocess.run([sys.executable, str(REPO / "scripts/online_hosts.py")],
                          env=env, capture_output=True, text=True, timeout=30)


def test_end_to_end_excludes_vps_and_self(stub_env, tmp_path):
    bindir, env = stub_env
    peers = {str(i): {"Online": True, "DNSName": f"{h}.tail.ts.net.", "HostName": h}
             for i, h in enumerate(["kerala", "matrix", "telengana", "test-fleet-fedora",
                                    "stranger", os.uname().nodename])}
    peers["x"] = {"Online": False, "DNSName": "goa.tail.ts.net.", "HostName": "goa"}
    (tmp_path / "ts.json").write_text(json.dumps({"Peer": peers}))
    r = run_script(bindir, env, f"cat {tmp_path / 'ts.json'}\n")
    assert r.returncode == 0, r.stderr
    got = set(r.stdout.split())
    try:
        me = Path("/etc/dotfiles-machine").read_text().strip().lower()
    except OSError:
        me = os.uname().nodename.lower()
    assert got == {"kerala", "test-fleet-fedora"} - {me}


def test_end_to_end_maps_tailnet_name_to_inventory_host(stub_env, tmp_path):
    """termux is online as `pixel-9a` (HostName `localhost`); matrix as
    `reilly-asia-matrix` but it is a retired VPS, so it stays out."""
    bindir, env = stub_env
    peers = {
        "1": {"Online": True, "DNSName": "pixel-9a.tail.ts.net.", "HostName": "localhost"},
        "2": {"Online": True, "DNSName": "reilly-asia-matrix.tail.ts.net.", "HostName": "matrix"},
        "3": {"Online": True, "DNSName": "termux-impostor.tail.ts.net.", "HostName": "termux"},
    }
    (tmp_path / "ts.json").write_text(json.dumps({"Peer": peers}))
    r = run_script(bindir, env, f"cat {tmp_path / 'ts.json'}\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["termux"]


def test_peers_mode_needs_no_inventory(stub_env, tmp_path):
    bindir, env = stub_env
    (tmp_path / "ts.json").write_text(json.dumps({"Peer": {
        "1": {"Online": True, "DNSName": "goa.tail.ts.net.", "HostName": "goa"}}}))
    write_stub(bindir, "tailscale", f"cat {tmp_path / 'ts.json'}\n")
    lone = tmp_path / "online_hosts.py"
    lone.write_text((REPO / "scripts/online_hosts.py").read_text())
    r = subprocess.run([sys.executable, str(lone), "--peers"], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "goa\n"


def test_end_to_end_tailscale_failure(stub_env):
    bindir, env = stub_env
    r = run_script(bindir, env, "echo 'daemon not running' >&2\nexit 1\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "\n"
