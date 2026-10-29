import json
import subprocess
from pathlib import Path

from conftest import REPO, write_stub


def test_seed_kube_defaults_to_retained_home_cache_not_merged_default(stub_env):
    bindir, env = stub_env
    home = Path(env["HOME"])
    (home / ".kube").mkdir()
    (home / ".talos").mkdir()
    (home / ".kube/config").write_text("active-k3s-private-config")
    (home / ".kube/config-home-talos").write_text("retained-home-private-config")
    (home / ".talos/config").write_text("retained-talos-private-config")
    write_stub(bindir, "bw", r'''
case "$1 $2" in
  "get template") echo '{}' ;;
  "list items") echo '[]' ;;
  "encode ") cat ;;
  "create item")
    payload="$(cat)"
    name="$(printf '%s' "$payload" | jq -r .name)"
    printf '%s' "$payload" > "$HOME/$name-seeded.json"
    ;;
  "sync ") exit 0 ;;
  *) exit 1 ;;
esac
''')
    env.pop("KUBECONFIG", None)
    env.pop("TALOSCONFIG", None)
    result = subprocess.run(["bash", str(REPO / "scripts/bw-seed-kube.sh")],
                            env={**env, "BW_SESSION": "test-session"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((home / "kubeconfig-seeded.json").read_text())["notes"] == "retained-home-private-config"
    assert json.loads((home / "talosconfig-seeded.json").read_text())["notes"] == "retained-talos-private-config"
    assert "private-config" not in result.stdout + result.stderr
    assert not (home / "kubeconfig-karnataka-k3s-seeded.json").exists()
