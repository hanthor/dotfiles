import json
import stat
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from unit_helpers import UNLOCKED_BW, calls, run_unit


def kubeconfig(name, server="https://example.invalid:6443"):
    return {
        "apiVersion": "v1", "kind": "Config",
        "clusters": [{"name": name, "cluster": {"server": server}}],
        "users": [{"name": name, "user": {"token": "test-private-token"}}],
        "contexts": [{"name": name, "context": {"cluster": name, "user": name}}],
        "current-context": name,
    }


# Models kubectl's local config operations, including first-file merge precedence.
# Only synthetic JSON kubeconfigs are used; there is no cluster/vault access.
KUBECTL = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(Path(os.environ["HOME"]) / "calls", "a") as log:
    log.write("kubectl " + " ".join(args) + "\n")
paths = os.environ["KUBECONFIG"].split(":")
try:
    configs = [json.loads(Path(path).read_text()) for path in paths]
    config = configs[0]
    if args[:2] == ["config", "get-clusters"]:
        print("NAME")
        for item in config["clusters"]:
            print(item["name"])
        if os.environ.get("FAIL_LIST") == "1":
            sys.exit(1)
    elif args[:2] == ["config", "set-cluster"]:
        for item in config["clusters"]:
            if item["name"] == args[2]:
                item["cluster"]["tls-server-name"] = args[3].split("=", 1)[1]
        Path(paths[0]).write_text(json.dumps(config))
    elif args[:2] == ["config", "get-contexts"]:
        for item in config["contexts"]:
            if item["name"] == args[2]:
                print(item["name"])
    elif args[:2] == ["config", "use-context"]:
        if os.environ.get("FAIL_SELECT") == "1" or not any(item["name"] == args[2] for item in config["contexts"]):
            print("test-private-invalid-config", file=sys.stderr)
            sys.exit(1)
        config["current-context"] = args[2]
        Path(paths[0]).write_text(json.dumps(config))
    elif args[:2] == ["config", "view"]:
        if os.environ.get("FAIL_MERGE") == "1":
            print("test-private-partial-config")
            print("test-private-merge-error", file=sys.stderr)
            sys.exit(1)
        merged = {"apiVersion": "v1", "kind": "Config", "current-context": config["current-context"]}
        for field in ("clusters", "users", "contexts"):
            items = {}
            for source in configs:
                for item in source[field]:
                    items.setdefault(item["name"], item)
            merged[field] = list(items.values())
        print(json.dumps(merged))
    else:
        sys.exit(1)
except (ValueError, KeyError, OSError):
    print("test-private-invalid-config", file=sys.stderr)
    sys.exit(1)
'''


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    home = Path(env["HOME"])
    (home / "home-note").write_text(json.dumps(kubeconfig("home")))
    (home / "k3s-note").write_text(json.dumps(kubeconfig("karnataka-k3s", "https://100.66.158.127:6443")))
    write_stub(bindir, "bw", UNLOCKED_BW % r'''
if [ "$1 $2" = "get notes" ]; then
  case "$3" in
    kubeconfig) cat "$HOME/home-note"; exit 0 ;;
    kubeconfig-karnataka-k3s)
      [ "${NO_K3S_NOTE:-0}" = 1 ] && { echo test-private-partial-config; exit 1; }
      cat "$HOME/k3s-note"; exit 0 ;;
    talosconfig) echo "home-talos"; exit 0 ;;
    kubeconfig-aws-migration) echo "aws-kube"; exit 0 ;;
    talosconfig-aws-migration) exit 1 ;;
  esac
fi
''')
    kubectl = home / "kubectl-stub.py"
    kubectl.write_text(KUBECTL)
    write_stub(bindir, "kubectl", f'exec python3 "{kubectl}" "$@"\n')
    env.update(BW_SESSION="x", DOTFILES_IS_DESKTOP="1")
    return env


def config(env):
    return json.loads(Path(env["HOME"], ".kube/config").read_text())


def existing_config(env, name="custom"):
    path = Path(env["HOME"], ".kube/config")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(kubeconfig(name)))
    return path


def test_configs_are_private_and_k3s_is_default_with_home_recovery(env):
    result = run_unit("kube", env)
    assert result.returncode == 0, result.stdout + result.stderr
    home = Path(env["HOME"])
    assert config(env)["current-context"] == "karnataka-k3s"
    assert {item["name"] for item in config(env)["contexts"]} == {"home", "karnataka-k3s"}
    clusters = {item["name"]: item["cluster"] for item in config(env)["clusters"]}
    assert clusters["home"]["tls-server-name"] == "192.168.0.5"
    assert "tls-server-name" not in clusters["karnataka-k3s"]
    assert (home / ".talos/config").read_text().strip() == "home-talos"
    assert (home / ".kube/config-aws-migration").read_text().strip() == "aws-kube"
    for name in (".kube/config", ".kube/config-home-talos", ".kube/config-karnataka-k3s", ".talos/config", ".kube/config-aws-migration"):
        assert stat.S_IMODE((home / name).stat().st_mode) == 0o600
    assert "test-private-token" not in result.stdout + result.stderr
    assert not list((home / ".kube").glob(".fleet.*"))


def test_existing_contexts_and_original_bytes_survive_repeated_applies(env):
    path = existing_config(env)
    original = path.read_bytes()
    first = run_unit("kube", env)
    assert first.returncode == 0, first.stdout + first.stderr
    merged = path.read_bytes()
    second = run_unit("kube", env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert path.read_bytes() == merged
    assert Path(env["HOME"], ".kube/config-pre-karnataka-k3s").read_bytes() == original
    assert {item["name"] for item in config(env)["contexts"]} == {"custom", "home", "karnataka-k3s"}
    assert config(env)["current-context"] == "karnataka-k3s"


def test_later_apply_restores_k3s_default_without_losing_custom_contexts(env):
    path = existing_config(env)
    assert run_unit("kube", env).returncode == 0
    changed = config(env)
    changed["current-context"] = "custom"
    path.write_text(json.dumps(changed))
    result = run_unit("kube", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert config(env)["current-context"] == "karnataka-k3s"
    assert "custom" in {item["name"] for item in config(env)["contexts"]}


def test_fresh_install_does_not_later_backup_merged_config_as_legacy(env):
    assert run_unit("kube", env).returncode == 0
    assert run_unit("kube", env).returncode == 0
    assert not Path(env["HOME"], ".kube/config-pre-karnataka-k3s").exists()


def test_explicit_cached_only_rollout_merges_without_bw_and_preserves_original(env):
    path = existing_config(env)
    original = path.read_bytes()
    cache = path.parent / "config-karnataka-k3s"
    cache.write_text(Path(env["HOME"], "k3s-note").read_text())
    cache.chmod(0o600)
    bindir = Path(env["PATH"].split(":")[0])
    write_stub(bindir, "bw", 'echo unexpected-bw-call >> "$HOME/calls"\nexit 99\n')
    result = run_unit("kube", env, KUBE_CACHED_ONLY="1", UNITS_NO_SECRETS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert config(env)["current-context"] == "karnataka-k3s"
    assert {item["name"] for item in config(env)["contexts"]} == {"custom", "karnataka-k3s"}
    assert (path.parent / "config-pre-karnataka-k3s").read_bytes() == original
    assert "bw" not in calls(env)
    assert not Path(env["HOME"], ".talos").exists()


def test_cached_only_rollout_without_cache_preserves_default_and_never_reads_bw(env):
    path = existing_config(env)
    original = path.read_bytes()
    result = run_unit("kube", env, KUBE_CACHED_ONLY="1", UNITS_NO_SECRETS="1")
    assert result.returncode != 0 and "no cached config exists" in result.stdout
    assert path.read_bytes() == original
    assert "bw " not in calls(env)


def test_recovery_caches_are_not_overwritten_or_read_from_vault(env):
    home = Path(env["HOME"])
    for name, content in ((".talos/config", "retained-talos"), (".kube/config-aws-migration", "retained-aws"), (".talos/config-aws-migration", "retained-aws-talos")):
        path = home / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
    result = run_unit("kube", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".talos/config").read_text() == "retained-talos"
    assert (home / ".kube/config-aws-migration").read_text() == "retained-aws"
    assert (home / ".talos/config-aws-migration").read_text() == "retained-aws-talos"
    assert "bw get notes talosconfig" not in calls(env)
    assert "bw get notes kubeconfig-aws-migration" not in calls(env)


def test_a_missing_recovery_note_warns_and_leaves_no_file(env):
    result = run_unit("kube", env)
    assert result.returncode == 0
    assert "talosconfig-aws-migration missing in BW" in result.stdout
    assert not Path(env["HOME"], ".talos/config-aws-migration").exists()


@pytest.mark.parametrize("extra", [{"STUB_UNLOCK_RC": "1"}, {"UNITS_NO_SECRETS": "1"}])
def test_locked_or_disabled_vault_leaves_existing_configs(env, extra):
    path = existing_config(env)
    original = path.read_bytes()
    result = run_unit("kube", env, **extra)
    assert result.returncode == 0 and "SKIPPED:" in result.stdout
    assert path.read_bytes() == original


@pytest.mark.parametrize("machine", ["punjab", "karnataka", "spindle", "mumbai", "termux", "unknown-active-server"])
def test_all_active_computers_are_eligible_without_desktop_lookup(env, machine):
    result = run_unit("kube", env, DOTFILES_IS_DESKTOP="0", DOTFILES_MACHINE=machine)
    assert result.returncode == 0, result.stdout + result.stderr
    assert config(env)["current-context"] == "karnataka-k3s"


@pytest.mark.parametrize("machine", ["matrix", "telengana"])
def test_retired_hosts_are_never_touched(env, machine):
    result = run_unit("kube", env, DOTFILES_MACHINE=machine)
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert calls(env) == "" and not Path(env["HOME"], ".kube").exists()


@pytest.mark.parametrize("profile", ["skip_kube: true\n", "machine_profile: vm-test\n"])
def test_explicit_opt_out_and_test_profile_skip_before_reading_secrets(env, tmp_path, profile):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars/phone.yml").write_text(profile)
    (repo / "units").symlink_to(REPO / "units")
    result = run_unit("kube", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="phone")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert calls(env) == "" and not Path(env["HOME"], ".kube").exists()


def test_missing_k3s_note_preserves_existing_default_and_hides_partial_stdout(env):
    path = existing_config(env)
    original = path.read_bytes()
    result = run_unit("kube", env, NO_K3S_NOTE="1")
    assert result.returncode != 0 and "no cached config exists" in result.stdout
    assert path.read_bytes() == original
    assert "test-private-partial-config" not in result.stdout + result.stderr


def test_failed_refresh_uses_last_successful_k3s_cache(env):
    assert run_unit("kube", env).returncode == 0
    result = run_unit("kube", env, NO_K3S_NOTE="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert config(env)["current-context"] == "karnataka-k3s"
    assert "test-private-partial-config" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["FAIL_MERGE", "FAIL_SELECT"])
def test_failed_merge_or_context_selection_is_atomic_and_private(env, failure):
    path = existing_config(env)
    original = path.read_bytes()
    result = run_unit("kube", env, **{failure: "1"})
    assert result.returncode != 0
    assert path.read_bytes() == original
    assert "test-private" not in result.stdout + result.stderr
    assert not Path(env["HOME"], ".kube/config-karnataka-k3s").exists()


def test_invalid_k3s_note_preserves_existing_default(env):
    path = existing_config(env)
    original = path.read_bytes()
    Path(env["HOME"], "k3s-note").write_text(json.dumps(kubeconfig("wrong-context")))
    result = run_unit("kube", env)
    assert result.returncode != 0 and "lacks a usable" in result.stdout
    assert path.read_bytes() == original
    assert "test-private" not in result.stdout + result.stderr


def test_failed_cluster_listing_does_not_install_partial_recovery_cache(env):
    result = run_unit("kube", env, FAIL_LIST="1")
    assert result.returncode != 0 and "cannot list home kubeconfig clusters" in result.stdout
    assert not Path(env["HOME"], ".kube/config-home-talos").exists()
    assert config(env)["current-context"] == "karnataka-k3s"
    assert "set-cluster" not in calls(env)


def test_symlinked_default_is_not_replaced(env):
    home = Path(env["HOME"])
    target = home / "untouched"
    target.write_text("retained-config")
    (home / ".kube").mkdir()
    (home / ".kube/config").symlink_to(target)
    result = run_unit("kube", env)
    assert result.returncode != 0 and "refusing non-regular" in result.stdout
    assert target.read_text() == "retained-config"
    assert (home / ".kube/config").is_symlink()


def test_missing_kubectl_reports_package_prerequisite_without_changing_files(env, tmp_path):
    bash_env = tmp_path / "bash-env"
    bash_env.write_text('''
command() {
  if [ "$1" = -v ] && [ "$2" = kubectl ]; then return 1; fi
  builtin command "$@"
}
''')
    result = run_unit("kube", env, BASH_ENV=str(bash_env))
    assert result.returncode != 0 and "apply packages before kube" in result.stdout
    assert not Path(env["HOME"], ".kube").exists()
