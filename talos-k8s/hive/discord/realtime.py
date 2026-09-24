#!/usr/bin/env python3
"""Hive ops bridge: GitHub webhook → event log, and a *quiet* Discord feed.

Two jobs:
  1. Receive GitHub org webhooks on :8080/api/discord-reports/github and append
     a compact record to GITHUB_EVENT_LOG. report.py builds the daily/weekly
     digests from that log, so this part must keep running even when Discord
     posting is off.
  2. Optionally (DISCORD_REALTIME_POSTS=true) post to #hive-ops — but only for
     events that need a human soon. Everything else (PR opened/merged, agent
     started/finished, bead churn, governor mode flips) is left to the digest.

Posted immediately (batched over REALTIME_BATCH_SECONDS, one embed per batch):
  🔴 a build/release/publish workflow on the default branch goes red
  🟢 ...and when it recovers
  🔴 an agent needs a fresh login · model budget exhausted · critical hive alert
  🟠 an issue/PR gets the `needs-human` label · a security issue is opened
  🔵 a real (non-nightly, non-draft) release is published
  ⚠️ the Hive SSE feed has been down for 5 minutes (and 🟢 when it's back)

DRY_RUN=1 prints payloads instead of posting.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import json
import os
import pathlib
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DASHBOARD = os.environ.get("HIVE_DASHBOARD_URL", "http://hive:3002")
DASHBOARD_TOKEN = os.environ.get("HIVE_DASHBOARD_TOKEN", "")
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL = os.environ.get("DISCORD_HIVE_OPS_CHANNEL", "")
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
EVENT_LOG = pathlib.Path(os.environ.get("GITHUB_EVENT_LOG", "/data/github-events.jsonl"))
POST_REALTIME = os.environ.get("DISCORD_REALTIME_POSTS", "false").lower() == "true"
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
BATCH_SECONDS = float(os.environ.get("REALTIME_BATCH_SECONDS", "60"))
SLOW_BATCH_SECONDS = float(os.environ.get("REALTIME_SLOW_BATCH_SECONDS", str(3 * 3600)))
MAX_POSTS_PER_HOUR = int(os.environ.get("REALTIME_MAX_POSTS_PER_HOUR", "6"))
CI_ALL_WORKFLOWS = os.environ.get("REALTIME_CI_ALL_WORKFLOWS", "false").lower() == "true"
CI_FAIL_STREAK = max(1, int(os.environ.get("REALTIME_CI_FAIL_STREAK", "2")))  # debounce flaky runs
CI_COOLDOWN = float(os.environ.get("REALTIME_CI_COOLDOWN_SECONDS", str(12 * 3600)))  # don't re-alert a flapping workflow
BEAD_POLL = os.environ.get("REALTIME_BEAD_POLL", "false").lower() == "true"
DISCONNECT_GRACE = float(os.environ.get("REALTIME_DISCONNECT_GRACE_SECONDS", "300"))
HIVE_URL = os.environ.get("HIVE_PUBLIC_URL", "https://hive.tunaos.org/")

RED, AMBER, GREEN, BLUE = 0xE5484D, 0xF5A524, 0x30A46C, 0x3E63DD
SEVERITY = {"red": 0, "amber": 1, "blue": 2, "green": 3}
ICON = {"red": "🔴", "amber": "🟠", "blue": "🔵", "green": "🟢"}
COLOUR = {"red": RED, "amber": AMBER, "blue": BLUE, "green": GREEN}
FAILED = {"failure", "timed_out", "startup_failure"}
IMPORTANT_WORKFLOW = re.compile(r"build|release|publish|deploy|nightly|image|iso|package", re.I)
DATE_TAG = re.compile(r"(?:19|20)\d{2}[.-]?\d{2}[.-]?\d{2}")
HEX_TAG = re.compile(r"\b[0-9a-f]{10,40}\b")
SECURITY_WORDS = ("security", "vulnerability", "cve-", "exploit")

_event_log_lock = threading.Lock()
_pending: list[dict] = []
_pending_lock = threading.Lock()
_flush_timer: threading.Timer | None = None
_post_times: collections.deque = collections.deque()
_seen_deliveries: list[str] = []
_seen_lock = threading.Lock()
_ci_state: dict[tuple, dict] = {}
_ci_lock = threading.Lock()


# ── Formatting (pure) ───────────────────────────────────────────────────────

def notice(level: str, text: str, key: str = "") -> dict:
    return {"level": level, "text": text, "key": key or text}


def link_text(label: str, url: str) -> str:
    label = str(label).replace("[", "(").replace("]", ")")[:150]
    return f"[{label}]({url})" if url else label


def render_batch(notices: list[dict], suppressed: int = 0) -> dict | None:
    """One embed per batch; colour = worst level; reds first."""
    unique = list({n["key"]: n for n in notices}.values())
    if not unique:
        return None
    unique.sort(key=lambda n: SEVERITY[n["level"]])
    worst = unique[0]["level"]
    lines, used = [], 0
    for index, n in enumerate(unique):
        line = f"{ICON[n['level']]} {n['text']}"
        if used + len(line) + 1 > 3500:
            lines.append(f"+{len(unique) - index} more")
            break
        lines.append(line)
        used += len(line) + 1
    if suppressed:
        lines.append(f"_+{suppressed} lower-priority events held back by the rate limit — see the daily digest_")
    reds = sum(1 for n in unique if n["level"] == "red")
    title = ("Needs attention" if reds else "Hive update") if len(unique) > 1 else None
    embed = {"description": "\n".join(lines), "color": COLOUR[worst]}
    if title:
        embed["title"] = title
    return {"content": "", "embeds": [embed], "allowed_mentions": {"parse": []}}


def is_real_release(release: dict) -> bool:
    tag, name = release.get("tag_name", "") or "", release.get("name", "") or ""
    return not (release.get("draft") or release.get("prerelease") or DATE_TAG.search(tag) or DATE_TAG.search(name)
                or HEX_TAG.search(tag) or HEX_TAG.search(name) or "latest" in tag.lower())


def default_branch_run(run: dict, payload: dict) -> bool:
    branch = run.get("head_branch")
    default = (payload.get("repository") or {}).get("default_branch")
    if run.get("event") in {"pull_request", "pull_request_target", "merge_group"}:
        return False
    return bool(branch) and branch == (default or branch)


def classify_github(event: str, payload: dict, ci_state: dict | None = None, now: float | None = None) -> list[dict]:
    """GitHub webhook → notices worth posting now. Mutates ci_state."""
    ci_state = _ci_state if ci_state is None else ci_state
    now = time.time() if now is None else now
    action = payload.get("action", "")
    repo = (payload.get("repository") or {}).get("full_name", "")
    short = repo.split("/")[-1]
    out: list[dict] = []
    if event == "workflow_run" and action == "completed":
        run = payload.get("workflow_run") or {}
        conclusion, name = run.get("conclusion"), run.get("name", "workflow")
        if conclusion not in FAILED and conclusion != "success":
            return out
        if not default_branch_run(run, payload):
            return out
        key = (repo, name)
        with _ci_lock:
            st = ci_state.setdefault(key, {"streak": 0, "alerted": False, "alerted_at": None, "known": False})
            was_known = st["known"]
            st["known"] = True
            if conclusion in FAILED:
                st["streak"] += 1
                fire = (was_known and st["streak"] == CI_FAIL_STREAK and not st["alerted"]
                        and (st["alerted_at"] is None or now - st["alerted_at"] > CI_COOLDOWN))
                if fire:
                    st["alerted"], st["alerted_at"] = True, now
                recovered = False
            else:
                recovered = st["alerted"]
                st["streak"], st["alerted"] = 0, False
                fire = False
        watched = CI_ALL_WORKFLOWS or bool(IMPORTANT_WORKFLOW.search(name))
        if not watched:
            return out
        if fire:
            runs = f" ({CI_FAIL_STREAK} runs in a row)" if CI_FAIL_STREAK > 1 else ""
            out.append(notice("red", f"**{short}** {link_text(name, run.get('html_url', ''))} is failing on `{run.get('head_branch')}`{runs}",
                              f"ci:{repo}:{name}"))
        elif recovered:
            out.append(notice("green", f"**{short}** {link_text(name, run.get('html_url', ''))} is green again", f"ci:{repo}:{name}"))
    elif event == "release" and action == "published":
        release = payload.get("release") or {}
        if is_real_release(release):
            out.append(notice("blue", f"**{short}** released {link_text(release.get('tag_name', ''), release.get('html_url', ''))}"
                                      + (f" — {release['name']}" if release.get("name") and release.get("name") != release.get("tag_name") else "")))
    elif event in {"issues", "pull_request"}:
        item = payload.get("issue" if event == "issues" else "pull_request") or {}
        kind = "issue" if event == "issues" else "PR"
        ref = link_text(f"{short}#{item.get('number')} — {item.get('title', '')}", item.get("html_url", ""))
        if action == "labeled" and (payload.get("label") or {}).get("name") == "needs-human":
            out.append(notice("amber", f"{kind} needs you: {ref}", f"needs-human:{repo}#{item.get('number')}"))
        elif event == "issues" and action == "opened":
            text = (item.get("title", "") + " " + " ".join(l.get("name", "") for l in item.get("labels", []))).lower()
            if any(word in text for word in SECURITY_WORDS) and not str(item.get("title", "")).startswith("["):
                out.append(notice("amber", f"Security issue opened: {ref}", f"sec:{repo}#{item.get('number')}"))
    return out


def classify_status(previous: dict | None, current: dict) -> list[dict]:
    """Hive SSE status snapshot diff → notices. Agent busy/idle churn is ignored."""
    if previous is None:
        return []
    out: list[dict] = []
    old_agents = {a.get("name"): a for a in previous.get("agents", [])}
    for agent in current.get("agents", []):
        old = old_agents.get(agent.get("name"))
        if old is not None and agent.get("needsLogin") and not old.get("needsLogin"):
            out.append(notice("red", f"Agent **{agent.get('name')}** needs you to log in again — {link_text('open the hive', HIVE_URL)}",
                              f"login:{agent.get('name')}"))
    old_budget = (previous.get("budget") or {}).get("BUDGET_EXHAUSTED")
    new_budget = (current.get("budget") or {}).get("BUDGET_EXHAUSTED")
    if new_budget and not old_budget:
        out.append(notice("red", "Model budget **exhausted** — agents stall until it resets", "budget"))
    elif old_budget and not new_budget:
        out.append(notice("green", "Model budget available again", "budget"))
    old_alerts = {a.get("id") for a in previous.get("systemAlerts") or []}
    for alert in current.get("systemAlerts") or []:
        if alert.get("id") not in old_alerts and alert.get("severity") in {"critical", "error"}:
            out.append(notice("red", str(alert.get("message", alert.get("id")))[:300], f"alert:{alert.get('id')}"))
    return out


# ── Transport ───────────────────────────────────────────────────────────────

def discord(payload: dict | str):
    if isinstance(payload, str):
        payload = {"content": payload[:1990], "allowed_mentions": {"parse": []}}
    if DRY_RUN:
        print(json.dumps({"channel": CHANNEL, "payload": payload}, ensure_ascii=False), flush=True)
        return
    if not POST_REALTIME:
        return
    body = json.dumps(payload).encode()
    for attempt in range(4):
        try:
            with urlopen(Request(f"https://discord.com/api/v10/channels/{CHANNEL}/messages", data=body,
                                 headers={"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json",
                                          "User-Agent": "TunaOS-Hive-Ops/2.0"}, method="POST"), timeout=20) as response:
                response.read()
                return
        except HTTPError as exc:
            if exc.code == 429:
                retry = 2.0
                try:
                    retry = min(30.0, float(json.loads(exc.read()).get("retry_after", 2)))
                except Exception:
                    pass
                time.sleep(retry)
                continue
            raise
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def _allowed_now(now: float) -> bool:
    while _post_times and now - _post_times[0] > 3600:
        _post_times.popleft()
    return len(_post_times) < MAX_POSTS_PER_HOUR


def flush_events():
    global _flush_timer
    with _pending_lock:
        batch = list(_pending)
        _pending.clear()
        _flush_timer = None
    if not batch:
        return
    now = time.time()
    suppressed = 0
    if not _allowed_now(now):
        # Over the hourly cap: only reds get through; the rest is in the digest.
        suppressed = sum(1 for n in batch if n["level"] != "red")
        batch = [n for n in batch if n["level"] == "red"]
        if not batch:
            print(f"rate limit: dropped {suppressed} non-urgent notices", flush=True)
            return
    payload = render_batch(batch, suppressed)
    if payload:
        _post_times.append(now)
        try:
            discord(payload)
        except Exception as exc:
            print(f"discord post failed: {exc}", flush=True)


def flush_delay(notices: list[dict]) -> float:
    """Reds and releases go out after BATCH_SECONDS. Everything else
    (needs-human, security issue, blocked bead, "green again") waits for the
    slow lane, or rides along with the next red, so bursts become one message."""
    return BATCH_SECONDS if any(n["level"] in {"red", "blue"} for n in notices) else SLOW_BATCH_SECONDS


_flush_due = 0.0


def queue(notices: list[dict]):
    global _flush_timer, _flush_due
    if not notices:
        return
    with _pending_lock:
        _pending.extend(notices)
        delay = flush_delay(_pending)
        due = time.time() + delay
        if _flush_timer is not None and due < _flush_due:
            _flush_timer.cancel()
            _flush_timer = None
        if _flush_timer is None:
            _flush_due = due
            _flush_timer = threading.Timer(delay, flush_events)
            _flush_timer.daemon = True
            _flush_timer.start()


# ── GitHub webhook → event log ──────────────────────────────────────────────

def event_record(event: str, payload: dict) -> dict | None:
    """Compact record for report.py. Returns None for events nobody reads."""
    action = payload.get("action", "")
    repository = payload.get("repository") or {}
    record = {"ts": time.time(), "event": event, "action": action, "repo": repository.get("full_name", ""),
              "default_branch": repository.get("default_branch")}
    if event in {"issues", "pull_request"}:
        item = payload.get("issue" if event == "issues" else "pull_request") or {}
        record.update({"number": item.get("number"), "title": item.get("title", ""), "url": item.get("html_url", ""),
                       "merged": item.get("merged", False), "merged_at": item.get("merged_at"), "created_at": item.get("created_at"),
                       "state": item.get("state"), "author": (item.get("user") or {}).get("login"),
                       "labels": [x.get("name", "") for x in item.get("labels", [])]})
    elif event == "release":
        release = payload.get("release") or {}
        record.update({"tag_name": release.get("tag_name", ""), "title": release.get("name", ""), "url": release.get("html_url", ""),
                       "published_at": release.get("published_at"), "draft": release.get("draft", False),
                       "prerelease": release.get("prerelease", False)})
    elif event == "push":
        record["ref"] = payload.get("ref", "")
        record["commits"] = [{"sha": x.get("id", ""), "message": (x.get("message", "").splitlines() or [""])[0], "url": x.get("url", "")}
                             for x in payload.get("commits", [])]
    elif event == "workflow_run":
        if action != "completed":
            return None  # requested/in_progress were ~70% of the log and unused
        run = payload.get("workflow_run") or {}
        record.update({"name": run.get("name", ""), "conclusion": run.get("conclusion", ""), "url": run.get("html_url", ""),
                       "branch": run.get("head_branch"), "trigger": run.get("event")})
    return record


def persist_github_event(event: str, payload: dict):
    record = event_record(event, payload)
    if record is None:
        return
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _event_log_lock:
        with EVENT_LOG.open("a") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")


def seed_ci_state(path: pathlib.Path = EVENT_LOG, max_bytes: int = 8_000_000):
    """Learn each workflow's last default-branch conclusion from the log tail."""
    if not path.exists():
        return
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - max_bytes))
        for raw in stream:
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if record.get("event") != "workflow_run" or record.get("action") != "completed":
                continue
            if record.get("trigger") in {"pull_request", "pull_request_target"}:
                continue
            if record.get("branch") and record.get("default_branch") and record["branch"] != record["default_branch"]:
                continue
            conclusion = record.get("conclusion")
            if conclusion not in FAILED and conclusion != "success":
                continue
            st = _ci_state.setdefault((record.get("repo"), record.get("name")),
                                      {"streak": 0, "alerted": False, "alerted_at": None, "known": True})
            # A workflow already red when we start was either alerted before a
            # restart or is long-standing; the digest covers it, so don't re-fire.
            st["streak"] = st["streak"] + 1 if conclusion in FAILED else 0
            st["alerted"] = st["streak"] >= CI_FAIL_STREAK


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/discord-reports/github":
            self.send_response(404)
            self.end_headers()
            return
        if not WEBHOOK_SECRET:  # never accept unsigned deliveries
            self.send_response(503)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        signature = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            print(f"webhook signature mismatch: header_present={bool(signature)} body_bytes={len(body)}", flush=True)
            self.send_response(401)
            self.end_headers()
            return
        delivery = self.headers.get("X-GitHub-Delivery", "")
        with _seen_lock:
            if delivery and delivery in _seen_deliveries:
                self.send_response(204)
                self.end_headers()
                return
            if delivery:
                _seen_deliveries.append(delivery)
                del _seen_deliveries[:-1000]
        try:
            event = self.headers.get("X-GitHub-Event", "")
            payload = json.loads(body)
            persist_github_event(event, payload)
            queue(classify_github(event, payload))
        except (ValueError, TypeError):
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        return


def webhook_server():
    ThreadingHTTPServer(("0.0.0.0", 8080), WebhookHandler).serve_forever()


# ── Hive SSE + beads ────────────────────────────────────────────────────────

def dashboard_json(path: str, timeout: int = 60):
    with urlopen(Request(f"{DASHBOARD}{path}", headers={"X-Hive-Internal": DASHBOARD_TOKEN}), timeout=timeout) as response:
        return json.loads(response.read())


def bead_link(bead: dict) -> str:
    ref = bead.get("external_ref", "")
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    if "/" in ref and "#" in ref:
        repo, number = ref.rsplit("#", 1)
        return f"https://github.com/{repo}/issues/{number}"
    return HIVE_URL


def bead_loop():
    """Only a bead becoming *blocked* is worth a ping; everything else is churn."""
    previous: dict[str, str] = {}
    while True:
        try:
            payload = dashboard_json("/api/beads", timeout=90)
            current = {}
            for agent, beads in payload.items():
                for bead in beads or []:
                    bead_id = str(bead.get("id", ""))
                    if not bead_id:
                        continue
                    status = str(bead.get("status", ""))
                    current[bead_id] = status
                    if previous and status == "blocked" and previous.get(bead_id) != "blocked":
                        queue([notice("amber", f"**{agent}** is blocked on {link_text(bead.get('title', bead_id), bead_link(bead))}",
                                      f"bead:{bead_id}")])
            previous = current
        except Exception as exc:
            print(f"bead poll: {exc}", flush=True)
        time.sleep(120)


def connect():
    response = urlopen(Request(f"{DASHBOARD}/api/events", headers={"X-Hive-Internal": DASHBOARD_TOKEN, "Accept": "text/event-stream",
                                                                    "Cache-Control": "no-cache"}), timeout=None)
    if response.status != 200:
        response.close()
        raise RuntimeError(f"SSE HTTP {response.status}")
    return response


def main():
    missing = [name for name, value in (("DISCORD_BOT_TOKEN", DISCORD_TOKEN), ("DISCORD_HIVE_OPS_CHANNEL", CHANNEL),
                                        ("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET), ("HIVE_DASHBOARD_TOKEN", DASHBOARD_TOKEN)) if not value]
    if missing and not DRY_RUN:
        raise SystemExit(f"missing required env: {', '.join(missing)}")
    seed_ci_state()
    threading.Thread(target=webhook_server, daemon=True).start()
    if BEAD_POLL:
        threading.Thread(target=bead_loop, daemon=True).start()
    previous = None
    delay = 5
    disconnect_since = None
    disconnect_notified = False
    while True:
        response = None
        try:
            response = connect()
            delay = 5
            if disconnect_notified:
                queue([notice("green", "Hive ops feed restored", "sse")])
            disconnect_since = None
            disconnect_notified = False
            data_lines = []
            for raw in response:
                line = raw.decode(errors="replace").rstrip("\r\n")
                if line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif not line and data_lines:
                    payload = "".join(data_lines)
                    data_lines = []
                    try:
                        current = json.loads(payload)
                        queue(classify_status(previous, current))
                        previous = current
                    except (ValueError, KeyError, AttributeError):
                        pass
            raise RuntimeError("SSE ended")
        except Exception as exc:
            now = time.time()
            if disconnect_since is None:
                disconnect_since = now
            if not disconnect_notified and now - disconnect_since >= DISCONNECT_GRACE:
                queue([notice("amber", f"Hive ops feed disconnected for {int(DISCONNECT_GRACE // 60)}+ min — reconnecting", "sse")])
                disconnect_notified = True
            print(f"SSE bridge: {exc}", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 60)
        finally:
            if response:
                response.close()


if __name__ == "__main__":
    main()
