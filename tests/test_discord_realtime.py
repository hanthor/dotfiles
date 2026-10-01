"""Tests for the quiet #hive-ops feed in talos-k8s/hive/discord/realtime.py."""
import importlib.util

from conftest import REPO

SRC = REPO / "talos-k8s" / "hive" / "discord" / "realtime.py"
spec = importlib.util.spec_from_file_location("hive_discord_realtime", SRC)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

REPOSITORY = {"full_name": "tuna-os/tunaOS", "default_branch": "main"}


def wf(name, conclusion, branch="main", event="push"):
    return {"action": "completed", "repository": REPOSITORY,
            "workflow_run": {"name": name, "conclusion": conclusion, "head_branch": branch, "event": event,
                             "html_url": "https://github.com/tuna-os/tunaOS/actions/runs/1"}}


def feed(sequence, state, name="Build Marlin", **kw):
    out = []
    for i, conclusion in enumerate(sequence):
        out.append(rt.classify_github("workflow_run", wf(name, conclusion, **kw), state, now=1000.0 + i * 3600))
    return out


def test_ci_alerts_only_after_streak_and_recovers_once():
    state = {}
    results = feed(["success", "failure", "failure", "failure", "success", "success"], state)
    levels = [[n["level"] for n in r] for r in results]
    assert levels == [[], [], ["red"], [], ["green"], []]


def test_flaky_single_failures_do_not_post():
    state = {}
    results = feed(["success", "failure", "success", "failure", "success"], state)
    assert all(r == [] for r in results)


def test_pr_and_feature_branch_runs_ignored():
    state = {}
    assert all(r == [] for r in feed(["success", "failure", "failure"], state, event="pull_request"))
    assert all(r == [] for r in feed(["success", "failure", "failure"], state, branch="feature"))


def test_unimportant_workflows_are_left_to_digest():
    state = {}
    assert all(r == [] for r in feed(["success", "failure", "failure"], state, name="Prose"))


def test_cancelled_runs_are_ignored():
    state = {}
    results = feed(["success", "failure", "cancelled", "failure"], state)
    assert [n["level"] for r in results for n in r] == ["red"]


def test_only_real_releases_post():
    def rel(tag, name, draft=False):
        payload = {"action": "published", "repository": REPOSITORY,
                   "release": {"tag_name": tag, "name": name, "draft": draft, "html_url": f"https://x/{tag}"}}
        return rt.classify_github("release", payload, {})
    assert rel("kde-20260923", "TunaOS kde (20260923)") == []
    assert rel("plugins-af523499eb948b32cdea", "Corral plugins af523499eb94") == []
    assert [n["level"] for n in rel("v0.4.0", "v0.4.0")] == ["blue"]


def test_pr_opened_and_merged_are_not_posted():
    for action, merged in (("opened", False), ("closed", True)):
        payload = {"action": action, "repository": REPOSITORY,
                   "pull_request": {"number": 1, "title": "feat: x", "merged": merged, "html_url": "u", "labels": []}}
        assert rt.classify_github("pull_request", payload, {}) == []


def test_needs_human_label_posts_amber():
    payload = {"action": "labeled", "label": {"name": "needs-human"}, "repository": REPOSITORY,
               "pull_request": {"number": 5, "title": "fix: y", "html_url": "u", "labels": [{"name": "needs-human"}]}}
    notices = rt.classify_github("pull_request", payload, {})
    assert [n["level"] for n in notices] == ["amber"] and "tunaOS#5" in notices[0]["text"]


def test_status_diff_ignores_busy_churn_but_flags_login_and_budget():
    prev = {"agents": [{"name": "scanner", "busy": "idle", "needsLogin": False}], "budget": {"BUDGET_EXHAUSTED": False}}
    cur = {"agents": [{"name": "scanner", "busy": "working", "needsLogin": False}], "budget": {"BUDGET_EXHAUSTED": False},
           "governor": {"mode": "surge"}}
    assert rt.classify_status(prev, cur) == []
    cur2 = {"agents": [{"name": "scanner", "needsLogin": True}], "budget": {"BUDGET_EXHAUSTED": True},
            "systemAlerts": [{"id": "x", "severity": "critical", "message": "disk full"},
                             {"id": "y", "severity": "warning", "message": "meh"}]}
    levels = sorted(n["text"][:12] for n in rt.classify_status(prev, cur2))
    assert len(levels) == 3  # login, budget, critical alert (warning ignored)


def test_render_batch_orders_red_first_and_dedupes():
    notices = [rt.notice("amber", "a", "k1"), rt.notice("red", "r", "k2"), rt.notice("amber", "a", "k1")]
    payload = rt.render_batch(notices)
    embed = payload["embeds"][0]
    assert embed["color"] == rt.RED and embed["description"].splitlines()[0].startswith("🔴")
    assert len(embed["description"].splitlines()) == 2
    assert payload["allowed_mentions"] == {"parse": []}


def test_render_batch_respects_embed_limit():
    notices = [rt.notice("amber", "x" * 300, f"k{i}") for i in range(50)]
    desc = rt.render_batch(notices)["embeds"][0]["description"]
    assert len(desc) <= 4096 and desc.splitlines()[-1].startswith("+")


def test_amber_only_batches_use_slow_lane():
    assert rt.flush_delay([rt.notice("amber", "a")]) == rt.SLOW_BATCH_SECONDS
    assert rt.flush_delay([rt.notice("green", "g")]) == rt.SLOW_BATCH_SECONDS
    assert rt.flush_delay([rt.notice("amber", "a"), rt.notice("red", "r")]) == rt.BATCH_SECONDS


def test_event_record_drops_unused_workflow_states():
    assert rt.event_record("workflow_run", {"action": "in_progress", "repository": REPOSITORY, "workflow_run": {}}) is None
    rec = rt.event_record("workflow_run", wf("Build", "failure"))
    assert rec["branch"] == "main" and rec["default_branch"] == "main" and rec["trigger"] == "push"
