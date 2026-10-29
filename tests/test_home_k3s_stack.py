import subprocess

from conftest import REPO, write_stub


ASSETS = REPO / "home-k3s"


def run_stack(tmp_path, stub_env, fail_apply=""):
    bindir, env = stub_env
    write_stub(bindir, "id", "echo 0\n")
    write_stub(bindir, "hostname", "echo karnataka\n")
    write_stub(
        bindir,
        "curl",
        '''while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; : > "$1"; break; fi
  shift
done
''',
    )
    write_stub(bindir, "sha256sum", "cat >/dev/null\n")
    write_stub(
        bindir,
        "k3s",
        '''echo "$*" >> "$K3S_LOG"
if [ -n "$FAIL_APPLY" ] && [[ "$*" == *"apply --server-side"*"$FAIL_APPLY"* ]]; then
  echo 'simulated ownership conflict' >&2
  exit 1
fi
''',
    )
    log = tmp_path / "k3s.log"
    env.update(K3S_LOG=str(log), FAIL_APPLY=fail_apply)
    script = tmp_path / "apply-stack.sh"
    original = (ASSETS / "apply-stack.sh").read_text()
    script.write_text(original.replace("k=(/var/usrlocal/bin/k3s kubectl ", "k=(k3s kubectl ", 1))
    result = subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True)
    return result, log.read_text().splitlines() if log.exists() else []



def test_ownership_conflict_stops_subsequent_changes(tmp_path, stub_env):
    result, calls = run_stack(tmp_path, stub_env, "kubevirt-cr.yaml")
    assert result.returncode != 0
    assert "simulated ownership conflict" in result.stderr
    assert not any("cdi-operator.yaml" in call for call in calls)


