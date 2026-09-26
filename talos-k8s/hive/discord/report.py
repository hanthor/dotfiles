#!/usr/bin/env python3
"""Attention-first GitHub + Hive digests for the TunaOS Discord.

Every message answers, in this order:
  1. Does anything need the human?  (or an explicit "nothing needs you")
  2. What were the 3-5 notable changes, in plain words, linked inline?
  3. One compact line of stats, with deltas against the previous period.
Routine work (dependency bumps, hive-agent housekeeping, nightly image builds)
is collapsed into a single "+N ..." line instead of being listed.

Messages are Discord embeds (colour = status) and are clamped to Discord's
limits. `--dry-run` (or DRY_RUN=1) prints the JSON payloads instead of posting
and never touches the state file.

Data sources (unchanged from the original):
  * GITHUB_EVENT_LOG  (default /data/github-events.jsonl) written by realtime.py
  * GitHub App API fallback when the event log is absent
    (GH_APP_ID / GH_INSTALLATION_ID / GH_APP_KEY_FILE, or GH_TOKEN for local runs)
  * Optional: Hive dashboard /api/status (HIVE_DASHBOARD_URL + HIVE_DASHBOARD_TOKEN,
    or HIVE_STATUS_FILE for an offline snapshot) for agent / queue attention items.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

GH = "https://api.github.com"
DISCORD = "https://discord.com/api/v10"
OWNER = os.environ.get("GITHUB_OWNER", "tuna-os")
CONFIG = pathlib.Path(os.environ.get("REPORT_CONFIG", "/config/projects.json"))
STATE = pathlib.Path(os.environ.get("REPORT_STATE", "/data/state.json"))
HIVE_URL = os.environ.get("HIVE_PUBLIC_URL", "https://hub.tunaos.org/")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}

# Discord hard limits (https://discord.com/developers/docs/resources/message).
LIMIT_CONTENT = 2000
LIMIT_TITLE = 256
LIMIT_DESCRIPTION = 4096
LIMIT_FIELDS = 25
LIMIT_FIELD_VALUE = 1024
LIMIT_FOOTER = 2048
LIMIT_EMBED_TOTAL = 6000
# Our own, stricter budget: a digest should be readable in one screen.
DIGEST_DESCRIPTION_BUDGET = 2400

RED, AMBER, GREEN, BLUE, GREY = 0xE5484D, 0xF5A524, 0x30A46C, 0x3E63DD, 0x8B8D98
FAILED = {"failure", "timed_out", "startup_failure"}
IGNORED_CONCLUSIONS = {"cancelled", "skipped", "neutral", "action_required", "stale", None, ""}
SECURITY_WORDS = ("security", "vulnerability", "vuln", "cve-", "cve ", "exploit")
FEATURE_WORDS = ("feature", "enhancement")
IMPORTANT_WORKFLOW = re.compile(r"build|release|publish|deploy|nightly|image|iso|package", re.I)
AGENT_PREFIX = re.compile(r"^\s*\[([a-z][a-z0-9-]*)\]\s*", re.I)
CONVENTIONAL = re.compile(r"^\s*(feat|fix|chore|docs|refactor|test|tests|ci|build|perf|style|revert|planning)(\([^)]*\))?!?:\s*", re.I)
DEPS = re.compile(
    r"^(chore|build|fix)\(deps[^)]*\)|^(update|bump) .*( to v?\d| digest to | from .* to )|"
    r"^update rust crate|^update dependency|^bump the .* group|^update .* bindings to|renovate|dependabot",
    re.I,
)
DATE_TAG = re.compile(r"(?:19|20)\d{2}[.-]?\d{2}[.-]?\d{2}")
HEX_TAG = re.compile(r"\b[0-9a-f]{10,40}\b")
DEFAULT_BRANCHES = {"main", "master"}


def report_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("REPORT_TIMEZONE", "UTC"))
    except Exception:  # tzdata missing in slim images → fall back to UTC
        return dt.timezone.utc


# ── HTTP ────────────────────────────────────────────────────────────────────

def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def http_json(url: str, headers: dict[str, str], method: str = "GET", data=None, timeout: int = 30):
    payload = None if data is None else json.dumps(data).encode()
    request_headers = {"Accept": "application/vnd.github+json", "User-Agent": "tunaos-discord-reports/2.0", **headers}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    for attempt in range(5):
        try:
            with urlopen(Request(url, data=payload, headers=request_headers, method=method), timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            if exc.code == 429 or exc.code >= 500:
                retry = 2 ** attempt
                try:
                    retry = float(json.loads(raw).get("retry_after", retry))
                except (ValueError, AttributeError):
                    pass
                time.sleep(min(30, retry))
                continue
            raise RuntimeError(f"HTTP {exc.code}: {raw[:240]}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 4:
                raise RuntimeError(str(exc)) from exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"request failed: {url}")


def app_token() -> str:
    if os.environ.get("GH_TOKEN") and not os.environ.get("GH_APP_ID"):
        return os.environ["GH_TOKEN"]  # local dry runs: `GH_TOKEN=$(gh auth token)`
    now = int(time.time())
    header = b64(b'{"alg":"RS256","typ":"JWT"}')
    payload = b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": os.environ["GH_APP_ID"]}, separators=(",", ":")).encode())
    unsigned = f"{header}.{payload}".encode()
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", os.environ["GH_APP_KEY_FILE"]], input=unsigned,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    jwt = f"{header}.{payload}.{b64(signature)}"
    result = http_json(f"{GH}/app/installations/{os.environ['GH_INSTALLATION_ID']}/access_tokens",
                       {"Authorization": f"Bearer {jwt}"}, method="POST", data={})
    return result["token"]


def gh(path: str, token: str):
    return http_json(GH + path, {"Authorization": f"Bearer {token}"})


# ── Normalised data model ───────────────────────────────────────────────────

def empty_repo(repo: str) -> dict:
    """Per-repo bucket. The first eight keys are the original report's keys."""
    return {"repo": repo, "pulls": [], "merged": [], "issues": [], "commits": [], "releases": [],
            "failures": [], "security": [], "features": [],
            "opened_issues": [], "closed_issues": [], "runs": [], "needs_human": []}


def parse_time(value: str | None):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def text_of(item: dict) -> str:
    labels = " ".join(l.get("name", "") if isinstance(l, dict) else str(l) for l in item.get("labels", []))
    return f"{item.get('title', '')} {labels}".lower()


def label_names(item: dict) -> list[str]:
    return [l.get("name", "") if isinstance(l, dict) else str(l) for l in item.get("labels", [])]


def is_security(item: dict) -> bool:
    return any(word in text_of(item) + " " for word in SECURITY_WORDS)


def classify_pr(item: dict) -> str:
    """feature | fix | security | deps | agent | other."""
    title = item.get("title", "")
    labels = [x.lower() for x in label_names(item)]
    if AGENT_PREFIX.match(title) or any(x.startswith("agent/") for x in labels):
        return "agent"
    if DEPS.search(title) or "dependencies" in labels or (item.get("author") or "").endswith(("renovate[bot]", "dependabot[bot]")):
        return "deps"
    if is_security(item):
        return "security"
    lowered = title.lower()
    if lowered.startswith("feat") or any(x in labels for x in FEATURE_WORDS):
        return "feature"
    if lowered.startswith("fix") or "bug" in labels:
        return "fix"
    if CONVENTIONAL.match(title):  # chore/docs/ci/test/refactor
        return "chore"
    return "other"


def agent_of(item: dict) -> str:
    match = AGENT_PREFIX.match(item.get("title", ""))
    if match:
        return match.group(1).lower()
    for label in label_names(item):
        if label.lower().startswith("agent/"):
            return label.split("/", 1)[1].lower()
    return "agent"


def is_nightly_release(release: dict) -> bool:
    tag, name = release.get("tag_name", ""), release.get("name", "") or ""
    return bool(release.get("prerelease") or release.get("draft") or DATE_TAG.search(tag) or DATE_TAG.search(name)
                or HEX_TAG.search(tag) or HEX_TAG.search(name) or "latest" in tag.lower() or "untagged-" in release.get("html_url", ""))


def clean_title(title: str, limit: int = 90) -> str:
    """Turn a PR/issue title into a plain phrase suitable as link text."""
    title = AGENT_PREFIX.sub("", title or "")
    title = CONVENTIONAL.sub("", title).strip()
    title = re.sub(r"\s+\(#\d+\)$", "", title)
    title = title.replace("[", "(").replace("]", ")").replace("`", "'")
    if title:
        title = title[0].upper() + title[1:]
    if len(title) > limit:
        cut = title[: limit - 1].rsplit(" ", 1)[0]
        title = (cut or title[: limit - 1]).rstrip(",;:-") + "…"
    return title


def md_link(label: str, url: str) -> str:
    return f"[{label}]({url})" if url else label


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


# ── Event log → per-repo buckets ────────────────────────────────────────────

def read_event_log(path: pathlib.Path, since: float = 0.0) -> list[dict]:
    """Parse the JSONL log, skipping records older than `since` (bounds memory:
    the log is append-only and grows ~2 MB/day)."""
    records = []
    if not path.exists():
        return records
    with path.open(errors="replace") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("repo") and float(record.get("ts", 0) or 0) >= since:
                records.append(record)
    return records


def aggregate(records: list[dict], start: float, end: float) -> dict[str, dict]:
    """Bucket event-log records into per-repo data for the window [start, end).

    CI runs are kept from *before* the window too, so failure streaks
    ("red for 9 days") can be computed. Needs-human items use the latest known
    state of each issue/PR regardless of when it last changed.
    """
    result: dict[str, dict] = {}
    releases: dict[tuple, dict] = {}
    commits_seen: set[str] = set()
    latest_item: dict[tuple, dict] = {}
    for record in records:
        ts = float(record.get("ts", 0) or 0)
        if ts >= end:
            continue
        repo = record["repo"]
        event, action = record.get("event"), record.get("action", "")
        if event in {"issues", "pull_request"} and record.get("number") is not None:
            latest_item[(repo, event, record["number"])] = record
        if event == "workflow_run" and action == "completed":
            data = result.setdefault(repo, empty_repo(repo))
            data["runs"].append({"repo": repo, "name": record.get("name", "workflow"), "conclusion": record.get("conclusion"),
                                 "html_url": record.get("url", ""), "ts": ts, "branch": record.get("branch"),
                                 "default_branch": record.get("default_branch"), "trigger": record.get("trigger")})
            if ts >= start and record.get("conclusion") in FAILED:
                data["failures"].append({"name": record.get("name", "workflow"), "html_url": record.get("url", "")})
            continue
        if ts < start:
            continue
        data = result.setdefault(repo, empty_repo(repo))
        item = {"repo": repo, "number": record.get("number"), "title": record.get("title", ""), "html_url": record.get("url", ""),
                "merged_at": record.get("merged_at"), "labels": [{"name": x} for x in record.get("labels", [])],
                "author": record.get("author")}
        if event == "pull_request" and action in {"opened", "closed", "reopened"}:
            data["pulls"].append(item)
            if action == "closed" and record.get("merged"):
                data["merged"].append(item)
                if classify_pr(item) == "feature":
                    data["features"].append(item)
                if is_security(item):
                    data["security"].append(item)
        elif event == "issues" and action in {"opened", "closed", "reopened"}:
            data["issues"].append(item)
            (data["opened_issues"] if action == "opened" else data["closed_issues"]).append(item)
            if action == "opened" and is_security(item):
                data["security"].append(item)
        elif event == "release" and action in {"published", "released", "created"}:
            key = (repo, record.get("tag_name") or record.get("title"))
            rel = {"tag_name": record.get("tag_name", ""), "name": record.get("title", ""), "html_url": record.get("url", ""),
                   "draft": record.get("draft", "untagged-" in record.get("url", "")), "prerelease": record.get("prerelease", False)}
            old = releases.get(key)
            if old is None or (old["draft"] and not rel["draft"]):
                releases[key] = rel
        elif event == "push":
            for commit in record.get("commits", []):
                sha = commit.get("sha", "")
                if sha and sha in commits_seen:
                    continue
                commits_seen.add(sha)
                data["commits"].append({"sha": sha, "message": commit.get("message", ""), "html_url": commit.get("url", "")})
    for (repo, _tag), rel in releases.items():
        if not rel["draft"]:
            result.setdefault(repo, empty_repo(repo))["releases"].append(rel)
    for (repo, kind, _number), record in latest_item.items():
        labels = record.get("labels", [])
        if "needs-human" in labels and record.get("action") != "closed" and record.get("state", "open") != "closed":
            result.setdefault(repo, empty_repo(repo))["needs_human"].append(
                {"repo": repo, "number": record.get("number"), "title": record.get("title", ""), "html_url": record.get("url", ""),
                 "kind": "PR" if kind == "pull_request" else "issue"})
    for data in result.values():
        data["runs"].sort(key=lambda run: run["ts"])
    return result


def load_event_data(start: dt.datetime, end: dt.datetime | None = None, records: list[dict] | None = None) -> dict[str, dict]:
    """Back-compat wrapper: original signature was load_event_data(start)."""
    if records is None:
        records = read_event_log(pathlib.Path(os.environ.get("GITHUB_EVENT_LOG", "/data/github-events.jsonl")))
    end = end or dt.datetime.now(dt.timezone.utc)
    return aggregate(records, start.timestamp(), end.timestamp())


def collect(repo: str, start: dt.datetime, token: str, end: dt.datetime | None = None, default_branch: str | None = None) -> dict:
    """GitHub API fallback, used only when the webhook event log is absent."""
    end = end or dt.datetime.now(dt.timezone.utc)

    def within(value):
        parsed = parse_time(value)
        return bool(parsed and start <= parsed < end)

    base = f"/repos/{repo}"
    data = empty_repo(repo)
    for pr in gh(base + "/pulls?state=all&sort=updated&direction=desc&per_page=100", token):
        item = {"repo": repo, "number": pr["number"], "title": pr.get("title", ""), "html_url": pr.get("html_url", ""),
                "merged_at": pr.get("merged_at"), "labels": pr.get("labels", []), "author": (pr.get("user") or {}).get("login")}
        if within(pr.get("created_at")) or within(pr.get("closed_at")):
            data["pulls"].append(item)
        if within(pr.get("merged_at")):
            data["merged"].append(item)
            if classify_pr(item) == "feature":
                data["features"].append(item)
            if is_security(item):
                data["security"].append(item)
        if pr.get("state") == "open" and "needs-human" in label_names(pr):
            data["needs_human"].append({**item, "kind": "PR"})
    for issue in gh(base + "/issues?state=all&sort=updated&direction=desc&per_page=100", token):
        if "pull_request" in issue:
            continue
        item = {"repo": repo, "number": issue["number"], "title": issue.get("title", ""), "html_url": issue.get("html_url", ""),
                "labels": issue.get("labels", [])}
        if within(issue.get("created_at")):
            data["issues"].append(item)
            data["opened_issues"].append(item)
            if is_security(item):
                data["security"].append(item)
        elif within(issue.get("closed_at")):
            data["issues"].append(item)
            data["closed_issues"].append(item)
        if issue.get("state") == "open" and "needs-human" in label_names(issue):
            data["needs_human"].append({**item, "kind": "issue"})
    try:
        commits = gh(base + "/commits?since=" + quote(start.isoformat().replace("+00:00", "Z"), safe="") + "&per_page=100", token)
        data["commits"] = commits if isinstance(commits, list) else []
    except RuntimeError:
        pass
    for rel in gh(base + "/releases?per_page=50", token):
        if within(rel.get("published_at")) and not rel.get("draft"):
            data["releases"].append({"tag_name": rel.get("tag_name", ""), "name": rel.get("name") or "", "html_url": rel.get("html_url", ""),
                                     "draft": False, "prerelease": rel.get("prerelease", False)})
    try:
        query = {"per_page": 100, "created": ">=" + (start - dt.timedelta(days=14)).date().isoformat()}
        if default_branch:
            query["branch"] = default_branch
        runs = gh(base + "/actions/runs?" + urlencode(query), token).get("workflow_runs", [])
    except RuntimeError:
        runs = []
    for run in sorted(runs, key=lambda r: r.get("created_at", "")):
        created = parse_time(run.get("updated_at") or run.get("created_at"))
        if not created or created >= end:
            continue
        data["runs"].append({"repo": repo, "name": run.get("name", "workflow"), "conclusion": run.get("conclusion"),
                             "html_url": run.get("html_url", ""), "ts": created.timestamp(), "branch": run.get("head_branch"),
                             "default_branch": default_branch, "trigger": run.get("event")})
        if created >= start and run.get("conclusion") in FAILED:
            data["failures"].append({"name": run.get("name", "workflow"), "html_url": run.get("html_url", "")})
    return data


def active(data: dict) -> bool:
    return any(data.get(k) for k in ("pulls", "merged", "issues", "releases", "failures", "needs_human"))


def activity_score(data: dict) -> int:
    """Rank repositories by notable work, not raw volume."""
    score = 0
    for item in data.get("merged", []):
        score += {"feature": 5, "security": 4, "fix": 3, "other": 2, "chore": 1, "agent": 1, "deps": 0}[classify_pr(item)]
    score += 8 * sum(1 for r in data.get("releases", []) if not is_nightly_release(r))
    score += 2 * len(data.get("needs_human", []))
    return score


# ── Analysis ────────────────────────────────────────────────────────────────

def run_counts(run: dict) -> bool:
    """Only default-branch, non-PR runs count as 'CI is broken' when we know."""
    branch, default = run.get("branch"), run.get("default_branch")
    if run.get("trigger") == "pull_request":
        return False
    if branch and default:
        return branch == default
    if branch:
        return branch in DEFAULT_BRANCHES
    return True  # legacy records: branch unknown


def ci_health(runs: list[dict], start: float, end: float) -> dict:
    """Per-workflow streaks → newly broken, still broken, fixed.

    `runs` must be chronological. A workflow is broken when its latest
    decisive run (cancelled/skipped ignored) failed; the streak is the number
    of consecutive failed runs and `since` the first of them.
    """
    by_workflow: dict[tuple, list[dict]] = collections.defaultdict(list)
    for run in runs:
        if run.get("conclusion") in IGNORED_CONCLUSIONS or not run_counts(run) or run["ts"] >= end:
            continue
        by_workflow[(run["repo"], run["name"])].append(run)
    newly, still, fixed = [], [], []
    for (repo, name), seq in by_workflow.items():
        streak = 0
        for run in reversed(seq):
            if run["conclusion"] in FAILED:
                streak += 1
            else:
                break
        last = seq[-1]
        if streak:
            since = seq[-streak]["ts"]
            entry = {"repo": repo, "name": name, "streak": streak, "since": since, "html_url": last["html_url"],
                     "important": bool(IMPORTANT_WORKFLOW.search(name))}
            (newly if since >= start else still).append(entry)
        elif last["ts"] >= start and any(r["conclusion"] in FAILED for r in seq if r["ts"] < last["ts"]) and \
                len(seq) >= 2 and seq[-2]["conclusion"] in FAILED:
            fixed.append({"repo": repo, "name": name, "html_url": last["html_url"]})
    key = lambda e: (not e["important"], -e["streak"], e["repo"], e["name"])
    return {"newly": sorted(newly, key=key), "still": sorted(still, key=lambda e: (not e["important"], e["since"])), "fixed": fixed}


def summarise_period(pairs: list[tuple[str, dict]], start: float, end: float) -> dict:
    merged = [i for _, d in pairs for i in d["merged"]]
    kinds = collections.Counter(classify_pr(i) for i in merged)
    runs = [r for _, d in pairs for r in d["runs"]]
    ci = ci_health(sorted(runs, key=lambda r: r["ts"]), start, end)
    releases = [r for _, d in pairs for r in d["releases"]]
    return {
        "merged": len(merged),
        "notable": sum(kinds[k] for k in ("feature", "fix", "security", "other")),
        "deps": kinds["deps"],
        "agent": kinds["agent"],
        "issues_opened": sum(len(d["opened_issues"]) for _, d in pairs),
        "issues_closed": sum(len(d["closed_issues"]) for _, d in pairs),
        "releases": sum(1 for r in releases if not is_nightly_release(r)),
        "nightly": sum(1 for r in releases if is_nightly_release(r)),
        "ci_red": len(ci["newly"]) + len(ci["still"]),
        "needs_human": sum(len(d["needs_human"]) for _, d in pairs),
    }


def delta(current: int, previous: int | None) -> str:
    if previous is None or current == previous:
        return ""
    return f" ({'▲' if current > previous else '▼'}{abs(current - previous)})"


def fmt_age(seconds: float) -> str:
    hours = seconds / 3600
    if hours < 1:
        return f"{max(1, int(seconds // 60))}m"
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours // 24)}d"


# ── Attention items ─────────────────────────────────────────────────────────
# Each item: (severity, text): 0 = red/critical, 1 = amber and needs a human
# decision (review, login, stuck agent), 2 = amber background noise that is
# still worth one line (long-running red CI).

def ci_attention(ci: dict, now: float, repo_scoped: bool = False) -> list[tuple[int, str]]:
    """Newly-red build/release workflows get their own red line; everything
    else red in CI is folded into a single low-priority line."""
    def name(entry):
        where = "" if repo_scoped else f"{entry['repo'].split('/')[-1]} "
        return md_link(f"{where}{entry['name']}", entry["html_url"])

    items: list[tuple[int, str]] = []
    urgent = [e for e in ci["newly"] if e["important"]]
    minor = [e for e in ci["newly"] if not e["important"]]
    for entry in urgent[:3]:
        runs = f", {plural(entry['streak'], 'run')} in a row" if entry["streak"] > 1 else ""
        items.append((0, f"{name(entry)} started failing {fmt_age(now - entry['since'])} ago{runs}"))
    minor = urgent[3:] + minor
    bits = []
    if minor:
        more = f" +{len(minor) - 2}" if len(minor) > 2 else ""
        bits.append("newly red: " + ", ".join(name(e) for e in minor[:2]) + more)
    if ci["still"]:
        oldest = min(ci["still"], key=lambda e: e["since"])
        bits.append(f"{plural(len(ci['still']), 'workflow')} red for days (oldest: {name(oldest)}, {fmt_age(now - oldest['since'])})")
    if bits:
        items.append((2, "CI " + "; ".join(bits)))
    return items


def needs_human_attention(pairs: list[tuple[str, dict]], repo_scoped: bool = False) -> list[tuple[int, str]]:
    items = [i for _, d in pairs for i in d.get("needs_human", [])]
    if not items:
        return []
    shown = ", ".join(
        md_link(("" if repo_scoped else i["repo"].split("/")[-1]) + f"#{i['number']}", i["html_url"]) for i in items[:4])
    more = f" +{len(items) - 4} more" if len(items) > 4 else ""
    return [(1, f"{plural(len(items), 'item')} labelled **needs-human**: {shown}{more}")]


WATCHDOG = re.compile(r'Agent "?([\w-]+)"? is alive but not producing: no production evidence for (\d+)h.*?while (\d+) item', re.I)
NO_CADENCE = re.compile(r"agent\(s\) ([\w, -]+?) enabled but never kicked", re.I)


def summarise_alerts(alerts: list[dict]) -> tuple[int, str]:
    """Collapse a group of hive systemAlerts (same id prefix) into one short line."""
    worst = 0 if any(a.get("severity") in {"critical", "error"} for a in alerts) else 1
    messages = [str(a.get("message", "")) for a in alerts]
    stuck = [m for m in map(WATCHDOG.search, messages) if m]
    if stuck and len(stuck) == len(messages):
        names = ", ".join(f"**{m.group(1)}**" for m in stuck)
        hours = max(int(m.group(2)) for m in stuck)
        verb = "is" if len(stuck) == 1 else "are"
        return worst, f"{names} {verb} running but produced nothing for {hours}h+ ({stuck[0].group(3)} items queued)"
    idle = [m for m in map(NO_CADENCE.search, messages) if m]
    if idle and len(idle) == len(messages):
        names = ", ".join(f"**{n.strip()}**" for m in idle for n in m.group(1).split(","))
        return worst, f"{names} enabled but has no cadence, so it never runs"
    text = messages[0].rstrip(".")
    text = text if len(text) <= 160 else text[:159].rsplit(" ", 1)[0] + "…"
    if len(alerts) > 1:
        text += f" (+{len(alerts) - 1} similar)"
    return worst, text


def cadence_paused_agents(status: dict) -> set[str]:
    """Agents whose governor cadence is `paused` in every mode.

    Uses /api/status `cadenceMatrix` (one row per agent, a column per mode);
    falls back to the per-agent `cadence` when the matrix is absent."""
    modes = ("idle", "quiet", "busy", "surge")
    matrix = status.get("cadenceMatrix") or []
    if matrix:
        return {row.get("agent") for row in matrix
                if all(str(row.get(m, "")).lower() == "paused" for m in modes)}
    return {a.get("name") for a in status.get("agents", []) if str(a.get("cadence", "")).lower() == "paused"}


def hive_attention(status: dict | None) -> list[tuple[int, str]]:
    if not status:
        return []
    items: list[tuple[int, str]] = []
    budget = status.get("budget") or {}
    if budget.get("BUDGET_EXHAUSTED"):
        items.append((0, "Model budget is **exhausted** — agents are stalled until it resets"))
    for agent in status.get("agents", []):
        if agent.get("needsLogin"):
            items.append((0, f"Agent **{agent.get('name')}** needs you to log in again"))
    breaker = status.get("breaker") or {}
    if breaker.get("engaged"):
        items.append((0, "Fleet circuit breaker is **engaged** — all agents are held"))
    # The hive's "not producing" watchdog also fires for agents the governor is
    # configured never to kick (cadence `paused` in every mode — operations and
    # telemetry in this fleet). That is a deliberate config, not a stall, so it
    # must not read as "running but produced nothing". Report it as one quiet
    # line instead: the queued lane work is still worth knowing about.
    never_kicked = cadence_paused_agents(status)
    alerts_in, parked = [], []
    for alert in status.get("systemAlerts") or []:
        match = WATCHDOG.search(str(alert.get("message", "")))
        (parked if match and match.group(1) in never_kicked else alerts_in).append(alert)
    if parked:
        matches = [WATCHDOG.search(str(a.get("message", ""))) for a in parked]
        names = ", ".join(f"**{m.group(1)}**" for m in matches)
        verb = "is" if len(matches) == 1 else "are"
        items.append((2, f"{names} {verb} paused by governor cadence in every mode, so never kicked "
                         f"({matches[0].group(3)} items queued)"))
    groups: dict[str, list[dict]] = collections.OrderedDict()
    for alert in alerts_in:
        prefix = "-".join(str(alert.get("id", "")).split("-")[:2]) or alert.get("message", "")
        groups.setdefault(prefix, []).append(alert)
    for alerts in groups.values():
        items.append(summarise_alerts(alerts))
    for alert in (status.get("ghRateLimits") or {}).get("alerts") or []:
        items.append((1, f"GitHub rate limit: {alert.get('message', alert) if isinstance(alert, dict) else alert}"))
    hold = status.get("hold") or {}
    if hold.get("total"):
        classes = collections.Counter((i.get("review_class") or "other") for i in hold.get("items", []))
        detail = ", ".join(f"{n} {k}" for k, n in classes.most_common(3))
        items.append((1, f"{md_link(plural(hold['total'], 'hive PR') + ' on hold', HIVE_URL)} waiting for your review"
                         + (f" ({detail})" if detail else "")))
    planning = status.get("planning") or {}
    if planning.get("awaiting_review"):
        items.append((1, f"{plural(planning['awaiting_review'], 'plan')} awaiting your review"))
    return items


# ── Highlights ──────────────────────────────────────────────────────────────

PRIORITY = {"feature": 0, "security": 1, "fix": 2, "other": 3, "chore": 4, "agent": 5, "deps": 6}
VERB = {"feature": "New", "security": "Security", "fix": "Fixed", "other": "Changed"}
KIND_WORDS = {"feature": ("feature", "features"), "fix": ("fix", "fixes"), "security": ("security fix", "security fixes"),
              "other": ("other change", "other changes"), "chore": ("housekeeping PR", "housekeeping PRs")}


def kind_summary(items: list[dict], top: int = 3) -> str:
    """'7 features, 2 fixes, 9 housekeeping PRs' — words, not a stats wall."""
    kinds = collections.Counter(classify_pr(i) for i in items)
    return ", ".join(f"{n} {KIND_WORDS[k][0] if n == 1 else KIND_WORDS[k][1]}" for k, n in kinds.most_common(top) if k in KIND_WORDS)


def repo_highlight(repo: str, data: dict, scoped: bool = False) -> tuple[int, str] | None:
    """One plain-language line per repo, or None if it only had routine work."""
    name = repo.split("/")[-1]
    real_releases = [r for r in data["releases"] if not is_nightly_release(r)]
    notable = sorted((i for i in data["merged"] if classify_pr(i) in VERB), key=lambda i: PRIORITY[classify_pr(i)])
    if not real_releases and not notable:
        return None
    parts = []
    if real_releases:
        rel = real_releases[0]
        parts.append(f"shipped {md_link(rel.get('tag_name') or rel.get('name'), rel['html_url'])}")
    if notable:
        top = notable[0]
        parts.append(f"{VERB[classify_pr(top)].lower() if parts else VERB[classify_pr(top)]}: "
                     f"{md_link(clean_title(top['title']), top['html_url'])}")
    rest = notable[1:] + [i for i in data["merged"] if classify_pr(i) == "chore"]
    if rest:
        parts.append(f"and {len(rest)} more ({kind_summary(rest)})")
    score = 8 * len(real_releases) + sum(5 - min(PRIORITY[classify_pr(i)], 4) for i in notable)
    prefix = "" if scoped else f"**{name}** — "
    return score, prefix + " · ".join(parts)


def item_highlights(data: dict, limit: int = 4) -> list[str]:
    """Repo-scoped highlights: the top few changes, one per line."""
    out = [f"Shipped {md_link(r.get('tag_name') or r.get('name'), r['html_url'])}"
           for r in data["releases"] if not is_nightly_release(r)][:2]
    notable = sorted((i for i in data["merged"] if classify_pr(i) in VERB), key=lambda i: PRIORITY[classify_pr(i)])
    room = max(0, limit - len(out))
    out += [f"{VERB[classify_pr(i)]}: {md_link(clean_title(i['title']), i['html_url'])}" for i in notable[:room]]
    rest = notable[room:] + [i for i in data["merged"] if classify_pr(i) == "chore"]
    if rest:
        out.append(f"and {len(rest)} more ({kind_summary(rest)})")
    return out


def routine_tail(pairs: list[tuple[str, dict]]) -> str:
    merged = [i for _, d in pairs for i in d["merged"]]
    deps = sum(1 for i in merged if classify_pr(i) == "deps")
    agents = collections.Counter(agent_of(i) for i in merged if classify_pr(i) == "agent")
    nightly = sum(1 for _, d in pairs for r in d["releases"] if is_nightly_release(r))
    parts = []
    if agents:
        top = ", ".join(f"{k} {n}" for k, n in agents.most_common(3))
        parts.append(f"+{sum(agents.values())} hive-agent PRs ({top})")
    if deps:
        parts.append(f"+{plural(deps, 'dependency bump')}")
    if nightly:
        parts.append(f"+{plural(nightly, 'nightly/CI build')} published")
    return " · ".join(parts)


# ── Rendering ───────────────────────────────────────────────────────────────

def section(title: str, lines: list[str]) -> str:
    return f"**{title}**\n" + "\n".join(lines) if lines else ""


def clamp_lines(lines: list[str], budget: int, overflow: str = "+{n} more") -> list[str]:
    """Keep whole lines until the budget is spent; summarise the rest."""
    kept, used = [], 0
    for index, line in enumerate(lines):
        if used + len(line) + 1 > budget:
            remaining = len(lines) - index
            kept.append(overflow.format(n=remaining))
            break
        kept.append(line)
        used += len(line) + 1
    return kept


def embed_size(embed: dict) -> int:
    return (len(embed.get("title", "")) + len(embed.get("description", "")) + len((embed.get("footer") or {}).get("text", ""))
            + len((embed.get("author") or {}).get("name", ""))
            + sum(len(f.get("name", "")) + len(f.get("value", "")) for f in embed.get("fields", [])))


def enforce_limits(payload: dict) -> dict:
    """Clamp a message payload to Discord's hard limits (defence in depth)."""
    payload = json.loads(json.dumps(payload))
    if len(payload.get("content", "")) > LIMIT_CONTENT:
        payload["content"] = payload["content"][: LIMIT_CONTENT - 1] + "…"
    total = 0
    for embed in payload.get("embeds", [])[:10]:
        if len(embed.get("title", "")) > LIMIT_TITLE:
            embed["title"] = embed["title"][: LIMIT_TITLE - 1] + "…"
        if len(embed.get("description", "")) > LIMIT_DESCRIPTION:
            embed["description"] = embed["description"][: LIMIT_DESCRIPTION - 1].rsplit("\n", 1)[0] + "\n…"
        embed["fields"] = embed.get("fields", [])[:LIMIT_FIELDS]
        for field in embed["fields"]:
            if len(field["value"]) > LIMIT_FIELD_VALUE:
                field["value"] = field["value"][: LIMIT_FIELD_VALUE - 1].rsplit("\n", 1)[0] + "\n…"
        if not embed["fields"]:
            embed.pop("fields")
        if "footer" in embed and len(embed["footer"]["text"]) > LIMIT_FOOTER:
            embed["footer"]["text"] = embed["footer"]["text"][: LIMIT_FOOTER - 1] + "…"
        budget = LIMIT_EMBED_TOTAL - total
        dropped = 0
        while embed_size(embed) > budget and embed.get("fields"):
            embed["fields"].pop()
            dropped += 1
        if dropped:
            embed.setdefault("footer", {"text": ""})
            embed["footer"]["text"] = (f"+{dropped} more not shown · " + embed["footer"]["text"]).strip(" ·")
        while embed_size(embed) > budget and embed.get("description"):
            cut = embed["description"].rsplit("\n", 1)[0]
            if cut == embed["description"]:
                cut = cut[: max(0, len(cut) - (embed_size(embed) - budget) - 1)]
            embed["description"] = cut
        if not embed.get("fields"):
            embed.pop("fields", None)
        total += embed_size(embed)
    payload["embeds"] = payload.get("embeds", [])[:10]
    payload["allowed_mentions"] = {"parse": []}
    return payload


def build_digest(title: str, pairs: list[tuple[str, dict]], *, start: float, end: float, previous: dict | None = None,
                 hive_status: dict | None = None, kind: str = "daily", repo_scoped: bool = False, url: str | None = None) -> dict:
    """The one message builder. Returns a Discord message payload."""
    now = end
    runs = sorted((r for _, d in pairs for r in d["runs"]), key=lambda r: r["ts"])
    ci = ci_health(runs, start, end)
    attention = ci_attention(ci, now, repo_scoped) + needs_human_attention(pairs, repo_scoped) + hive_attention(hive_status)
    attention.sort(key=lambda item: item[0])  # stable: red first, original order within
    colour = GREEN if not attention else (RED if attention[0][0] == 0 else AMBER)

    lines: list[str] = []
    if attention:
        icons = {0: "🔴", 1: "🟠", 2: "🟡"}
        lines.append(section("Needs you", clamp_lines([f"{icons[s]} {t}" for s, t in attention[:7]] +
                                                      ([f"+{len(attention) - 7} more"] if len(attention) > 7 else []), 1100,
                                                      "+{n} more — see " + md_link("the hive", HIVE_URL))))
    else:
        lines.append("✅ **Nothing needs you" + (" today" if kind == "daily" else " this week") + ".**")

    if repo_scoped:
        highlight_lines = [f"• {text}" for text in item_highlights(pairs[0][1]) ] if pairs else []
    else:
        ranked = []
        for repo, data in pairs:
            hl = repo_highlight(repo, data)
            if hl:
                ranked.append((hl[0], repo, hl[1]))
        ranked.sort(key=lambda x: (-x[0], x[1].lower()))
        limit = 5
        highlight_lines = [f"• {text}" for _, _, text in ranked[:limit]]
        if len(ranked) > limit:
            others = ", ".join(r.split("/")[-1] for _, r, _ in ranked[limit:limit + 4])
            extra = f" +{len(ranked) - limit - 4}" if len(ranked) > limit + 4 else ""
            highlight_lines.append(f"• Also active: {others}{extra}")
    if highlight_lines:
        lines.append(section("Highlights", clamp_lines(highlight_lines, 1200)))
    elif not attention:
        lines.append("Quiet period — no notable merges or releases.")

    tail = routine_tail(pairs)
    if tail:
        lines.append(f"_{tail}_")

    cur = summarise_period(pairs, start, end)
    prev = previous or {}
    period = "yesterday" if kind == "daily" else "last week"
    stats = [f"{cur['merged']} merged{delta(cur['merged'], prev.get('merged'))}"]
    if cur["issues_opened"] or cur["issues_closed"]:
        stats.append(f"{cur['issues_opened']} issues opened{delta(cur['issues_opened'], prev.get('issues_opened'))}, "
                     f"{cur['issues_closed']} closed")
    if cur["releases"]:
        stats.append(plural(cur["releases"], "release"))
    ci_bits = []
    if ci["newly"]:
        ci_bits.append(f"{len(ci['newly'])} newly red")
    if ci["still"]:
        ci_bits.append(f"{len(ci['still'])} still red")
    if ci["fixed"]:
        ci_bits.append(f"{len(ci['fixed'])} fixed")
    stats.append("CI " + (", ".join(ci_bits) if ci_bits else "green"))
    if hive_status and (hive_status.get("governor") or {}).get("mode"):
        stats.append(f"hive {hive_status['governor']['mode'].upper()}")
    stats_line = "📊 " + " · ".join(stats) + (f"  _vs {period}_" if previous else "")
    lines.append(stats_line)

    description = "\n\n".join(x for x in lines if x)
    if len(description) > DIGEST_DESCRIPTION_BUDGET:
        description = description[: DIGEST_DESCRIPTION_BUDGET - 1].rsplit("\n", 1)[0] + "\n…"
    tz = report_tz()
    a, b = dt.datetime.fromtimestamp(start, tz), dt.datetime.fromtimestamp(end, tz)
    window = f"{a:%a %d %b %H:%M} → {b:%a %d %b %H:%M} {b.tzname() or ''}".strip() + " · hub.tunaos.org"
    embed = {"title": title, "description": description, "color": colour, "footer": {"text": window}}
    if url:
        embed["url"] = url
    n_attention = len(attention)
    summary = (f"{'🔴' if colour == RED else '🟠'} {plural(n_attention, 'thing')} need{'s' if n_attention == 1 else ''} you"
               if attention else "✅ Nothing needs you")
    if attention and all(sev == 2 for sev, _ in attention):
        colour = AMBER
    return enforce_limits({"content": f"{summary} · {title}", "embeds": [embed], "_stats": cur})


def build_ci_report(title: str, pairs: list[tuple[str, dict]], *, start: float, end: float,
                    per_repo: int = 3, max_repos: int = 10) -> dict | None:
    runs = sorted((r for _, d in pairs for r in d["runs"]), key=lambda r: r["ts"])
    ci = ci_health(runs, start, end)
    if not ci["newly"] and not ci["still"]:
        return None
    newly_ids = {(e["repo"], e["name"]) for e in ci["newly"]}
    by_repo: dict[str, list[dict]] = collections.defaultdict(list)
    for entry in ci["newly"] + ci["still"]:
        by_repo[entry["repo"].split("/")[-1]].append(entry)
    # Repos with a newly-red build/release workflow first, then by count.
    order = sorted(by_repo.items(), key=lambda kv: (not any(e["important"] and (e["repo"], e["name"]) in newly_ids for e in kv[1]),
                                                    -len(kv[1]), kv[0].lower()))
    fields = []
    for repo, entries in order[:max_repos]:
        entries.sort(key=lambda e: ((e["repo"], e["name"]) not in newly_ids, not e["important"], e["since"]))
        lines = [f"{'🆕 ' if (e['repo'], e['name']) in newly_ids else ''}{md_link(e['name'], e['html_url'])} — red {fmt_age(end - e['since'])}"
                 for e in entries[:per_repo]]
        if len(entries) > per_repo:
            lines.append(f"+{len(entries) - per_repo} more")
        fields.append({"name": repo, "value": "\n".join(lines), "inline": False})
    hidden = order[max_repos:]
    desc = [f"**{len(ci['newly'])} newly red** this period · {len(ci['still'])} red for longer · {len(ci['fixed'])} fixed"]
    if hidden:
        desc.append(f"+{sum(len(v) for _, v in hidden)} red workflows in {', '.join(r for r, _ in hidden[:5])}"
                    + (f" +{len(hidden) - 5} repos" if len(hidden) > 5 else ""))
    colour = RED if any(e["important"] for e in ci["newly"]) else AMBER
    return enforce_limits({"content": "", "embeds": [{"title": title, "description": "\n".join(desc), "color": colour, "fields": fields}]})


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", clean_title(title, 200).lower()).replace(f"{OWNER} ", "")


def build_security_report(title: str, pairs: list[tuple[str, dict]]) -> dict | None:
    """Group identical findings across repos; collapse agent PR volume."""
    themes: dict[str, list[dict]] = collections.OrderedDict()
    agent_count, agent_repos = 0, set()
    for repo, data in pairs:
        for item in data["security"]:
            if classify_pr(item) == "agent" and item.get("merged_at") is not None:
                agent_count += 1
                agent_repos.add(repo)
                continue
            key = title_key(re.sub(r"^[\w .-]+:\s*", "", item.get("title", "")) if ":" in item.get("title", "")[:30] else item.get("title", ""))
            key = re.sub(r"^(remove|fix|resolve) ", "", key)
            themes.setdefault(key, []).append(item)
    if not themes and not agent_count:
        return None
    lines = []
    for items in sorted(themes.values(), key=lambda v: -len(v))[:10]:
        first = items[0]
        if len(items) == 1:
            lines.append(f"• **{first['repo'].split('/')[-1]}** — {md_link(clean_title(first['title']), first['html_url'])}")
        else:
            repos = ", ".join(md_link(i["repo"].split("/")[-1], i["html_url"]) for i in items[:5])
            more = f" +{len(items) - 5}" if len(items) > 5 else ""
            lines.append(f"• {clean_title(first['title'])} — {repos}{more}")
    if len(themes) > 10:
        lines.append(f"+{len(themes) - 10} more findings")
    if agent_count:
        lines.append(f"_+{plural(agent_count, 'hive-agent security PR')} merged across {plural(len(agent_repos), 'repo')}_")
    colour = RED if any(classify_pr(i) != "agent" and i.get("merged_at") is None for v in themes.values() for i in v) else AMBER
    return enforce_limits({"content": "", "embeds": [{"title": title, "description": "\n".join(lines), "color": colour}]})


def build_releases_report(pairs: list[tuple[str, dict]], title: str = "🚀 Releases & features this week") -> dict | None:
    shipped, nightly, fields = [], 0, []
    for repo, data in pairs:
        real = [r for r in data["releases"] if not is_nightly_release(r)]
        nightly += len(data["releases"]) - len(real)
        if real:
            tags = ", ".join(md_link(r.get("tag_name") or r.get("name"), r["html_url"]) for r in real[:3])
            shipped.append(f"• **{repo.split('/')[-1]}** {tags}")
    ranked = sorted(((repo, data["features"]) for repo, data in pairs if data["features"]), key=lambda kv: -len(kv[1]))
    for repo, feats in ranked[:8]:
        lines = [f"• {md_link(clean_title(i['title']), i['html_url'])}" for i in feats[:3]]
        if len(feats) > 3:
            lines.append(f"+{len(feats) - 3} more")
        fields.append({"name": repo.split("/")[-1], "value": "\n".join(lines), "inline": False})
    if not shipped and not fields:
        return None
    desc = []
    if shipped:
        desc.append("**Released**\n" + "\n".join(shipped))
    if len(ranked) > 8:
        desc.append(f"New features also landed in {', '.join(r.split('/')[-1] for r, _ in ranked[8:13])}"
                    + (f" +{len(ranked) - 13}" if len(ranked) > 13 else ""))
    if nightly:
        desc.append(f"_plus {plural(nightly, 'nightly/CI build')} (not listed)_")
    embed = {"title": title, "description": "\n\n".join(desc), "color": BLUE}
    if fields:
        embed["fields"] = fields
    return enforce_limits({"content": "", "embeds": [embed]})


def render_preview(payload: dict) -> str:
    """Human-readable approximation of how Discord will show a payload."""
    out = [payload.get("content", "")]
    for embed in payload.get("embeds", []):
        out.append(f"┃ [{embed.get('color', 0):06X}] **{embed.get('title', '')}**")
        for line in embed.get("description", "").splitlines():
            out.append("┃ " + line)
        for field in embed.get("fields", []):
            out.append(f"┃ __{field['name']}__")
            out.extend("┃ " + line for line in field["value"].splitlines())
        if embed.get("footer"):
            out.append("┃ " + embed["footer"]["text"])
    return "\n".join(out)


# ── Transport ───────────────────────────────────────────────────────────────

def send(channel: str, payload: dict | str):
    if isinstance(payload, str):
        payload = {"content": payload}
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    payload = enforce_limits(payload)
    if DRY_RUN:
        print(json.dumps({"channel": channel, "payload": payload}, ensure_ascii=False, indent=1))
        return
    token = os.environ["DISCORD_BOT_TOKEN"]
    http_json(f"{DISCORD}/channels/{channel}/messages", {"Authorization": f"Bot {token}"}, method="POST", data=payload)


def fetch_hive_status() -> dict | None:
    snapshot = os.environ.get("HIVE_STATUS_FILE")
    if snapshot:
        return json.loads(pathlib.Path(snapshot).read_text())
    url, token = os.environ.get("HIVE_DASHBOARD_URL"), os.environ.get("HIVE_DASHBOARD_TOKEN")
    if not (url and token):
        return None
    try:
        status = http_json(f"{url}/api/status", {"X-Hive-Internal": token}, timeout=90)
        try:
            status["breaker"] = http_json(f"{url}/api/breaker", {"X-Hive-Internal": token}, timeout=30)
        except RuntimeError:
            pass
        return status
    except RuntimeError as exc:
        print(f"hive status unavailable: {exc}", file=sys.stderr)
        return None


# ── Main ────────────────────────────────────────────────────────────────────

def gather(start: dt.datetime, end: dt.datetime, records: list[dict] | None, token_cache: dict) -> dict[str, dict]:
    if records is not None:
        return aggregate(records, start.timestamp(), end.timestamp())
    token = token_cache.setdefault("token", app_token())
    repos = token_cache.setdefault("repos", gh(f"/orgs/{OWNER}/repos?type=all&per_page=100&sort=full_name", token))
    data_by_repo = {}
    for repo in repos:
        try:
            data_by_repo[repo["full_name"]] = collect(repo["full_name"], start, token, end, repo.get("default_branch"))
        except RuntimeError as exc:
            print(f"skipping {repo['full_name']}: {exc}", file=sys.stderr)
    return data_by_repo


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("daily", "weekly"), required=True)
    parser.add_argument("--dry-run", action="store_true", help="print payload JSON instead of posting (also DRY_RUN=1)")
    parser.add_argument("--preview", action="store_true", help="with --dry-run: print a text rendering instead of JSON")
    parser.add_argument("--now", help="ISO timestamp to treat as 'now' (for re-rendering a past report)")
    args = parser.parse_args(argv)
    global DRY_RUN
    DRY_RUN = DRY_RUN or args.dry_run
    cfg = json.loads(CONFIG.read_text())
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    span = dt.timedelta(days=1 if args.kind == "daily" else 7)
    start, prev_start = now - span, now - 2 * span
    event_log = pathlib.Path(os.environ.get("GITHUB_EVENT_LOG", "/data/github-events.jsonl"))
    lookback = (prev_start - dt.timedelta(days=21)).timestamp()  # CI streaks need history before the window
    records = read_event_log(event_log, since=lookback) if event_log.exists() else None
    cache: dict = {}
    current = gather(start, now, records, cache)
    previous_data = gather(prev_start, start, records, cache) if records is not None else {}
    pairs = [(repo, data) for repo, data in current.items() if active(data)]
    pairs.sort(key=lambda pair: (-activity_score(pair[1]), pair[0].lower()))
    prev_pairs = [(r, d) for r, d in previous_data.items() if active(d)]
    hive = fetch_hive_status()
    s, e = start.timestamp(), now.timestamp()

    configured = {p["repo"].lower(): p for p in cfg.get("projects", [])}
    sent = json.loads(STATE.read_text()) if STATE.exists() else {"sent": []}
    sent.setdefault("history", {})
    period = now.strftime("%Y-%m-%d") if args.kind == "daily" else now.strftime("%G-W%V")
    prev_period = (now - span).strftime("%Y-%m-%d") if args.kind == "daily" else (now - span).strftime("%G-W%V")
    prev_stats = (summarise_period(prev_pairs, prev_start.timestamp(), s) if prev_pairs
                  else sent["history"].get(f"{args.kind}:{prev_period}"))
    label = now.astimezone(report_tz()).strftime("%a %d %b") if args.kind == "daily" else now.strftime("week %V")
    outputs: list[tuple[str, dict]] = []

    def emit(key: str, channel: str | None, payload: dict | None):
        if not channel or not payload or (key in sent["sent"] and not DRY_RUN):
            return
        if DRY_RUN and args.preview:
            print(f"── channel {channel} ({key})\n{render_preview(payload)}\n")
        else:
            send(channel, payload)
        outputs.append((key, payload))
        sent["sent"].append(key)

    if args.kind == "daily" and cfg.get("daily_digest_channel_id"):
        payload = build_digest(f"TunaOS daily · {label}", pairs, start=s, end=e, previous=prev_stats, hive_status=hive,
                               kind="daily", url=HIVE_URL)
        emit(f"daily:digest:{period}", cfg["daily_digest_channel_id"], payload)
        sent["history"][f"daily:{period}"] = payload["_stats"]
    if args.kind == "weekly":
        for repo, data in pairs:
            project = configured.get(repo.lower())
            if not project:
                continue
            prev_repo = [(r, d) for r, d in prev_pairs if r.lower() == repo.lower()]
            prev_repo_stats = summarise_period(prev_repo, prev_start.timestamp(), s) if prev_repo else None
            payload = build_digest(f"{project['name']} · {label}", [(repo, data)], start=s, end=e, previous=prev_repo_stats,
                                   kind="weekly", repo_scoped=True, url=f"https://github.com/{repo}")
            if data["merged"] or data["releases"] or payload["embeds"][0]["color"] != GREEN:
                emit(f"weekly:project:{period}:{project['channel_id']}", project["channel_id"], payload)
        if pairs:
            payload = build_digest(f"TunaOS weekly · {label}", pairs, start=s, end=e, previous=prev_stats, hive_status=hive,
                                   kind="weekly", url=HIVE_URL)
            emit(f"weekly:general:{period}", cfg.get("general_channel_id"), payload)
            sent["history"][f"weekly:{period}"] = payload["_stats"]
        emit(f"weekly:releases:{period}", cfg.get("releases_channel_id"), build_releases_report(pairs))
        emit(f"weekly:ci_channel_id:{period}", cfg.get("ci_channel_id"), build_ci_report(f"🔧 CI health · {label}", pairs, start=s, end=e))
        emit(f"weekly:security_channel_id:{period}", cfg.get("security_channel_id"),
             build_security_report(f"🛡️ Security · {label}", pairs))

    if DRY_RUN:
        return outputs
    sent["sent"] = sent["sent"][-500:]
    sent["history"] = dict(sorted(sent["history"].items())[-60:])
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sent, indent=2) + "\n")
    tmp.replace(STATE)
    return outputs


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"discord report failed: {exc}", file=sys.stderr)
        sys.exit(1)
