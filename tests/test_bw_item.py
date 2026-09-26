import subprocess

import pytest

from conftest import REPO, write_stub

# Fake bw: `list items --search <name>` returns $STUB_ITEMS verbatim (a JSON
# array); `encode` echoes stdin back out; `create item` / `edit item <id>`
# just record what they were called with. Every call is logged to $STUB_LOG.
BW_STUB = r'''
echo "$*" >> "$STUB_LOG"
case "$1 $2" in
  "list items")
    printf '%s' "${STUB_ITEMS:-[]}"
    ;;
  "encode ")
    cat
    ;;
  "create item")
    cat > /dev/null
    ;;
  "edit item")
    cat > /dev/null
    ;;
  *)
    exit 99
    ;;
esac
'''

# Sources bw-item.sh and calls whichever function + args were passed on argv.
DRIVER = '''
set -euo pipefail
source "$1"
shift
"$@"
'''


@pytest.fixture
def bw(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "bw", BW_STUB)
    env.update(STUB_LOG=str(tmp_path / "bw.log"))
    (tmp_path / "bw.log").touch()
    return env, tmp_path / "bw.log"


def call(env, *args):
    return subprocess.run(
        ["bash", "-c", DRIVER, "bw-item-test", str(REPO / "scripts" / "bw-item.sh"), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


def test_find_item_id_no_match(bw):
    env, _ = bw
    env["STUB_ITEMS"] = '[{"id": "abc", "name": "other", "type": 2}]'
    r = call(env, "bw_find_item_id", "kubeconfig")
    assert (r.returncode, r.stdout) == (0, "")


def test_find_item_id_matches_by_name(bw):
    env, _ = bw
    env["STUB_ITEMS"] = '[{"id": "abc", "name": "kubeconfig", "type": 2}]'
    r = call(env, "bw_find_item_id", "kubeconfig")
    assert (r.returncode, r.stdout) == (0, "abc\n")


def test_find_item_id_filters_by_type(bw):
    env, _ = bw
    # Same name, wrong type (e.g. a secure note vs. an SSH key) must not match.
    env["STUB_ITEMS"] = '[{"id": "abc", "name": "karnataka", "type": 2}]'
    r = call(env, "bw_find_item_id", "karnataka", "5")
    assert (r.returncode, r.stdout) == (0, "")


def test_upsert_creates_when_absent(bw):
    env, log = bw
    env["STUB_ITEMS"] = "[]"
    r = call(env, "bw_upsert_item", "kubeconfig", '{"name":"kubeconfig"}')
    assert r.returncode == 0, r.stderr
    assert "create item" in log.read_text()
    assert "edit item" not in log.read_text()


def test_upsert_edits_when_present(bw):
    env, log = bw
    env["STUB_ITEMS"] = '[{"id": "abc", "name": "kubeconfig", "type": 2}]'
    r = call(env, "bw_upsert_item", "kubeconfig", '{"name":"kubeconfig"}')
    assert r.returncode == 0, r.stderr
    assert "edit item abc" in log.read_text()
    assert "create item" not in log.read_text()


def test_upsert_respects_type_filter(bw):
    env, log = bw
    # Existing item has the same name but a different type, so this must
    # create a new item rather than overwrite the unrelated one.
    env["STUB_ITEMS"] = '[{"id": "abc", "name": "karnataka", "type": 2}]'
    r = call(env, "bw_upsert_item", "karnataka", '{"name":"karnataka"}', "5")
    assert r.returncode == 0, r.stderr
    assert "create item" in log.read_text()
    assert "edit item" not in log.read_text()
