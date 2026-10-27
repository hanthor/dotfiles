import json
import subprocess

import pytest

from conftest import REPO, write_stub


SCRIPT = REPO / "home-k3s" / "firewall.sh"


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
if "--state" in args:
    print("running")
elif "--get-default-zone" in args:
    print(s["default"])
elif "--list-interfaces" in args:
    print(" ".join(zone["interfaces"]))
elif "--list-sources" in args:
    print(" ".join(zone["sources"]))
else:
    op = next(a for a in args if a.startswith(("--query-", "--add-", "--change-")))
    command, _, value = op.partition("=")
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
    s["changes"].append([scope, op])
    if key == "interfaces":
        zone[key].append(value)
    else:
        zone[key] = value if key == "rule" else True
    with open(p, "w") as f:
        json.dump(s, f)
PY
''',
    )
    path = tmp_path / "firewall.json"
    state = {
        "default": "public",
        "runtime": {"interfaces": [], "sources": [], "forward": False, "rule": ""},
        "permanent": {"interfaces": [], "sources": [], "forward": False, "rule": ""},
        "changes": [],
    }
    path.write_text(json.dumps(state))
    env["FIREWALL_STATE"] = str(path)

    def run(mode):
        result = subprocess.run(["bash", str(SCRIPT), mode], env=env, text=True, capture_output=True)
        return result, json.loads(path.read_text())

    return path, env, run


def test_apply_is_scoped_and_idempotent(firewall):
    _, _, run = firewall
    result, state = run("--apply")
    assert result.returncode == 0, result.stderr
    for scope in ("runtime", "permanent"):
        zone = state[scope]
        assert zone["interfaces"] == ["cni0"]
        assert zone["sources"] == []
        assert zone["forward"] is True
    result, second = run("--apply")
    assert result.returncode == 0, result.stderr
    assert second == state
    result, checked = run("--check")
    assert result.returncode == 0, result.stderr
    assert checked == state


def test_check_reports_missing_without_changes(firewall):
    _, _, run = firewall
    result, state = run("--check")
    assert result.returncode != 0
    assert "Missing" in result.stderr
    assert not state["changes"]



def test_check_accepts_host_rule_from_real_firewalld(firewall):
    path, _, run = firewall
    state = json.loads(path.read_text())
    for scope in ("runtime", "permanent"):
        state[scope].update(
            interfaces=["cni0"], forward=True,
            rule='rule family="ipv4" source address="10.42.0.0/16" '
                 'destination address="100.66.158.127/32" port port="10250" protocol="tcp" accept',
        )
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
