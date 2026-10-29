import json
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


SCRIPT = REPO / "home-k3s" / "firewall.sh"
POLICY = "k3s-pod-egress"
EGRESS_RULE = 'rule family="ipv4" source address="10.42.0.0/16" accept'
KUBELET_RULE = (
    'rule family="ipv4" source address="10.42.0.0/16" '
    'destination address="100.66.158.127/32" port port="10250" protocol="tcp" accept'
)
API_RULE = (
    'rule family="ipv4" source address="100.64.0.0/10" '
    'destination address="100.66.158.127/32" port port="6443" protocol="tcp" accept'
)


def empty_policy():
    return {
        "target": "CONTINUE", "priority": "-1", "disable": "no",
        "ingress-zones": [], "egress-zones": [], "services": [], "ports": [],
        "protocols": [], "masquerade": "no", "forward-ports": [],
        "source-ports": [], "icmp-blocks": [], "rich rules": [],
    }


@pytest.fixture
def firewall(tmp_path, stub_env):
    bindir, env = stub_env
    write_stub(bindir, "id", 'echo 0\n')
    write_stub(bindir, "hostname", 'echo karnataka\n')
    write_stub(
        bindir,
        "firewall-cmd",
        r'''exec python3 - "$@" <<'PY'
import json, os, sys
p = os.environ["FIREWALL_STATE"]
s = json.load(open(p))
args = sys.argv[1:]
scope = "permanent" if "--permanent" in args else "runtime"
zone = s[scope]
policy_name = next((a.split("=", 1)[1] for a in args if a.startswith("--policy=")), None)
if "--zone=public" in args:
    zone = zone["public"]
if "--state" in args:
    print("running")
elif "--get-default-zone" in args:
    print(s["default"])
elif "--get-zones" in args:
    print("internal public")
elif "--get-policies" in args:
    print(" ".join(zone["policies"]))
elif any(a.startswith("--info-policy=") for a in args):
    name = next(a.split("=", 1)[1] for a in args if a.startswith("--info-policy="))
    policy = zone["policies"][name]
    active = bool(policy["ingress-zones"] and policy["egress-zones"])
    print(name + (" (active)" if active else ""))
    for key in ("disable", "priority", "target", "ingress-zones", "egress-zones",
                "services", "ports", "protocols", "masquerade", "forward-ports",
                "source-ports", "icmp-blocks", "rich rules"):
        value = policy[key]
        if key == "rich rules":
            print("  rich rules: " + ("\n\t" + "\n\t".join(value) if value else ""))
        else:
            print("  " + key + ": " + (" ".join(value) if isinstance(value, list) else value))
elif any(a.startswith("--new-policy=") for a in args):
    if scope != "permanent":
        sys.exit(2)
    op = next(a for a in args if a.startswith("--new-policy="))
    name = op.split("=", 1)[1]
    zone["policies"][name] = {
        "target": "CONTINUE", "priority": "-1", "disable": "no",
        "ingress-zones": [], "egress-zones": [], "services": [], "ports": [],
        "protocols": [], "masquerade": "no", "forward-ports": [],
        "source-ports": [], "icmp-blocks": [], "rich rules": [],
    }
    s["changes"].append([scope, op])
    with open(p, "w") as f:
        json.dump(s, f)
elif "--list-interfaces" in args:
    print(" ".join(zone["interfaces"]))
elif "--list-sources" in args:
    print(" ".join(zone["sources"]))
else:
    op = next(a for a in args if a.startswith(("--query-", "--add-", "--change-")))
    command, _, value = op.partition("=")
    if policy_name:
        policy = zone["policies"][policy_name]
        key = {"--query-rich-rule": "rich rules", "--add-rich-rule": "rich rules",
               "--query-ingress-zone": "ingress-zones", "--add-ingress-zone": "ingress-zones",
               "--query-egress-zone": "egress-zones", "--add-egress-zone": "egress-zones"}[command]
        if command.startswith("--query-"):
            if os.environ.get("FAIL_QUERY"):
                sys.exit(2)
            sys.exit(0 if value in policy[key] else 1)
        policy[key].append(value)
    else:
        key = {"--query-rich-rule": "rule", "--add-rich-rule": "rule",
               "--query-forward": "forward", "--add-forward": "forward",
               "--query-interface": "interfaces", "--change-interface": "interfaces"}[command]
        if command.startswith("--query-"):
            if os.environ.get("FAIL_QUERY"):
                sys.exit(2)
            present = value in zone[key] if key == "interfaces" else zone[key]
            if key == "rule" and present:
                present = value == zone[key]
            sys.exit(0 if present else 1)
        if key == "interfaces":
            zone[key].append(value)
        else:
            if not (key == "rule" and "--zone=public" in args and os.environ.get("IGNORE_API_ADD")):
                zone[key] = value if key == "rule" else True
    s["changes"].append([scope, op])
    with open(p, "w") as f:
        json.dump(s, f)
PY
''',
    )
    path = tmp_path / "firewall.json"
    state = {
        "default": "public",
        "runtime": {"interfaces": [], "sources": [], "forward": False, "rule": "", "policies": {}},
        "permanent": {"interfaces": [], "sources": [], "forward": False, "rule": "", "policies": {}},
        "changes": [],
    }
    for scope in ("runtime", "permanent"):
        state[scope]["public"] = {"interfaces": [], "sources": [], "rule": ""}
    path.write_text(json.dumps(state))
    env["FIREWALL_STATE"] = str(path)

    def run(mode):
        result = subprocess.run(["bash", str(SCRIPT), mode], env=env, text=True, capture_output=True)
        return result, json.loads(path.read_text())

    return path, env, run


def test_apply_is_scoped_and_idempotent(firewall):
    path, _, run = firewall
    result, state = run("--apply")
    assert result.returncode != 0
    assert "runtime policy is absent" in result.stderr
    expected = empty_policy()
    expected.update({"ingress-zones": ["internal"], "egress-zones": ["public"],
                     "rich rules": [EGRESS_RULE]})
    for scope in ("runtime", "permanent"):
        zone = state[scope]
        assert zone["interfaces"] == ["cni0"]
        assert zone["sources"] == []
        assert zone["forward"] is True
        assert zone["public"] == {"interfaces": [], "sources": [], "rule": API_RULE}
        assert zone["rule"] == KUBELET_RULE
    assert state["permanent"]["policies"] == {POLICY: expected}
    assert state["runtime"]["policies"] == {}
    ops = [op for scope, op in state["changes"] if scope == "permanent"]
    assert ops.index("--add-rich-rule=" + EGRESS_RULE) < ops.index("--add-egress-zone=public")
    result, unchanged = run("--apply")
    assert result.returncode != 0
    assert unchanged == state
    result, checked = run("--check")
    assert result.returncode != 0
    assert "Missing policy k3s-pod-egress (runtime)" in result.stderr
    assert checked == state
    # Model firewalld starting from its permanent configuration.
    state["runtime"]["policies"][POLICY] = expected
    path.write_text(json.dumps(state))
    result, checked = run("--check")
    assert result.returncode == 0, result.stderr
    assert checked == state
    result, unchanged = run("--apply")
    assert result.returncode == 0, result.stderr
    assert unchanged == state


def test_check_reports_missing_without_changes(firewall):
    _, _, run = firewall
    result, state = run("--check")
    assert result.returncode != 0
    assert "Missing" in result.stderr
    assert not state["changes"]


@pytest.mark.parametrize("tailnet_interfaces", [[], ["tailscale0"]])
def test_check_accepts_host_rule_and_egress_policy(firewall, tailnet_interfaces):
    path, _, run = firewall
    state = json.loads(path.read_text())
    policy = empty_policy()
    policy.update({"ingress-zones": ["internal"], "egress-zones": ["public"],
                   "rich rules": [EGRESS_RULE]})
    for scope in ("runtime", "permanent"):
        state[scope].update(interfaces=["cni0"], forward=True, rule=KUBELET_RULE,
                            policies={POLICY: policy})
        state[scope]["public"]["rule"] = API_RULE
        state[scope]["public"]["interfaces"] = tailnet_interfaces
    path.write_text(json.dumps(state))
    result, after = run("--check")
    assert result.returncode == 0, result.stderr
    assert after == state


@pytest.mark.parametrize("scope", ["runtime", "permanent"])
@pytest.mark.parametrize("field,value", [("interfaces", "eth0"), ("sources", "10.42.0.0/16")])
def test_foreign_interface_or_source_refused_before_any_changes(firewall, scope, field, value):
    path, _, run = firewall
    state = json.loads(path.read_text())
    state[scope][field] = [value]
    path.write_text(json.dumps(state))
    result, after = run("--apply")
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert after == state


@pytest.mark.parametrize("scope", ["runtime", "permanent"])
@pytest.mark.parametrize("field,value", [
    ("target", "ACCEPT"), ("priority", "1000"), ("disable", "yes"),
    ("ingress-zones", ["internal", "home"]), ("egress-zones", ["ANY"]),
    ("services", ["ssh"]), ("masquerade", "yes"), ("rich rules", ["rule accept"]),
])
def test_foreign_policy_refused_before_any_changes(firewall, scope, field, value):
    path, _, run = firewall
    state = json.loads(path.read_text())
    policy = empty_policy()
    policy[field] = value
    state[scope]["policies"][POLICY] = policy
    path.write_text(json.dumps(state))
    result, after = run("--apply")
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert after == state


def test_partial_policy_is_completed(firewall):
    path, _, run = firewall
    state = json.loads(path.read_text())
    policy = empty_policy()
    policy["rich rules"] = [EGRESS_RULE]
    state["permanent"]["policies"][POLICY] = policy
    path.write_text(json.dumps(state))
    result, after = run("--apply")
    assert result.returncode != 0
    assert "runtime policy is absent" in result.stderr
    assert after["permanent"]["policies"][POLICY]["ingress-zones"] == ["internal"]
    assert after["permanent"]["policies"][POLICY]["egress-zones"] == ["public"]
    assert after["permanent"]["policies"][POLICY]["rich rules"] == [EGRESS_RULE]


def test_internal_default_zone_refused(firewall):
    path, _, run = firewall
    state = json.loads(path.read_text())
    state["default"] = "internal"
    path.write_text(json.dumps(state))
    result, after = run("--apply")
    assert result.returncode != 0
    assert after == state


def test_query_error_is_not_treated_as_missing(firewall):
    _, env, run = firewall
    env["FAIL_QUERY"] = "1"
    result, state = run("--apply")
    assert result.returncode == 2
    assert not state["changes"]


@pytest.mark.parametrize("scope", ["runtime", "permanent"])
def test_missing_api_rule_is_reported_without_changes(firewall, scope):
    path, _, run = firewall
    run("--apply")
    state = json.loads(path.read_text())
    state[scope]["public"]["rule"] = ""
    path.write_text(json.dumps(state))
    result, after = run("--check")
    assert result.returncode != 0
    assert "6443" in result.stderr
    assert after == state


@pytest.mark.parametrize("scope", ["runtime", "permanent"])
@pytest.mark.parametrize("drift", ["default", "interface", "source"])
def test_api_zone_classification_drift_refused_before_changes(firewall, scope, drift):
    path, _, run = firewall
    state = json.loads(path.read_text())
    if drift == "default":
        state["default"] = "external"
    elif drift == "interface":
        state[scope]["interfaces"] = ["tailscale0"]
    else:
        state[scope]["public"]["sources"] = ["100.103.187.46/32"]
    path.write_text(json.dumps(state))
    result, after = run("--apply")
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert after == state


def test_apply_verifies_api_rule_was_actually_installed(firewall):
    path, env, run = firewall
    policy = empty_policy()
    policy.update({"ingress-zones": ["internal"], "egress-zones": ["public"],
                   "rich rules": [EGRESS_RULE]})
    state = json.loads(path.read_text())
    for scope in ("runtime", "permanent"):
        state[scope]["policies"][POLICY] = policy
    path.write_text(json.dumps(state))
    env["IGNORE_API_ADD"] = "1"
    result, after = run("--apply")
    assert result.returncode != 0
    assert "6443" in result.stderr
    for scope in ("runtime", "permanent"):
        assert not after[scope]["public"]["rule"]


BRIDGE_SCRIPT = REPO / "home-k3s" / "firewall-egress-bridge.sh"
RULE4 = 'rule priority="-1" family="ipv4" source NOT address="10.42.0.0/16" drop'
RULE6 = 'rule priority="-1" family="ipv6" source address="::/0" drop'


@pytest.fixture
def bridge(tmp_path, stub_env):
    bindir, env = stub_env
    write_stub(bindir, "id", 'echo 0\n')
    write_stub(bindir, "hostname", 'echo karnataka\n')
    write_stub(bindir, "systemd-run", 'printf "timer\\n" >> "$BRIDGE_LOG"\ntouch "$TIMER_FILE"\n')
    write_stub(bindir, "systemctl", r'''case "$1" in
  is-active) test -f "$TIMER_FILE" ;;
  stop) rm -f "$TIMER_FILE" ;;
  *) exit 2 ;;
esac
''')
    write_stub(bindir, "firewall-cmd", r'''exec python3 - "$@" <<'PY'
import json, os, sys
p = os.environ["BRIDGE_FIREWALL_STATE"]
s = json.load(open(p))
args = sys.argv[1:]
scope = "permanent" if "--permanent" in args else "runtime"
policy = s["policy"]
zone = next((a.split("=", 1)[1] for a in args if a.startswith("--zone=")), "")
if "--state" in args:
    print("running")
elif "--get-default-zone" in args:
    print(s["default"])
elif "--get-zones" in args:
    print("internal public home trusted external")
elif "--list-interfaces" in args:
    print(" ".join(s[scope]["interfaces"]))
elif "--list-sources" in args:
    print(" ".join(s[scope]["sources"].get(zone, [])))
elif any(a.startswith("--info-policy=") for a in args):
    print("gateway-lan-to-world" + (" (disabled)" if policy["disable"] == "yes" else " (active)"))
    for key in ("disable", "priority", "target", "ingress-zones", "egress-zones",
                "services", "ports", "protocols", "masquerade", "forward-ports",
                "source-ports", "icmp-blocks", "rich rules"):
        value = policy[key]
        if key == "rich rules":
            print("  rich rules: " + ("\n\t" + "\n\t".join(value) if value else ""))
        else:
            print("  " + key + ": " + (" ".join(value) if isinstance(value, list) else value))
else:
    op = next(a for a in args if a.startswith(("--query-", "--add-", "--remove-")))
    command, _, value = op.partition("=")
    key = {"--query-disable": "disable", "--add-disable": "disable", "--remove-disable": "disable",
           "--query-rich-rule": "rich rules", "--add-rich-rule": "rich rules", "--remove-rich-rule": "rich rules",
           "--query-ingress-zone": "ingress-zones", "--add-ingress-zone": "ingress-zones", "--remove-ingress-zone": "ingress-zones",
           "--query-egress-zone": "egress-zones", "--add-egress-zone": "egress-zones", "--remove-egress-zone": "egress-zones"}[command]
    if command.startswith("--query-"):
        sys.exit(0 if (policy[key] == "yes" if key == "disable" else value in policy[key]) else 1)
    with open(os.environ["BRIDGE_LOG"], "a") as f:
        f.write(op + "\n")
    if os.environ.get("FAIL_OP") == command and not os.path.exists(os.environ["FAIL_ONCE"]):
        open(os.environ["FAIL_ONCE"], "w").close()
        sys.exit(2)
    if key == "disable":
        policy[key] = "yes" if command == "--add-disable" else "no"
    elif command.startswith("--add-"):
        policy[key].append(value)
    else:
        policy[key].remove(value)
    with open(p, "w") as f:
        json.dump(s, f)
PY
''')
    path = tmp_path / "bridge-firewall.json"
    policy = empty_policy()
    policy.update({"target": "ACCEPT", "priority": "1000", "disable": "yes",
                   "ingress-zones": ["internal", "home", "trusted"],
                   "egress-zones": ["external", "public"], "services": ["ftp", "tftp"]})
    path.write_text(json.dumps({
        "default": "public", "policy": policy,
        "runtime": {"interfaces": ["cni0"], "sources": {}},
        "permanent": {"interfaces": ["cni0"], "sources": {}},
    }))
    env.update({"BRIDGE_FIREWALL_STATE": str(path), "BRIDGE_LOG": str(tmp_path / "ops"),
                "TIMER_FILE": str(tmp_path / "timer"), "FAIL_ONCE": str(tmp_path / "failed"),
                "K3S_BRIDGE_STATE_DIR": str(tmp_path / "managed")})

    def run(mode):
        result = subprocess.run(["bash", str(BRIDGE_SCRIPT), mode], env=env, text=True, capture_output=True)
        return result, json.loads(path.read_text())

    return path, env, run


def test_bridge_arms_before_changes_and_timer_restores(bridge):
    path, env, run = bridge
    original = json.loads(path.read_text())
    result, state = run("--apply")
    assert result.returncode == 0, result.stderr
    policy = state["policy"]
    assert policy["disable"] == "no"
    assert policy["ingress-zones"] == ["internal"]
    assert policy["egress-zones"] == ["public"]
    assert set(policy["rich rules"]) == {RULE4, RULE6}
    operations = Path(env["BRIDGE_LOG"]).read_text().splitlines()
    assert operations[0] == "timer"
    assert operations.index("--add-rich-rule=" + RULE4) < operations.index("--remove-disable")
    assert operations.index("--add-rich-rule=" + RULE6) < operations.index("--remove-disable")
    result, restored = run("--timer-rollback")
    assert result.returncode == 0, result.stderr
    assert set(restored["policy"]["ingress-zones"]) == set(original["policy"]["ingress-zones"])
    assert set(restored["policy"]["egress-zones"]) == set(original["policy"]["egress-zones"])
    assert restored["policy"]["disable"] == "yes"
    assert restored["policy"]["rich rules"] == []
    result, _ = run("--cleanup")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scope", ["runtime", "permanent"])
def test_bridge_refuses_source_bindings_in_other_zones(bridge, scope):
    path, _, run = bridge
    state = json.loads(path.read_text())
    state[scope]["sources"]["public"] = ["10.42.0.0/16"]
    path.write_text(json.dumps(state))
    result, unchanged = run("--apply")
    assert result.returncode != 0
    assert "source bindings" in result.stderr
    assert unchanged == state


def test_bridge_failure_restores_before_returning(bridge):
    path, env, run = bridge
    original = json.loads(path.read_text())
    env["FAIL_OP"] = "--remove-egress-zone"
    result, state = run("--apply")
    assert result.returncode != 0
    assert state["policy"]["disable"] == "yes"
    assert set(state["policy"]["ingress-zones"]) == set(original["policy"]["ingress-zones"])
    assert set(state["policy"]["egress-zones"]) == set(original["policy"]["egress-zones"])
    assert state["policy"]["rich rules"] == []


def test_bridge_commit_keeps_policy_until_cleanup(bridge):
    _, _, run = bridge
    result, _ = run("--apply")
    assert result.returncode == 0, result.stderr
    result, active = run("--commit")
    assert result.returncode == 0, result.stderr
    result, unchanged = run("--timer-rollback")
    assert result.returncode == 0, result.stderr
    assert unchanged == active
    result, restored = run("--cleanup")
    assert result.returncode == 0, result.stderr
    assert restored["policy"]["disable"] == "yes"
    assert restored["policy"]["rich rules"] == []


@pytest.mark.parametrize("field,value", [
    ("target", "CONTINUE"), ("priority", "-1"), ("disable", "no"),
    ("ingress-zones", ["internal", "home", "trusted", "public"]),
    ("rich rules", [RULE4]),
])
def test_bridge_refuses_policy_drift_without_mutation(bridge, field, value):
    path, env, run = bridge
    state = json.loads(path.read_text())
    state["policy"][field] = value
    path.write_text(json.dumps(state))
    result, unchanged = run("--apply")
    assert result.returncode != 0
    assert unchanged == state
    assert not Path(env["TIMER_FILE"]).exists()


def test_bridge_never_removes_guards_if_disabling_fails(bridge):
    _, env, run = bridge
    result, active = run("--apply")
    assert result.returncode == 0, result.stderr
    env["FAIL_OP"] = "--add-disable"
    result, unchanged = run("--cleanup")
    assert result.returncode != 0
    assert unchanged == active
    assert Path(env["TIMER_FILE"]).exists()
