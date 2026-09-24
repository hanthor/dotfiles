"""hive-upgrade.sh driven against a stateful fake cluster + fake registry.

The fake kubectl keeps deployments/configmaps in a JSON "world" file and logs
every invocation, so tests can assert exactly which calls mutated what. The
fake curl serves GitHub releases, GHCR tokens/manifests and records Discord
posts. Nothing here talks to a network.
"""
import hashlib
import json
import subprocess

import pytest

from conftest import REPO, write_stub

SCRIPT = REPO / "talos-k8s/hive/upgrade/hive-upgrade.sh"

FAKE_KUBECTL = r'''
import json, os, sys, hashlib

WORLD = os.environ["FAKE_WORLD"]
w = json.load(open(WORLD))
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")

def save():
    json.dump(w, open(WORLD, "w"))

def die(msg, rc=1):
    sys.stderr.write(msg + "\n"); sys.exit(rc)

ns = "default"
rest = []
i = 0
while i < len(args):
    if args[i] == "-n":
        ns = args[i + 1]; i += 2; continue
    rest.append(args[i]); i += 1

def behavior(ns, image):
    out = {}
    for b in w.get("behaviors", []):
        if b.get("ns", ns) == ns and b["match"] in image:
            out.update(b)
    return out

def podname(key, dep):
    return key.split("/")[1] + "-" + hashlib.sha1(dep["image"].encode()).hexdigest()[:6]

def deploy_obj(key, dep):
    ns_, name = key.split("/")
    b = behavior(ns_, dep["image"])
    bad = b.get("crashloop") or b.get("rollout_fail")
    return {
        "metadata": {"name": name, "namespace": ns_, "generation": dep["generation"],
                     "annotations": dep.get("annotations", {})},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
                 "template": {"spec": {"containers": [{"name": dep["container"], "image": dep["image"]}]}}},
        "status": {"observedGeneration": dep["generation"], "readyReplicas": 0 if bad else 1},
    }

def find_pod(ns, pod):
    for key, dep in w["deploys"].items():
        if key.startswith(ns + "/") and podname(key, dep) == pod:
            return key, dep
    die('Error from server (NotFound): pods "%s" not found' % pod)

verb = rest[0]
if verb == "get":
    what = rest[1]
    if what == "--raw":
        path = rest[2]
        seg = path.split("/")
        key = seg[4] + "/" + seg[6].split(":")[0]
        dep = w["deploys"][key]
        b = behavior(seg[4], dep["image"])
        if b.get("forbid_exec"):
            die("Error from server (Forbidden): services \"x\" is forbidden")
        if b.get("hub_down"):
            die("Error from server (ServiceUnavailable): the server is currently unable to handle the request")
        print("<!DOCTYPE html><html><title>Hive hub</title></html>"); sys.exit(0)
    if what == "nodes":
        print(json.dumps({"items": [{"status": {"nodeInfo": {"architecture": a}}} for a in w["nodes"]]})); sys.exit(0)
    if what in ("deploy", "deployment"):
        if len(rest) > 2 and not rest[2].startswith("-"):
            key = ns + "/" + rest[2]
            if key not in w["deploys"]:
                die('Error from server (NotFound): deployments.apps "%s" not found' % rest[2])
            print(json.dumps(deploy_obj(key, w["deploys"][key]))); sys.exit(0)
        print(json.dumps({"items": [deploy_obj(k, d) for k, d in w["deploys"].items() if k.startswith(ns + "/")]}))
        sys.exit(0)
    if what == "pods":
        items = []
        for key, dep in w["deploys"].items():
            if not key.startswith(ns + "/"):
                continue
            b = behavior(ns, dep["image"])
            st = {"name": dep["container"], "restartCount": dep.get("restarts", 0),
                  "imageID": dep["image"].split(":")[0] + "@" + dep["image"].split("@")[-1],
                  "state": {"running": {}}}
            if b.get("crashloop"):
                st["restartCount"] = 4; st["state"] = {"waiting": {"reason": "CrashLoopBackOff"}}
            items.append({"metadata": {"name": podname(key, dep), "creationTimestamp": "2026-09-24T00:00:00Z"},
                          "status": {"containerStatuses": [st]}})
        print(json.dumps({"items": items})); sys.exit(0)
    if what in ("configmap", "cm"):
        key = ns + "/" + rest[2]
        if key not in w["configmaps"]:
            die('Error from server (NotFound): configmaps "%s" not found' % rest[2])
        print(json.dumps(w["configmaps"][key])); sys.exit(0)
    die("fake kubectl: unhandled get %r" % rest)

if verb == "patch":
    key = ns + "/" + rest[2]
    p = json.loads(rest[rest.index("-p") + 1])
    dep = w["deploys"][key]
    ann = dep.setdefault("annotations", {})
    for k, v in p.get("metadata", {}).get("annotations", {}).items():
        if v is None: ann.pop(k, None)
        else: ann[k] = v
    for c in p["spec"]["template"]["spec"]["containers"]:
        assert c["name"] == dep["container"], c
        dep["image"] = c["image"]
    dep["generation"] += 1
    save(); print("deployment.apps/%s patched" % rest[2]); sys.exit(0)

if verb == "rollout":
    key = ns + "/" + rest[2].split("/")[1]
    if behavior(ns, w["deploys"][key]["image"]).get("rollout_fail"):
        die("error: timed out waiting for the condition")
    print("deployment successfully rolled out"); sys.exit(0)

if verb == "exec":
    pod = rest[1]
    key, dep = find_pod(ns, pod)
    b = behavior(ns, dep["image"])
    if b.get("forbid_exec"):
        die('Error from server (Forbidden): pods "%s" is forbidden: cannot create resource "pods/exec"' % pod)
    cmd = rest[rest.index("--") + 1:]
    if cmd[0] == "cat":
        f = cmd[1]
        if f.endswith("dashboard-sessions.json"):
            print(json.dumps({"sid-owner": {"Role": "owner", "ExpiresAt": "2099-01-01T00:00:00.123-04:00"},
                              "sid-old": {"Role": "owner", "ExpiresAt": "2020-01-01T00:00:00Z"}})); sys.exit(0)
        if f.endswith("branding.json"):
            br = w.get("branding", {}).get(ns)
            if not br: die("cat: can't open '%s': No such file or directory" % f)
            print(json.dumps(br)); sys.exit(0)
    if cmd[0] == "curl":
        url = cmd[-1]
        cookie = any("hive_session=sid-owner" in a for a in cmd)
        if url.endswith("/api/health"):
            code = b.get("health", 200)
            sys.stdout.write('{"status":"ok"}\n%d' % code); sys.exit(0)
        br = w.get("branding", {}).get(ns, {})
        page = "<!doctype html><html><head><title>Hive</title></head><body>"
        if cookie and not b.get("unbranded") and br:
            page += br["product_name"] + " " + br["mark"]
        page += "</body></html>"
        sys.stdout.write(page + "\n" + ("200" if cookie else "401")); sys.exit(0)
    die("fake kubectl: unhandled exec %r" % cmd)

if verb in ("replace", "create"):
    obj = json.loads(sys.stdin.read())
    key = obj["metadata"]["namespace"] + "/" + obj["metadata"]["name"]
    if verb == "create" and key in w["configmaps"]:
        die("Error from server (AlreadyExists)")
    rv = int(w["configmaps"].get(key, {}).get("metadata", {}).get("resourceVersion", "0")) + 1
    obj["metadata"]["resourceVersion"] = str(rv)
    w["configmaps"][key] = obj
    save(); print(json.dumps(obj)); sys.exit(0)

die("fake kubectl: unhandled %r" % rest)
'''

FAKE_CURL = r'''
import json, os, sys

args = sys.argv[1:]
out = None; fmt = None; data = None; url = None
i = 0
while i < len(args):
    a = args[i]
    if a == "-o": out = args[i + 1]; i += 2; continue
    if a == "-w": fmt = args[i + 1]; i += 2; continue
    if a in ("-H", "-X", "--max-time"): i += 2; continue
    if a == "--data-binary": data = args[i + 1]; i += 2; continue
    if a.startswith("http"): url = a
    i += 1

code, body, redirect = 200, b"", ""
reg = os.environ["FAKE_REG"]
if url.startswith("https://ghcr.io/token"):
    body = b'{"token":"t"}'
elif url.startswith("https://ghcr.io/v2/"):
    repo, tag = url[len("https://ghcr.io/v2/"):].split("/manifests/")
    p = os.path.join(reg, repo.replace("/", "_") + "@" + tag + ".json")
    if os.path.exists(p): body = open(p, "rb").read()
    else: code, body = 404, b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}'
elif url.startswith("https://api.github.com/"):
    code = int(os.environ.get("FAKE_GH_CODE", "200"))
    body = open(os.path.join(reg, "releases.json"), "rb").read() if code == 200 else b'{"message":"rate limit"}'
elif url.startswith("https://github.com/"):
    code, redirect = 302, "https://github.com/hivecommons/hive/releases/tag/" + os.environ.get("FAKE_WEB_LATEST", "v5.35.10")
elif url.startswith("https://discord.com/"):
    with open(os.environ["FAKE_DISCORD"], "a") as f:
        f.write(open(data[1:]).read() + "\n")
    body = b'{"id":"1"}'
else:
    sys.stderr.write("fake curl: unexpected url " + url + "\n"); sys.exit(6)

if out and out != "/dev/null":
    open(out, "wb").write(body)
elif not out:
    sys.stdout.buffer.write(body)
if fmt:
    sys.stdout.write(fmt.replace("%{http_code}", str(code)).replace("%{redirect_url}", redirect))
'''

OLD_SPOKE = "ghcr.io/hivecommons/hive:v5.35.2@sha256:" + "a" * 64
OLD_HUB = "ghcr.io/hivecommons/hive-hub:v5.35.2@sha256:" + "b" * 64
ORDER = ["hive-hanthor", "hive-reef", "hive", "hive-hub"]

RELEASES = [
    {"tag_name": "v5.37.0", "draft": True, "prerelease": False},
    {"tag_name": "v5.36.0", "draft": False, "prerelease": True},
    {"tag_name": "v6.0.0", "draft": False, "prerelease": False},
    {"tag_name": "v4.99.0", "draft": False, "prerelease": False},
    {"tag_name": "v5.35.9", "draft": False, "prerelease": False},
    {"tag_name": "v5.35.10", "draft": False, "prerelease": False},
    {"tag_name": "v5.35.2", "draft": False, "prerelease": False},
]


def index(arches, salt):
    return json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
        "manifests": [{"digest": "sha256:" + salt * 64, "platform": {"os": "linux", "architecture": a}}
                      for a in arches],
    }).encode()


@pytest.fixture
def cluster(stub_env, tmp_path):
    bindir, env = stub_env
    (tmp_path / "kubectl.py").write_text(FAKE_KUBECTL)
    (tmp_path / "curl.py").write_text(FAKE_CURL)
    write_stub(bindir, "kubectl", f'exec python3 {tmp_path}/kubectl.py "$@"\n')
    write_stub(bindir, "curl", f'exec python3 {tmp_path}/curl.py "$@"\n')
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "releases.json").write_text(json.dumps(RELEASES))
    digests = {}

    def publish(tag, arches=("amd64", "arm64"), hub_arches=None):
        for repo, arch, salt in (("hive", arches, "1"), ("hive-hub", hub_arches or arches, "2")):
            body = index(arch, salt + tag.replace(".", ""))
            (reg / f"hivecommons_{repo}@{tag}.json").write_bytes(body)
            digests[(repo, tag)] = "sha256:" + hashlib.sha256(body).hexdigest()

    for t in ("v5.35.2", "v5.35.9", "v5.35.10", "v6.0.0", "v4.99.0", "v5.36.0", "v5.37.0"):
        publish(t)

    world = {
        "nodes": ["amd64", "amd64"],
        "deploys": {
            "hive-hanthor/hive": {"container": "hive", "image": OLD_SPOKE, "generation": 1, "annotations": {}},
            "hive-reef/hive": {"container": "hive", "image": OLD_SPOKE, "generation": 1, "annotations": {}},
            "hive/hive": {"container": "hive", "image": OLD_SPOKE, "generation": 1, "annotations": {}},
            "hive-hub/hive-hub": {"container": "hub", "image": OLD_HUB, "generation": 1, "annotations": {}},
            "hive-contributors/claude-contributor": {"container": "contributor",
                                                     "image": "ghcr.io/kubestellar/hive-contributor:latest@sha256:" + "c" * 64,
                                                     "generation": 1},
        },
        "branding": {"hive-reef": {"product_name": "REEF", "mark": "🪸"},
                     "hive": {"product_name": "SCHOOL", "mark": "🐟"}},
        "behaviors": [],
        "configmaps": {},
    }
    wfile = tmp_path / "world.json"
    log = tmp_path / "kubectl.log"
    discord = tmp_path / "discord.log"
    log.touch()
    discord.touch()
    env.update(FAKE_WORLD=str(wfile), FAKE_LOG=str(log), FAKE_REG=str(reg), FAKE_DISCORD=str(discord),
               SOAK_SECONDS="0", SOAK_INTERVAL="0", VERIFY_ATTEMPTS="2", VERIFY_INTERVAL="0",
               ROLLOUT_TIMEOUT="5", DISCORD_BOT_TOKEN="tok", DISCORD_CHANNEL_ID="42", TMPDIR=str(tmp_path))
    for k in ("DRY_RUN", "TRACK", "HIVE_UPGRADE_PIN", "FORCE", "GITHUB_TOKEN", "KUBERNETES_SERVICE_HOST"):
        env.pop(k, None)

    class C:
        def __init__(self):
            self.world = world
            self.digests = digests
            self.publish = publish
            self.env = env
            self.reg = reg

        def save(self):
            wfile.write_text(json.dumps(self.world))

        def load(self):
            return json.loads(wfile.read_text())

        def run(self, *argv, **extra):
            self.save()
            log.write_text("")
            e = dict(env, **extra)
            r = subprocess.run(["bash", str(SCRIPT), *argv], env=e, capture_output=True, text=True, timeout=120)
            self.out = r.stdout + r.stderr
            return r

        def calls(self):
            return [json.loads(line) for line in log.read_text().splitlines()]

        def mutations(self):
            return [c for c in self.calls()
                    if any(v in c for v in ("patch", "replace", "create", "apply", "set", "delete",
                                            "scale", "annotate", "label", "edit"))
                    or ("rollout" in c and ("restart" in c or "undo" in c))]

        def patched(self):
            return [c[c.index("-n") + 1] for c in self.calls() if "patch" in c]

        def image(self, key):
            return self.load()["deploys"][key]["image"]

        def state(self):
            return self.load()["configmaps"].get("hive/hive-upgrade-state", {}).get("data", {})

        def discord(self):
            return [json.loads(line) for line in discord.read_text().splitlines() if line.strip()]

        def at(self, tag, repo="hive"):
            return self.digests[(repo, tag)]

    return C()


def spoke(c, tag):
    return f"ghcr.io/hivecommons/hive:{tag}@{c.at(tag)}"


def test_picks_newest_v5_non_prerelease_release(cluster):
    r = cluster.run("status")
    assert r.returncode == 0, cluster.out
    # v5.37.0 is a draft, v5.36.0 a prerelease, v6/v4 are other lines; v5.35.10 > v5.35.9 (semver, not lexical)
    assert "target: v5.35.10" in cluster.out
    assert "source: GitHub releases API" in cluster.out
    assert cluster.mutations() == []


def test_falls_back_to_web_latest_when_api_rate_limited(cluster):
    r = cluster.run("status", FAKE_GH_CODE="403", FAKE_WEB_LATEST="v5.35.9")
    assert r.returncode == 0, cluster.out
    assert "target: v5.35.9" in cluster.out and "releases/latest" in cluster.out


def test_noop_when_current(cluster):
    for key, d in cluster.world["deploys"].items():
        if key.startswith("hive-contributors"):
            continue
        d["image"] = (f"ghcr.io/hivecommons/hive-hub:v5.35.10@{cluster.at('v5.35.10', 'hive-hub')}"
                      if key.startswith("hive-hub") else spoke(cluster, "v5.35.10"))
    r = cluster.run("run")
    assert r.returncode == 0, cluster.out
    assert "nothing to do" in cluster.out
    assert cluster.patched() == []
    assert cluster.discord() == []
    assert cluster.state()["last_result"].startswith("noop")


def test_success_order_canary_reef_hive_hub_with_soak(cluster):
    r = cluster.run("run")
    assert r.returncode == 0, cluster.out
    assert cluster.patched() == ORDER
    # soak runs after every target except the last, and before the next target starts
    out = cluster.out
    pos = [out.index(f"({ns}/") for ns in ("hive-hanthor", "hive-reef", "hive", "hive-hub")]
    soaks = [i for i in range(len(out)) if out.startswith("soaking 0s", i)]
    assert len(soaks) == 3
    assert pos[0] < soaks[0] < pos[1] < soaks[1] < pos[2] < soaks[2] < pos[3]
    for key in ("hive-hanthor/hive", "hive-reef/hive", "hive/hive"):
        d = cluster.load()["deploys"][key]
        assert d["image"] == spoke(cluster, "v5.35.10")
        assert d["annotations"]["hive.tunaos.org/previous-image"] == OLD_SPOKE
        assert d["annotations"]["hive.tunaos.org/version"] == "v5.35.10"
        assert d["annotations"]["hive.tunaos.org/upgraded-at"].endswith("Z")
    hub = cluster.load()["deploys"]["hive-hub/hive-hub"]
    assert hub["image"] == f"ghcr.io/hivecommons/hive-hub:v5.35.10@{cluster.at('v5.35.10', 'hive-hub')}"
    assert hub["annotations"]["hive.tunaos.org/previous-image"] == OLD_HUB
    # contributors are never touched
    assert "hive-contributors" not in cluster.patched()
    st = cluster.state()
    assert st["last_result"].startswith("success") and st["last_success"] == "v5.35.10"
    assert "running_since" not in st
    posts = cluster.discord()
    assert len(posts) == 1
    assert posts[0]["content"] == "Hive upgraded v5.35.2 → v5.35.10 (canary hive-hanthor ✓, reef ✓, hive ✓, hub ✓)"


def test_skips_blocklisted_version(cluster):
    cluster.world["configmaps"]["hive/hive-upgrade-state"] = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": "hive-upgrade-state", "namespace": "hive", "resourceVersion": "1"},
        "data": {"blocklist": "v5.35.10"}}
    r = cluster.run("run")
    assert r.returncode == 0, cluster.out
    assert "v5.35.10 is blocklisted" in cluster.out
    assert cluster.image("hive-hanthor/hive") == spoke(cluster, "v5.35.9")


def test_arch_missing_aborts_without_mutation(cluster):
    cluster.publish("v5.35.10", arches=("arm64",))
    r = cluster.run("run")
    assert r.returncode == 2, cluster.out
    assert "no linux/amd64 image" in cluster.out
    assert cluster.patched() == []
    assert cluster.image("hive-hanthor/hive") == OLD_SPOKE


def test_hub_arch_missing_aborts_before_any_spoke(cluster):
    cluster.publish("v5.35.10", hub_arches=("arm64",))
    r = cluster.run("run")
    assert r.returncode == 2, cluster.out
    assert cluster.patched() == []


def test_canary_failure_rolls_back_blocklists_and_stops(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-hanthor", "match": cluster.at("v5.35.10"), "health": 500}]
    r = cluster.run("run")
    assert r.returncode == 1, cluster.out
    assert cluster.patched() == ["hive-hanthor", "hive-hanthor"]   # upgrade, then rollback
    d = cluster.load()["deploys"]["hive-hanthor/hive"]
    assert d["image"] == OLD_SPOKE
    assert d["annotations"]["hive.tunaos.org/rolled-back-from"] == spoke(cluster, "v5.35.10")
    assert "hive.tunaos.org/version" not in d["annotations"]
    assert cluster.image("hive-reef/hive") == OLD_SPOKE and cluster.image("hive/hive") == OLD_SPOKE
    st = cluster.state()
    assert "v5.35.10" in st["blocklist"].split("\n")
    assert st["last_result"].startswith("rolled back")
    posts = cluster.discord()
    assert len(posts) == 1 and posts[0]["content"].startswith("🚨") and "FAILED on canary hive-hanthor" in posts[0]["content"]


def test_cooldown_after_rollback(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-hanthor", "match": cluster.at("v5.35.10"), "health": 500}]
    cluster.run("run")
    cluster.world = cluster.load()
    cluster.world["behaviors"] = []
    r = cluster.run("run")
    assert r.returncode == 0 and "cooldown" in cluster.out
    assert cluster.patched() == []


def test_crashloop_on_reef_rolls_back_reef_only(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-reef", "match": cluster.at("v5.35.10"), "crashloop": True}]
    r = cluster.run("run")
    assert r.returncode == 1, cluster.out
    assert cluster.patched() == ["hive-hanthor", "hive-reef", "hive-reef"]
    assert cluster.image("hive-hanthor/hive") == spoke(cluster, "v5.35.10")
    assert cluster.image("hive-reef/hive") == OLD_SPOKE
    assert cluster.image("hive/hive") == OLD_SPOKE


def test_branding_failure_on_branded_hive_rolls_back(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-reef", "match": cluster.at("v5.35.10"), "unbranded": True}]
    r = cluster.run("run")
    assert r.returncode == 1, cluster.out
    assert "branding FAIL" in cluster.out
    assert cluster.image("hive-reef/hive") == OLD_SPOKE
    assert cluster.image("hive/hive") == OLD_SPOKE
    assert cluster.image("hive-hanthor/hive") == spoke(cluster, "v5.35.10")
    assert "v5.35.10" in cluster.state()["blocklist"]


def test_cannot_measure_aborts_without_rollback(cluster):
    # After the canary moves, exec is refused (RBAC/API error). That is not
    # evidence the image is bad: abort and alert, never roll back or blocklist.
    cluster.world["behaviors"] = [{"ns": "hive-hanthor", "match": cluster.at("v5.35.10"), "forbid_exec": True}]
    r = cluster.run("run")
    assert r.returncode == 2, cluster.out
    assert cluster.patched() == ["hive-hanthor"]
    assert cluster.image("hive-hanthor/hive") == spoke(cluster, "v5.35.10")
    d = cluster.load()["deploys"]["hive-hanthor/hive"]
    assert d["annotations"]["hive.tunaos.org/previous-image"] == OLD_SPOKE   # rollback path kept
    assert "blocklist" not in cluster.state()
    assert cluster.image("hive-reef/hive") == OLD_SPOKE
    posts = cluster.discord()
    assert len(posts) == 1 and "ABORTED" in posts[0]["content"] and "NOT rolled back" in posts[0]["content"]


def test_preflight_unmeasurable_touches_nothing(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-hanthor", "match": "v5.35.2", "forbid_exec": True}]
    r = cluster.run("run")
    assert r.returncode == 2, cluster.out
    assert cluster.patched() == []
    assert cluster.discord() == []


def test_hub_down_after_upgrade_rolls_back_hub(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-hub", "match": cluster.at("v5.35.10", "hive-hub"), "hub_down": True}]
    r = cluster.run("run")
    assert r.returncode == 1, cluster.out
    assert cluster.image("hive-hub/hive-hub") == OLD_HUB
    assert cluster.image("hive/hive") == spoke(cluster, "v5.35.10")


def test_dry_run_makes_no_mutating_calls(cluster):
    r = cluster.run("run", DRY_RUN="1")
    assert r.returncode == 0, cluster.out
    assert cluster.mutations() == []
    for c in cluster.calls():
        if "exec" in c:
            cmd = c[c.index("--") + 1:]
            assert cmd[0] in ("cat", "curl") and "-X" not in cmd and "-d" not in cmd, c
    assert cluster.image("hive-hanthor/hive") == OLD_SPOKE
    assert cluster.discord() == []
    assert "would run: kubectl -n hive-hanthor patch" in cluster.out


def test_dry_run_failure_paths_also_do_not_mutate(cluster):
    cluster.world["behaviors"] = [{"ns": "hive-hanthor", "match": cluster.at("v5.35.10"), "health": 500}]
    r = cluster.run("run", DRY_RUN="1")
    assert cluster.mutations() == []


def test_channel_track_uses_digest_label(cluster):
    cluster.publish("stable")
    r = cluster.run("run", TRACK="stable")
    assert r.returncode == 0, cluster.out
    label = "stable@" + cluster.at("stable")[7:19]
    assert cluster.image("hive/hive") == f"ghcr.io/hivecommons/hive:stable@{cluster.at('stable')}"
    assert cluster.load()["deploys"]["hive/hive"]["annotations"]["hive.tunaos.org/version"] == label


def test_pin_and_block_subcommands(cluster):
    assert cluster.run("block", "v5.35.10").returncode == 0
    assert cluster.state()["blocklist"] == "v5.35.10"
    assert cluster.run("unblock", "v5.35.10").returncode == 0
    assert "blocklist" not in cluster.state()
    cluster.world = cluster.load()
    assert cluster.run("pin", "v5.35.9").returncode == 0
    cluster.world = cluster.load()
    r = cluster.run("run")
    assert r.returncode == 0, cluster.out
    assert cluster.image("hive-reef/hive") == spoke(cluster, "v5.35.9")


def test_does_not_downgrade_when_ahead(cluster):
    cluster.world["deploys"]["hive-reef/hive"]["image"] = spoke(cluster, "v6.0.0")
    cluster.world["deploys"]["hive-reef/hive"]["annotations"] = {"hive.tunaos.org/version": "v5.99.0"}
    r = cluster.run("run")
    assert r.returncode == 0, cluster.out
    assert "hive-reef" not in cluster.patched()


def test_discord_payload_is_valid_json_with_awkward_text(cluster):
    # A newline or quote in the reason must not produce invalid JSON.
    cluster.world["branding"]["hive-reef"] = {"product_name": 'RE"EF\nX', "mark": "🪸"}
    cluster.world["behaviors"] = [{"ns": "hive-reef", "match": cluster.at("v5.35.10"), "unbranded": True}]
    cluster.run("run")
    raw = (cluster.reg.parent / "discord.log").read_text().strip().splitlines()
    assert raw, cluster.out
    for line in raw:
        p = json.loads(line)
        assert set(p) == {"content", "allowed_mentions", "flags"}
        assert p["allowed_mentions"] == {"parse": []}


def test_target_left_on_blocklisted_version_is_moved_off_it(cluster):
    # Reef fails on v5.35.10 → reef rolled back, canary stays on v5.35.10 and
    # v5.35.10 is blocklisted. Next run targets v5.35.9: the canary must NOT be
    # treated as "ahead" and left on the blocklisted build.
    cluster.world["behaviors"] = [{"ns": "hive-reef", "match": cluster.at("v5.35.10"), "unbranded": True}]
    assert cluster.run("run").returncode == 1
    assert cluster.image("hive-hanthor/hive") == spoke(cluster, "v5.35.10")
    cluster.world = cluster.load()
    r = cluster.run("run", FORCE="1")   # skip the post-rollback cooldown
    assert r.returncode == 0, cluster.out
    assert cluster.patched() == ORDER
    assert cluster.image("hive-hanthor/hive") == spoke(cluster, "v5.35.9")
    assert cluster.image("hive-reef/hive") == spoke(cluster, "v5.35.9")
