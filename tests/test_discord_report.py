"""Formatting / prioritisation tests for talos-k8s/hive/discord/report.py."""
import importlib.util
import json

import pytest

from conftest import REPO

SRC = REPO / "talos-k8s" / "hive" / "discord" / "report.py"
spec = importlib.util.spec_from_file_location("hive_discord_report", SRC)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

DAY = 86400.0
END = 1_790_000_000.0
START = END - DAY


def pr(title, n=1, repo="tuna-os/compass", labels=()):
    return {"repo": repo, "number": n, "title": title, "html_url": f"https://github.com/{repo}/pull/{n}",
            "merged_at": "2026-09-23T10:00:00Z", "labels": [{"name": x} for x in labels]}


def run(name, conclusion, ts, repo="tuna-os/tunaOS"):
    return {"repo": repo, "name": name, "conclusion": conclusion, "html_url": f"https://github.com/{repo}/actions/runs/{int(ts)}",
            "ts": ts, "branch": None, "default_branch": None, "trigger": None}


def repo_data(repo="tuna-os/compass", merged=(), runs=(), releases=(), needs_human=(), opened=()):
    data = report.empty_repo(repo)
    data["merged"] = list(merged)
    data["pulls"] = list(merged)
    data["features"] = [i for i in merged if report.classify_pr(i) == "feature"]
    data["runs"] = sorted(runs, key=lambda r: r["ts"])
    data["releases"] = list(releases)
    data["needs_human"] = list(needs_human)
    data["opened_issues"] = list(opened)
    data["issues"] = list(opened)
    return data


def description(payload):
    return payload["embeds"][0]["description"]


# ── classification ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("chore(deps): update dependency ubuntu to v26", "deps"),
    ("Update Rust crate gtk to v0.11.5", "deps"),
    ("Bump the rust-dependencies group across 1 directory with 2 updates", "deps"),
    ("chore(deps): update debian:sid docker digest to fac5e25", "deps"),
    ("[strategist] planning: refresh ROADMAP", "agent"),
    ("[sec-check] fix: remove duplicate org preset entry in renovate.json", "agent"),
    ("feat: port query orchestration over an IndexReader trait", "feature"),
    ("fix(sort): coerce BigInt gint64 to Number", "fix"),
    ("docs: refresh matrix status", "chore"),
    ("Give Worker a health check and a kill switch", "other"),
])
def test_classify_pr(title, expected):
    assert report.classify_pr({"title": title, "labels": []}) == expected


@pytest.mark.parametrize("release,nightly", [
    ({"tag_name": "kde-20260923", "name": "TunaOS kde (20260923)", "html_url": "x"}, True),
    ({"tag_name": "plugins-af523499eb948b32cdea58e96ff5e2d7283c9bda", "name": "Corral plugins af523499eb94", "html_url": "x"}, True),
    ({"tag_name": "v2026.09.19-e36d8e37", "name": "bootc-installer v2026.09.19-e36d8e37", "html_url": "x"}, True),
    ({"tag_name": "v0.3.0", "name": "v0.3.0", "html_url": "https://github.com/tuna-os/fisherman/releases/tag/untagged-f02b"}, True),
    ({"tag_name": "v0.3.0", "name": "v0.3.0", "html_url": "https://github.com/tuna-os/fisherman/releases/tag/v0.3.0"}, False),
])
def test_nightly_release_detection(release, nightly):
    assert report.is_nightly_release(release) is nightly


def test_clean_title_is_plain_words_and_link_safe():
    assert report.clean_title("[architect] refactor: unify GRUB config source") == "Unify GRUB config source"
    assert report.clean_title("feat(ui)!: open a [resident] session (#12)") == "Open a (resident) session"
    long = report.clean_title("fix: " + "word " * 60, limit=40)
    assert len(long) <= 40 and long.endswith("…")


# ── CI health ───────────────────────────────────────────────────────────────

def test_ci_health_newly_still_fixed_and_ignores_cancelled():
    runs = [
        run("Build Hummingbird", "failure", START - 5 * DAY),
        run("Build Hummingbird", "cancelled", START + 10),
        run("Build Hummingbird", "failure", START + 100),        # still red, since before window
        run("Build Marlin", "success", START - DAY),
        run("Build Marlin", "failure", START + 200),
        run("Build Marlin", "failure", START + 300),              # newly red, streak 2
        run("Lint", "failure", START + 50),
        run("Lint", "success", START + 400),                      # fixed
    ]
    ci = report.ci_health(sorted(runs, key=lambda r: r["ts"]), START, END)
    assert [(e["name"], e["streak"]) for e in ci["newly"]] == [("Build Marlin", 2)]
    assert [e["name"] for e in ci["still"]] == ["Build Hummingbird"]
    assert ci["still"][0]["streak"] == 2  # cancelled run skipped, not a break
    assert [e["name"] for e in ci["fixed"]] == ["Lint"]


def test_ci_health_skips_pr_and_non_default_branch_runs():
    feature = dict(run("Build X", "failure", START + 10), branch="feature", default_branch="main")
    pr_run = dict(run("Build Y", "failure", START + 20), trigger="pull_request")
    ci = report.ci_health([feature, pr_run], START, END)
    assert not ci["newly"] and not ci["still"]


# ── digest structure ────────────────────────────────────────────────────────

def test_nothing_needs_you_is_explicit_and_green():
    pairs = [("tuna-os/compass", repo_data(merged=[pr("feat: a thing")]))]
    payload = report.build_digest("Daily", pairs, start=START, end=END)
    assert description(payload).startswith("✅ **Nothing needs you today.**")
    assert payload["embeds"][0]["color"] == report.GREEN
    assert payload["content"].startswith("✅ Nothing needs you")


def test_attention_comes_first_and_red_before_amber():
    runs = [run("Build Marlin", "success", START - 10), run("Build Marlin", "failure", START + 10)]
    status = {"hold": {"total": 5, "items": [{"review_class": "fix"}] * 5},
              "agents": [{"name": "scanner", "needsLogin": True}], "systemAlerts": []}
    pairs = [("tuna-os/tunaOS", repo_data("tuna-os/tunaOS", merged=[pr("feat: new thing", repo="tuna-os/tunaOS")], runs=runs))]
    payload = report.build_digest("Daily", pairs, start=START, end=END, hive_status=status)
    desc = description(payload)
    assert desc.startswith("**Needs you**")
    assert desc.index("Needs you") < desc.index("Highlights") < desc.index("📊")
    needs = desc.split("\n\n")[0].splitlines()[1:]
    assert needs[0].startswith("🔴") and needs[1].startswith("🔴")
    assert any(line.startswith("🟠") and "on hold" in line for line in needs)
    assert payload["embeds"][0]["color"] == report.RED


def test_empty_sections_are_suppressed():
    pairs = [("tuna-os/docs", repo_data("tuna-os/docs", merged=[pr("chore(deps): update x to v2", repo="tuna-os/docs")]))]
    desc = description(report.build_digest("Daily", pairs, start=START, end=END))
    assert "Highlights" not in desc          # only a dependency bump: no highlights section
    assert "+1 dependency bump" in desc      # ...collapsed instead
    stats = [line for line in desc.splitlines() if line.startswith("📊")][0]
    assert "release" not in stats and "issues" not in stats  # zero-count stats omitted


def test_long_tail_is_collapsed_not_listed():
    merged = [pr(f"chore(deps): update crate{i} to v{i}", n=i) for i in range(40)]
    merged += [pr(f"[strategist] planning: roadmap {i}", n=100 + i) for i in range(12)]
    merged += [pr("feat: the one real feature", n=999)]
    pairs = [("tuna-os/compass", repo_data(merged=merged))]
    desc = description(report.build_digest("Daily", pairs, start=START, end=END))
    assert "+40 dependency bumps" in desc
    assert "+12 hive-agent PRs (strategist 12)" in desc
    assert "crate7" not in desc and "roadmap 3" not in desc
    assert "[The one real feature](https://github.com/tuna-os/compass/pull/999)" in desc


def test_highlights_capped_at_five_repos_with_also_active_line():
    pairs = [(f"tuna-os/r{i}", repo_data(f"tuna-os/r{i}", merged=[pr(f"feat: thing {i}", repo=f"tuna-os/r{i}")])) for i in range(9)]
    desc = description(report.build_digest("Daily", pairs, start=START, end=END))
    highlights = desc.split("**Highlights**\n")[1].split("\n\n")[0].splitlines()
    assert len(highlights) == 6 and highlights[-1].startswith("• Also active:")


def test_links_are_inline_not_bare_urls():
    pairs = [("tuna-os/compass", repo_data(merged=[pr("feat: a thing")]))]
    desc = description(report.build_digest("Daily", pairs, start=START, end=END))
    bare = [w for w in desc.split() if w.startswith("http")]
    assert not bare


def test_stats_line_has_deltas_vs_previous():
    pairs = [("tuna-os/compass", repo_data(merged=[pr("feat: a", n=1), pr("fix: b", n=2)]))]
    desc = description(report.build_digest("Daily", pairs, start=START, end=END, previous={"merged": 5, "issues_opened": 0}))
    stats = [line for line in desc.splitlines() if line.startswith("📊")][0]
    assert "2 merged (▼3)" in stats and "vs yesterday" in stats


def test_repeated_hive_alerts_collapse_to_one_line():
    status = {"systemAlerts": [
        {"id": "watchdog-producing-operations", "severity": "warning",
         "message": 'Agent "operations" is alive but not producing: no production evidence for 6h54m0s (threshold 6h0m0s) while 1031 item(s) are queued'},
        {"id": "watchdog-producing-telemetry", "severity": "warning",
         "message": 'Agent "telemetry" is alive but not producing: no production evidence for 6h5m0s (threshold 6h0m0s) while 1031 item(s) are queued'},
    ]}
    items = report.hive_attention(status)
    assert len(items) == 1
    assert "**operations**, **telemetry**" in items[0][1] and "1031 items queued" in items[0][1]


def test_watchdog_on_cadence_paused_agents_is_not_a_stall():
    paused = {m: "paused" for m in ("idle", "quiet", "busy", "surge")}
    status = {
        "cadenceMatrix": [{"agent": "operations", **paused}, {"agent": "telemetry", **paused},
                          {"agent": "scanner", "idle": "30m", "quiet": "20m", "busy": "10m", "surge": "5m"}],
        "systemAlerts": [
            {"id": "watchdog-producing-operations", "severity": "warning",
             "message": 'Agent "operations" is alive but not producing: no production evidence for 6h1m0s (threshold 6h0m0s) while 24 item(s) are queued'},
            {"id": "watchdog-producing-telemetry", "severity": "warning",
             "message": 'Agent "telemetry" is alive but not producing: no production evidence for 6h1m0s (threshold 6h0m0s) while 24 item(s) are queued'},
            {"id": "watchdog-producing-scanner", "severity": "warning",
             "message": 'Agent "scanner" is alive but not producing: no production evidence for 7h0m0s (threshold 6h0m0s) while 24 item(s) are queued'},
        ]}
    items = report.hive_attention(status)
    parked = [t for s, t in items if "paused by governor cadence" in t]
    assert len(parked) == 1 and "**operations**, **telemetry**" in parked[0]
    assert [s for s, t in items if t == parked[0]] == [2]
    stuck = [t for s, t in items if "produced nothing" in t]
    assert len(stuck) == 1 and "**scanner**" in stuck[0] and "operations" not in stuck[0]


# ── Discord limits ──────────────────────────────────────────────────────────

def test_huge_input_respects_discord_limits():
    pairs = []
    for i in range(60):
        repo = f"tuna-os/repo-{i}-" + "x" * 40
        merged = [pr("feat: " + "very long title " * 20, n=j, repo=repo) for j in range(30)]
        runs = [run("Build " + "y" * 80 + str(j), "failure", START + j, repo=repo) for j in range(20)]
        nh = [{"repo": repo, "number": j, "title": "t", "html_url": "https://github.com/x/y/issues/1", "kind": "issue"} for j in range(10)]
        pairs.append((repo, repo_data(repo, merged=merged, runs=runs, needs_human=nh)))
    status = {"systemAlerts": [{"id": f"a{i}-b", "severity": "critical", "message": "m" * 500} for i in range(40)]}
    for payload in (report.build_digest("T" * 400, pairs, start=START, end=END, hive_status=status),
                    report.build_ci_report("CI", pairs, start=START, end=END),
                    report.build_security_report("Sec", [(r, dict(d, security=d["merged"])) for r, d in pairs]),
                    report.build_releases_report(pairs)):
        assert payload is not None
        assert len(payload.get("content", "")) <= report.LIMIT_CONTENT
        for embed in payload["embeds"]:
            assert len(embed.get("title", "")) <= report.LIMIT_TITLE
            assert len(embed.get("description", "")) <= report.LIMIT_DESCRIPTION
            assert len(embed.get("fields", [])) <= report.LIMIT_FIELDS
            assert all(len(f["value"]) <= report.LIMIT_FIELD_VALUE for f in embed.get("fields", []))
            assert report.embed_size(embed) <= report.LIMIT_EMBED_TOTAL
        assert payload["allowed_mentions"] == {"parse": []}


def test_digest_stays_within_readability_budget():
    pairs = [(f"tuna-os/r{i}", repo_data(f"tuna-os/r{i}", merged=[pr("feat: " + "z" * 80, n=j, repo=f"tuna-os/r{i}") for j in range(20)]))
             for i in range(30)]
    payload = report.build_digest("Daily", pairs, start=START, end=END)
    assert len(description(payload)) <= report.DIGEST_DESCRIPTION_BUDGET


def test_ci_report_suppressed_when_all_green():
    runs = [run("Build A", "success", START + 1)]
    assert report.build_ci_report("CI", [("tuna-os/tunaOS", repo_data("tuna-os/tunaOS", runs=runs))], start=START, end=END) is None


def test_releases_report_skips_nightlies():
    releases = [{"tag_name": "kde-20260923", "name": "TunaOS kde (20260923)", "html_url": "u", "draft": False},
                {"tag_name": "v0.4.0", "name": "v0.4.0", "html_url": "https://github.com/tuna-os/fisherman/releases/tag/v0.4.0", "draft": False}]
    payload = report.build_releases_report([("tuna-os/fisherman", repo_data("tuna-os/fisherman", releases=releases))])
    desc = description(payload)
    assert "[v0.4.0]" in desc and "kde-20260923" not in desc and "plus 1 nightly/CI build" in desc


def test_security_report_groups_same_finding_across_repos():
    def issue(repo, n):
        return {"repo": repo, "number": n, "title": "Remove duplicate org preset entry in renovate.json",
                "html_url": f"https://github.com/{repo}/issues/{n}", "labels": [{"name": "security"}], "merged_at": None}
    pairs = [(f"tuna-os/r{i}", dict(report.empty_repo(f"tuna-os/r{i}"), security=[issue(f"tuna-os/r{i}", i)])) for i in range(4)]
    desc = description(report.build_security_report("Sec", pairs))
    assert len(desc.splitlines()) == 1 and "r0" in desc and "r3" in desc


# ── event log aggregation ───────────────────────────────────────────────────

def test_aggregate_dedupes_releases_and_tracks_needs_human():
    t = START + 100
    records = [
        {"ts": t, "event": "release", "action": "created", "repo": "tuna-os/f", "tag_name": "v1", "title": "v1",
         "url": "https://github.com/tuna-os/f/releases/tag/untagged-abc"},
        {"ts": t + 1, "event": "release", "action": "published", "repo": "tuna-os/f", "tag_name": "v1", "title": "v1",
         "url": "https://github.com/tuna-os/f/releases/tag/v1"},
        {"ts": START - 5 * DAY, "event": "pull_request", "action": "labeled", "repo": "tuna-os/f", "number": 7, "title": "x",
         "url": "u7", "labels": ["needs-human"]},
        {"ts": t, "event": "issues", "action": "labeled", "repo": "tuna-os/f", "number": 8, "title": "y", "url": "u8",
         "labels": ["needs-human"]},
        {"ts": t + 2, "event": "issues", "action": "closed", "repo": "tuna-os/f", "number": 8, "title": "y", "url": "u8",
         "labels": ["needs-human"]},
        {"ts": t, "event": "push", "action": "", "repo": "tuna-os/f", "commits": [{"sha": "a"}, {"sha": "b"}]},
        {"ts": t + 3, "event": "push", "action": "", "repo": "tuna-os/f", "commits": [{"sha": "a"}]},
    ]
    data = report.aggregate(records, START, END)["tuna-os/f"]
    assert [r["html_url"] for r in data["releases"]] == ["https://github.com/tuna-os/f/releases/tag/v1"]
    assert [i["number"] for i in data["needs_human"]] == [7]
    assert len(data["commits"]) == 2


def test_dry_run_prints_json_and_never_writes_state(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "projects.json"
    cfg.write_text(json.dumps({"daily_digest_channel_id": "1", "projects": []}))
    log = tmp_path / "events.jsonl"
    log.write_text(json.dumps({"ts": END - 100, "event": "pull_request", "action": "closed", "merged": True,
                               "repo": "tuna-os/compass", "number": 1, "title": "feat: x", "url": "u", "labels": []}) + "\n")
    state = tmp_path / "state.json"
    monkeypatch.setattr(report, "CONFIG", cfg)
    monkeypatch.setattr(report, "STATE", state)
    monkeypatch.setenv("GITHUB_EVENT_LOG", str(log))
    monkeypatch.delenv("HIVE_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("HIVE_STATUS_FILE", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    report.main(["--kind", "daily", "--dry-run", "--now", "2026-09-21T22:00:00Z"])
    out = json.loads(capsys.readouterr().out)
    assert out["channel"] == "1" and out["payload"]["embeds"][0]["description"]
    assert "_stats" not in out["payload"]
    assert not state.exists()
