"""Unit tests for the in-cluster hive-ops scripts (talos-k8s/hive/ops/scripts).

Pure decision/parsing helpers are exercised by sourcing hive-lib.sh (or, for
hive-rotate.sh, which runs on source, by extracting single functions) in bash.
The hive_open test drives the exec path against a stub kubectl on PATH, the
same pattern as test_hive_peak.py.
"""
import json
import subprocess
import time

import pytest

from conftest import REPO, write_stub

OPS = REPO / "talos-k8s/hive/ops/scripts"
LIB = OPS / "hive-lib.sh"
ROTATE = OPS / "hive-rotate.sh"


def lib(snippet, stdin=None, env=None):
    r = subprocess.run(["bash", "-c", f'. "{LIB}"; {snippet}'], input=stdin,
                       capture_output=True, text=True, timeout=30, env=env)
    return r


def out(snippet, stdin=None):
    return lib(snippet, stdin).stdout.strip()


def rotate_fn(names, snippet, stdin=None):
    """Source only the named functions out of hive-rotate.sh."""
    extract = "; ".join(
        f'source <(sed -n "/^{n}() {{/,/^}}/p" "{ROTATE}")' for n in names)
    r = subprocess.run(["bash", "-c", f'. "{LIB}"; META_MODEL=muse-x; {extract}; {snippet}'],
                       input=stdin, capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


# ── provider / effort / rungs ─────────────────────────────────────────────

@pytest.mark.parametrize("backend,model,want", [
    ("agy", "gemini-3.8-flash-high", "google"),
    ("claude", "claude-fable-5-1", "anthropic"),
    ("codex", "gpt-5.6-luna", "openai"),
    ("agy", "gpt-5.6-luna", "openai"),          # model sniffing wins over the CLI
    ("copilot", "claude-fable-5", "github"),     # CLI-tied auth wins over the model
    ("muse", "muse-spark-1.3-contributor", "meta"),
    ("pi", "", "unknown"),                       # deepseek default dropped
    ("pi", "kiro-api-key/claude-sonnet-5", "kiro"),  # prefix beats model sniffing
    ("pi", "kiro-api-key/gpt-5-6-sol", "kiro"),
    ("pi", "deepseek-v4-flash", "deepseek"),     # legacy, still recognised
    ("weird", "", "unknown"),
])
def test_provider_of(backend, model, want):
    assert out(f"hive_provider_of {backend} {model}") == want


@pytest.mark.parametrize("backend,model,recorded,want", [
    ("agy", "gemini-3.8-flash-high", "", "high"),   # never set = v5 default low
    ("agy", "gemini-3.8-flash-high", "high", ""),
    ("agy", "gemini-3.6-flash-low", "", ""),        # default already matches
    ("agy", "gemini-3.8-flash-low", "high", "low"), # demoted after a high rung
    ("agy", "gemini-3.7-flash-medium", "low", "medium"),
    ("agy", "gemini-3.1-pro", "", ""),              # unsuffixed: nothing to match
    ("claude", "claude-opus-5-high", "", ""),       # only agy has the conflict
])
def test_effort_change(backend, model, recorded, want):
    assert out(f'effort_change {backend} {model} "{recorded}"') == want


@pytest.mark.parametrize("model,want", [
    ("claude-fable-5-1", "claude-sonnet-5"),
    ("claude-opus-5", "claude-sonnet-5"),
    ("gemini-3.8-flash-high", "gemini-3.8-flash-low"),
    ("gpt-5.6-sol", "gpt-5.6-luna"),
    ("claude-sonnet-5", ""),
    ("gemini-3.6-flash-low", ""),
    ("kiro-api-key/claude-opus-5", "kiro-api-key/claude-sonnet-5"),
    ("kiro-api-key/gpt-5-6-sol", "kiro-api-key/gpt-5-6-luna"),
    ("kiro-api-key/claude-sonnet-5", "kiro-api-key/claude-haiku-4-5:low"),   # 2nd notch
    ("kiro-api-key/claude-opus-5:high", "kiro-api-key/claude-sonnet-5:high"),
    ("kiro-api-key/gpt-5-6-sol:high", "kiro-api-key/gpt-5-6-luna:high"),
    ("kiro-api-key/claude-sonnet-5:medium", "kiro-api-key/claude-haiku-4-5:low"),
    ("kiro-api-key/gpt-5-6-luna:high", "kiro-api-key/claude-haiku-4-5:low"),
    ("kiro-api-key/claude-haiku-4-5:low", ""),                              # the floor
])
def test_rung_down(model, want):
    assert out(f"rung_down {model}") == want


def test_pace_demoted_from(tmp_path):
    f = tmp_path / "pace-demoted"
    f.write_text("hive-reef/sec-check|claude|claude-opus-5\n"
                 "hive/strategist|claude|claude-fable-5-1\n"
                 "hive-reef/sec-check|claude|claude-fable-5-1\n")
    # latest row wins, and the current model must be exactly its rung_down
    assert out(f'pace_demoted_from "{f}" hive-reef sec-check claude-sonnet-5') == "claude|claude-fable-5-1"
    assert out(f'pace_demoted_from "{f}" hive strategist claude-sonnet-5') == "claude|claude-fable-5-1"
    assert out(f'pace_demoted_from "{f}" hive strategist claude-opus-5') == ""
    assert out(f'pace_demoted_from "{f}" hive-hanthor sec-check claude-sonnet-5') == ""
    assert out(f'pace_demoted_from "{tmp_path}/missing" hive x y') == ""


# ── watchdog ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n,secs", [(0, 0), (1, 300), (2, 600), (3, 1200),
                                    (5, 4800), (6, 7200), (12, 7200)])
def test_watchdog_backoff(n, secs):
    assert out(f"watchdog_backoff_s {n}") == str(secs)


AGY_WIZARD = """\
    tokyo night                  │  6 +     fmt.Printf("Hello, %s!\\n", name)   │
                                 │   ★ accent: highlighted text                │
                                 ╰─────────────────────────────────────────────╯
    [Next]
  ↑/↓ Navigate · enter Confirm
"""
MUSE_TRUST = """\
Do you trust this workspace?
Workspace: /data/agents/outreach
Error: failed to save trust decision: failed to read trust store at /data/home/agents/outreach/.config/muse/trust.json: Permission denied (os error 13)
> 1  Trust and continue
  2  Quit
Use Up/Down or 1/2, then Enter. Esc quits.
"""
COPILOT_LOGIN = "● Welcome to GitHub Copilot CLI\n\n Please use /login to sign in to use Copilot\n"
LAUNCH_LINE = ("-bash: /data/home/agents/reviewer/.cargo/env: No such file or directory\n"
               "hive-reviewer@hive-6f77b74574-qwtj9:/data/agents/reviewer$ ^C\n"
               "hive-reviewer@hive-6f77b74574-qwtj9:/data/agents/reviewer$ HIVE_AGENT='reviewer' "
               "/usr/local/bin/copilot --model claude-fable-5 --allow-all\n")
BARE_PROMPT = "some output\nhive-guide@hive-0:/data/agents/guide$ \n\n"
AGY_WORKING = """\
  ⚙ tool: run_shell_command gh pr view 12 --repo tuna-os/docs
  ◉ Working (32s · esc to interrupt)
"""
PROSE = ("  > The dashboard says: please sign in to use the dashboard first.\n"
         "  mail me@example.com: it costs $5 per month\n")


@pytest.mark.parametrize("pane,want", [
    (AGY_WIZARD, "wizard"),
    (MUSE_TRUST, "wizard"),
    (COPILOT_LOGIN, "auth"),
    ("Login expired · Please run /login\n", "auth"),
    (LAUNCH_LINE, "shell"),
    (BARE_PROMPT, "shell"),
    ("", "empty"),
    ("\n   \n", "empty"),
    (AGY_WORKING, "ready"),
    (PROSE, "ready"),      # loose English must never read as auth or a shell
])
def test_pane_classify(pane, want):
    assert out("pane_classify_text", stdin=pane) == want


def test_pane_stalled(tmp_path):
    f = tmp_path / "pane"
    t0 = 1_000_000

    def stalled(busy, text, now):
        return lib(f'pane_stalled "{f}" {busy} "{text}" {now} 60').returncode == 0

    assert not stalled("working", "A", t0)             # first sight: record only
    assert not stalled("working", "A", t0 + 59 * 60)
    assert stalled("working", "A", t0 + 60 * 60)       # an hour of identical bytes
    assert not stalled("working", "B", t0 + 61 * 60)   # any change resets the clock
    assert not stalled("working", "B", t0 + 100 * 60)
    assert not stalled("idle", "B", t0 + 200 * 60)     # an idle agent is waiting, not hung
    assert not f.exists()


@pytest.mark.parametrize("value,want", [
    ("37% used resets=2026-09-30T03:17:08Z", "37 resets=2026-09-30T03:17:08Z"),
    ("100% used balance=-1.23", "100 balance=-1.23"),
    ("unknown no-usage-api", "-1 no-usage-api"),
    ("unknown", "-1 unpublished"),
    ("garbage", "-1 unpublished"),
])
def test_published_to_probe(value, want):
    assert out(f'published_to_probe "{value}"') == want


# ── rotate's probe parsers ────────────────────────────────────────────────

def test_parse_openai_weekly_window_and_reset():
    body = "\n".join([
        json.dumps({"id": 0, "result": {}}),
        json.dumps({"id": 2, "result": {"rateLimits": {
            "primary": {"usedPercent": 100, "windowDurationMins": 10080, "resetsAt": 1790410518},
            "secondary": None}}}),
    ])
    got = rotate_fn(["parse_probe_openai"], "parse_probe_openai", stdin=body)
    assert got == "100 weekly=100% resets=2026-09-26T08:15:18Z"


def test_parse_openai_takes_worse_window():
    body = json.dumps({"id": 2, "result": {"rateLimits": {
        "primary": {"usedPercent": 40, "windowDurationMins": 300},
        "secondary": {"usedPercent": 90, "windowDurationMins": 10080, "resetsAt": 1790410518}}}})
    got = rotate_fn(["parse_probe_openai"], "parse_probe_openai", stdin=body)
    assert got.startswith("90 5h=40% weekly=90% resets=")


def test_parse_openai_no_answer_is_unknown():
    assert rotate_fn(["parse_probe_openai"], "parse_probe_openai",
                     stdin='{"id":0,"result":{}}') == "-1 unparsed"


def test_parse_anthropic_ignores_model_scoped_caps(tmp_path):
    lim = tmp_path / "limits.json"
    body = json.dumps({"limits": [
        {"percent": 16, "resets_at": "2026-09-24T17:40:00Z"},
        {"percent": 21, "resets_at": "2026-09-30T23:00:00Z"},
        {"percent": 100, "resets_at": "2026-09-30T23:00:00Z",
         "scope": {"model": {"display_name": "Fable"}}}]})
    got = rotate_fn(["parse_probe_anthropic"], f'parse_probe_anthropic "{lim}"', stdin=body)
    assert got == "21 resets=2026-09-30T23:00:00Z capped-models=Fable"
    assert [x["percent"] for x in json.loads(lim.read_text())] == [16, 21]


def test_parse_anthropic_rate_limit_keeps_previous_limits(tmp_path):
    lim = tmp_path / "limits.json"
    lim.write_text('[{"slot":"slot0","percent":5}]')
    got = rotate_fn(["parse_probe_anthropic"], f'parse_probe_anthropic "{lim}"',
                    stdin='{"type":"error","error":{"type":"rate_limit_error"}}')
    assert got == "-1 rate-limited"
    assert "percent" in lim.read_text()   # a 429 must not blank the pacer's input


def test_parse_anthropic_missing_token_is_exhaustion():
    got = rotate_fn(["parse_probe_anthropic"], "parse_probe_anthropic", stdin="-1 no-token\n")
    assert got.startswith("100 no-credential")


KIRO_USAGE = {
    "daysUntilReset": 0, "limits": [], "nextDateReset": 1.7908128E9,
    "overageConfiguration": {"overageStatus": "DISABLED"},
    "usageBreakdownList": [{"resourceType": "CREDIT", "currentUsageWithPrecision": 6.34,
                            "usageLimitWithPrecision": 10000.0, "nextDateReset": 1.7908128E9}]}


@pytest.mark.parametrize("body,want", [
    (json.dumps(KIRO_USAGE), "0 credits=6.34/10000 resets=2026-10-01T00:00:00Z"),
    (json.dumps({**KIRO_USAGE, "usageBreakdownList": [
        {**KIRO_USAGE["usageBreakdownList"][0], "currentUsageWithPrecision": 9612.5}]}),
     "96 credits=9612.5/10000 resets=2026-10-01T00:00:00Z"),
    (json.dumps({**KIRO_USAGE, "overageConfiguration": {"overageStatus": "ENABLED"}, "usageBreakdownList": [
        {**KIRO_USAGE["usageBreakdownList"][0], "currentUsageWithPrecision": 10400}]}),
     "100 credits=10400/10000 resets=2026-10-01T00:00:00Z overage=ENABLED"),
    ('{"__type":"com.amazon.kiro.runtimeservice#AccessDeniedException","message":"The bearer token included in the request is invalid."}',
     "100 key-rejected"),
    ("KIRO-KEY-MISSING\n", "-1 no-key (KIRO_API_KEY not in the hive pod env)"),
    ("curl: (28) timeout", "-1 unparsed"),
])
def test_parse_kiro(body, want):
    assert rotate_fn(["parse_probe_kiro"], "parse_probe_kiro", stdin=body) == want


@pytest.mark.parametrize("model,want", [
    ("kiro-api-key/claude-sonnet-5:medium", "kiro-api-key%2Fclaude-sonnet-5:medium"),
    ("gemini-3.8-flash-low", "gemini-3.8-flash-low"),
])
def test_model_path(model, want):
    assert out(f"hive_model_path {model}") == want


def test_parse_google_uses_lowest_gemini_remaining():
    body = ("Gemini Models          Weekly Limit Remaining     54%   2026-09-30T03:17:08Z\n"
            "Gemini Models          Five Hour Limit Remaining  64%   2026-09-24T19:17:07Z\n"
            "Claude and GPT models  Weekly Limit Remaining     3%    2026-09-25T01:15:02Z\n")
    assert rotate_fn(["parse_probe_google"], "parse_probe_google", stdin=body) == \
        "46 resets=2026-09-30T03:17:08Z"
    assert rotate_fn(["parse_probe_google"], "parse_probe_google",
                     stdin="AGY-BINARY-MISSING\n") == "-1 agy-binary-missing"


def test_probe_section():
    raw = "=====HIVE-PROBE kiro\n{\"a\":1}\n\n=====HIVE-PROBE meta\nM\n"
    assert rotate_fn(["probe_section"], f"probe_section '{raw}' kiro") == '{"a":1}'
    assert rotate_fn(["probe_section"], f"probe_section '{raw}' meta") == "M"


# ── hive_open over the exec path, with a stale cached session ─────────────

KUBECTL_STUB = r'''
case "$1 $2" in
  "get --raw") echo '{"items":[{"metadata":{"name":"hive-0"},"status":{"phase":"Running"}}]}'; exit 0 ;;
esac
# exec -n NS POD -- CMD...
shift 5
case "$1" in
  cat) echo '{"old":{"Role":"owner","ExpiresAt":"2026-01-01T00:00:00Z"},
              "good":{"Role":"owner","ExpiresAt":"2026-12-01T00:00:00Z"}}' ;;
  sh)  # sh -c SCRIPT sh MAXTIME SID PORT FILTER
       echo "$6" >> "$STUB_SIDS"
       if [ "$6" = good ]; then jq -c "$8" "$STUB_STATUS"
       else echo '{"error":"unauthorized"}' | jq -c "$8"; fi ;;
esac
'''


def test_hive_open_refreshes_a_refused_cached_session(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "kubectl", KUBECTL_STUB)
    status = {"timestamp": "t", "hiveId": "h", "repos": ["x" * 100],
              "agents": [{"name": "a1", "cli": "agy", "govModel": "gemini-3.6-flash-low",
                          "liveSummary": "pane", "statsConfig": {"big": 1}}]}
    (tmp_path / "status.json").write_text(json.dumps(status))
    cache = tmp_path / "sessions"
    cache.mkdir()
    (cache / "hive.sid").write_text("stale")
    env.update(STUB_STATUS=str(tmp_path / "status.json"), STUB_SIDS=str(tmp_path / "sids"),
               HIVE_SID_CACHE_DIR=str(cache), HIVE_API_VIA="exec")
    env.pop("KUBERNETES_SERVICE_HOST", None)
    r = lib('hive_open hive && echo "POD=$POD SID=$SID" && printf "%s" "$STATUS_JSON"', env=env)
    assert r.returncode == 0, r.stderr
    first, body = r.stdout.split("\n", 1)
    assert first == "POD=hive-0 SID=good"
    slim = json.loads(body)
    assert "repos" not in slim and slim["agents"][0]["liveSummary"] == "pane"
    assert "statsConfig" not in slim["agents"][0]
    assert (tmp_path / "sids").read_text().split() == ["stale", "good"]
    assert (cache / "hive.sid").read_text() == "good"


def test_tier_members_inventory_gate_ignores_pi_thinking_suffix(tmp_path):
    """A kiro rung `kiro-api-key/<id>:high` must survive the inventory gate,
    which lists bare ids; a rung whose bare id is absent must not."""
    inv = tmp_path / "inventory.tsv"
    inv.write_text("kiro\tpi\tkiro-api-key/claude-opus-5\tOpus\n"
                   "google\tagy\tgemini-3.8-flash-high\tG\n")
    tiers = ("T1|kiro|pi|kiro-api-key/claude-opus-5:high\n"
             "T1|kiro|pi|kiro-api-key/gpt-5-6-sol:high\n"
             "T1|google|agy|gemini-3.8-flash-high\n"
             "T1|openai|codex|gpt-5.6-sol\n")
    r = subprocess.run(["bash", "-c",
        f'. "{LIB}"; source <(sed -n "/^tier_members() {{/,/^}}/p" "{ROTATE}"); '
        f'TIER_SOURCE=builtin INVENTORY_OK=1 INVENTORY="{inv}" TIERS="{tiers}" tier_members T1'],
        capture_output=True, text=True, timeout=30)
    assert r.stdout.split() == ["T1|kiro|pi|kiro-api-key/claude-opus-5:high",
                                "T1|google|agy|gemini-3.8-flash-high",
                                "T1|openai|codex|gpt-5.6-sol"]


@pytest.mark.parametrize("backend,model,want", [
    ("agy", "gemini-3.8-flash-high",
     {"backend": "agy", "model": "gemini-3.8-flash-high", "reasoning_effort": "high"}),
    ("agy", "gemini-3.1-pro", {"backend": "agy", "model": "gemini-3.1-pro"}),
    ("pi", "kiro-api-key/claude-opus-5:high",
     {"backend": "pi", "model": "kiro-api-key/claude-opus-5:high"}),   # no effort key off agy
    ("muse", "muse-spark-1.3-contributor",
     {"backend": "muse", "model": "muse-spark-1.3-contributor"}),
])
def test_placement_body(backend, model, want):
    assert json.loads(out(f"hive_placement_body {backend} {model}")) == want


@pytest.mark.parametrize("resp,ok", [
    ('{"ok":true,"status":"updated","agent":"a","applied":true,"restarted":true}', True),
    ('{"ok":true,"status":"updated","agent":"a","applied":true,"restarted":false}', True),
    ('{"ok":true,"status":"updated; applied to the launch configuration but the restart failed"}', True),
    ('{"ok":false,"error":"transport rc=28: timeout"}', False),
    ('{"error":"agent not found"}', False),
    ('{"ok":true,"status":"updated","applied":false}', False),
])
def test_placement_ok(resp, ok):
    assert (lib(f"hive_placement_ok '{resp}'").returncode == 0) == ok


MUSE_APPROVAL_PANE = """\
◆ Ran command · Inspect workspace and hive env · ✗ · 0.3s · ctrl+o
◇ Calling tools (38m 13s · esc to interrupt)
  └ last event 38m 00s ago
Would you like to run the following command?
  $ pwd; ls -la /data/agents/guide 2>&1 | head -n 50
› 1. Yes, proceed (y)
  2. No, and tell Muse Code what to do differently (esc)
  muse-spark-1.3-contributor · high · /data/agents/guide · Auto-review
"""


def test_pane_muse_approval_prompt():
    assert out("pane_classify_text", stdin=MUSE_APPROVAL_PANE) == "approval"
    # the question alone (e.g. quoted in an issue body) is not the menu
    assert out("pane_classify_text",
               stdin="Would you like to run the following command?\nsome text\n") == "ready"


# ── ccleft as the probe source (2026-09-25) ───────────────────────────────
# Fixture: a real GET /readings payload captured from ccleft in ns hive
# (2026-09-25T13:42Z), account hashes redacted and home lists trimmed.

import copy
import datetime

FIXTURES = REPO / "tests/fixtures"
READINGS = json.loads((FIXTURES / "ccleft-readings.json").read_text())
PACE = OPS / "hive-pace.sh"


def epoch(iso):
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


GEN = epoch("2026-09-25T13:42:42Z")


def readings(claude_age_s=None, **edits):
    """The fixture, with claude's fetched_at moved to GEN - claude_age_s and
    per-provider field overrides (provider=dict)."""
    r = copy.deepcopy(READINGS)
    for x in r["readings"]:
        if x["provider"] == "claude" and claude_age_s is not None:
            x["fetched_at"] = datetime.datetime.fromtimestamp(
                GEN - claude_age_s, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.123Z")
        x.update(edits.get(x["provider"], {}))
    return json.dumps(r)


def probe(provider, body, now=GEN):
    return out(f"ccleft_probe {provider} {now}", stdin=body)


@pytest.mark.parametrize("iso,want", [
    ("2026-09-25T13:40:20Z", "1790343620"),
    ("2026-09-25T15:40:00.298440+00:00", "1790350800"),   # the direct probe's shape
    ("2026-09-25T15:40:00.25309Z", "1790350800"),          # ccleft's shape
    ("not a date", ""),
])
def test_iso_to_epoch(iso, want):
    assert out(f'iso_to_epoch "{iso}"') == want


def test_ccleft_normal_readings_match_direct_parser_shapes():
    body = readings(claude_age_s=120, claude={"stale": False, "cause": None})
    # same strings parse_probe_* produce for the same account state
    assert probe("kiro", body) == "40 credits=4052.86/10000 resets=2026-10-01T00:00:00Z"
    assert probe("anthropic", body) == "36 resets=2026-09-25T15:40:00Z"
    assert probe("openai", body) == "100 weekly=100% resets=2026-09-26T08:15:18Z"
    # agy: the worse GEMINI window (5h, 95.5% -> 96), never the 3p (Claude/GPT) ones
    assert probe("google", body) == "96 resets=2026-09-25T15:17:07Z"
    lim = json.loads(out(f"ccleft_anthropic_limits {GEN}", stdin=body))
    assert lim == [{"slot": "slot0", "percent": 36, "resets_at": "2026-09-25T15:40:00Z"},
                   {"slot": "slot1", "percent": 10, "resets_at": "2026-09-30T23:00:00Z"}]


def test_ccleft_anthropic_model_scoped_cap_is_a_note_not_exhaustion():
    r = json.loads(readings(claude_age_s=60, claude={"stale": False}))
    r["readings"][0]["windows"][2]["used_pct"] = 100
    assert probe("anthropic", json.dumps(r)) == "36 resets=2026-09-25T15:40:00Z capped-models=fable"


def test_ccleft_stale_young_is_still_a_measurement():
    body = readings(claude_age_s=10 * 60)   # stale:true, cause http_429, 10 min old
    assert probe("anthropic", body) == \
        "36 resets=2026-09-25T15:40:00Z (ccleft stale 10m cause=http_429)"
    assert out(f"ccleft_anthropic_limits {GEN}", stdin=body) != ""


def test_ccleft_stale_old_is_unmeasured_never_exhausted():
    body = readings(claude_age_s=45 * 60)   # the fixture's real age: 45 min
    assert probe("anthropic", body) == "-1 ccleft-stale age=45m cause=http_429"
    assert out(f"ccleft_anthropic_limits {GEN}", stdin=body) == ""   # pacer keeps its last set
    # the threshold is a knob
    r = lib(f"HIVE_CCLEFT_MAX_STALE_S=3600 ccleft_probe anthropic {GEN}", stdin=body)
    assert r.stdout.startswith("36 ")


@pytest.mark.parametrize("provider,edit,want", [
    ("meta", {}, "-1 no-usage-api (ccleft unsupported cause=api_key_login)"),
    ("deepseek", {}, "100 ccleft exhausted: provider reports is_available=false"),
    ("kiro", {"kiro": {"state": "auth_required", "cause": "http_403", "windows": []}},
     "100 no-credential (ccleft auth_required cause=http_403: needs an interactive login)"),
    ("google", {"agy": {"state": "error", "cause": "timeout", "windows": []}},
     "-1 ccleft-error cause=timeout"),
    ("anthropic", {"claude": {"state": "rate_limited", "stale": False, "windows": []}},
     "-1 ccleft-rate_limited cause=http_429"),
    ("openai", {"codex": {"windows": []}}, "100 ccleft limited: provider reports limit_reached"),
    ("github", {}, "-1 ccleft-no-reading"),
])
def test_ccleft_state_mapping(provider, edit, want):
    assert probe(provider, readings(claude_age_s=60, **edit)) == want


def test_ccleft_garbage_is_unparsed():
    assert probe("kiro", "not json") == "-1 ccleft-unparsed"


def test_ccleft_kiro_sample_and_history_dedupe(tmp_path):
    body = readings(claude_age_s=60)
    row = json.loads(out(f"ccleft_kiro_sample {GEN}", stdin=body))
    assert row == {"ts": epoch("2026-09-25T13:42:41Z"), "provider": "kiro", "slot": "slot0",
                   "pct": 40.529, "reset": epoch("2026-10-01T00:00:00Z"),
                   "used": 4052.86, "limit": 10000}
    h = tmp_path / "hist.jsonl"
    for _ in range(3):   # rotate, watchdog and pace all see the same reading
        lib(f"pace_history_add '{h}' '{json.dumps(row, separators=(',', ':'))}'")
    assert len(h.read_text().splitlines()) == 1


def test_ccleft_fetch_ok_and_down(stub_env, tmp_path):
    bindir, env = stub_env
    (tmp_path / "r.json").write_text(readings())
    write_stub(bindir, "curl", f'case "$*" in *ccleft*/readings*) cat "{tmp_path}/r.json" ;; *) exit 7 ;; esac\n')
    env.update(HIVE_CCLEFT_URL="http://ccleft.test:9464")
    r = lib("ccleft_fetch | jq -r '.readings | length'", env=env)
    assert r.stdout.strip() == "7"
    env.update(HIVE_CCLEFT_URL="http://down.test:9464")
    r = lib("ccleft_fetch; echo rc=$?", env=env)
    assert r.stdout.strip().endswith("rc=1") and "ccleft unreadable" in r.stderr


GATHER_STUBS = r'''
declare -A PCT NOTE; PROVIDERS="kiro anthropic openai google meta"
NS=hive; USAGE_NS=hive; MEASURED=0; STATE_DIR="$T"; PACE_HISTORY="$T/pace-history.jsonl"
PROBE_SOURCE=$(hive_probe_source)
provider_exhausted() { return 1; }; in_peak_window() { return 1; }
openai_pane_cap() { :; }
publish_usage() { echo "PUBLISH source=$USAGE_SOURCE"; }
load_published_usage() { echo "DIRECT-REUSE"; return 1; }
measure_usage() { echo "DIRECT-PROBES"; for p in $PROVIDERS; do PCT[$p]=7; NOTE[$p]=direct; done; MEASURED=1; }
'''


def gather(env, tmp_path):
    env["T"] = str(tmp_path)
    snippet = (GATHER_STUBS + 'gather; for p in $PROVIDERS; do echo "$p=${PCT[$p]} ${NOTE[$p]}"; done')
    r = subprocess.run(["bash", "-c",
        f'. "{LIB}"; source <(sed -n "/^gather() {{/,/^}}/p;/^usage_from_ccleft() {{/,/^}}/p" "{ROTATE}"); {snippet}'],
        capture_output=True, text=True, timeout=60, env=env)
    return r


def test_gather_reads_ccleft(stub_env, tmp_path):
    bindir, env = stub_env
    (tmp_path / "r.json").write_text(readings(claude_age_s=300))
    write_stub(bindir, "curl", f'cat "{tmp_path}/r.json"\n')
    env.update(HIVE_CCLEFT_URL="http://ccleft.test:9464")
    r = gather(env, tmp_path)
    assert "DIRECT" not in r.stdout, r.stdout + r.stderr
    assert "usage: from ccleft" in r.stdout and "PUBLISH source=ccleft" in r.stdout
    assert "kiro=40 credits=4052.86/10000" in r.stdout
    assert "meta=-1 no-usage-api" in r.stdout
    # the pacer's limit file and a Kiro sample for the budget
    assert json.loads((tmp_path / "anthropic-limits.json").read_text())[0]["percent"] == 36
    assert json.loads((tmp_path / "pace-history.jsonl").read_text())["used"] == 4052.86


def test_gather_falls_back_to_direct_probes_loudly_when_ccleft_is_down(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "curl", 'echo "curl: (7) Failed to connect" >&2; exit 7\n')
    env.update(HIVE_CCLEFT_URL="http://ccleft.test:9464")
    r = gather(env, tmp_path)
    assert "FALLING BACK TO DIRECT PROVIDER PROBES" in r.stdout
    assert "DIRECT-PROBES" in r.stdout and "PUBLISH source=direct" in r.stdout
    assert "kiro=7 direct" in r.stdout


def test_gather_direct_switch_never_asks_ccleft(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "curl", f'echo called >> "{tmp_path}/curl.log"; exit 7\n')
    env.update(HIVE_CCLEFT_URL="http://ccleft.test:9464", HIVE_PROBE_SOURCE="direct")
    r = gather(env, tmp_path)
    assert "DIRECT-PROBES" in r.stdout and "FALLING BACK" not in r.stdout
    assert not (tmp_path / "curl.log").exists()


# ── Kiro ladder + budget pacing ───────────────────────────────────────────

def test_rung_chain_and_up():
    assert out("rung_chain kiro-api-key/claude-opus-5:high").split() == [
        "kiro-api-key/claude-opus-5:high", "kiro-api-key/claude-sonnet-5:high",
        "kiro-api-key/claude-haiku-4-5:low"]
    assert out("rung_chain kiro-api-key/gpt-5-6-sol:high").split()[-1] == "kiro-api-key/claude-haiku-4-5:low"
    assert out("rung_up_toward kiro-api-key/claude-opus-5:high kiro-api-key/claude-haiku-4-5:low") == \
        "kiro-api-key/claude-sonnet-5:high"
    assert out("rung_up_toward kiro-api-key/claude-opus-5:high kiro-api-key/claude-sonnet-5:high") == \
        "kiro-api-key/claude-opus-5:high"
    assert out("rung_up_toward kiro-api-key/claude-opus-5:high kiro-api-key/claude-opus-5:high") == ""


def test_pace_demoted_from_follows_the_two_notch_kiro_chain(tmp_path):
    f = tmp_path / "pace-demoted"
    f.write_text("hive/architect|pi|kiro-api-key/claude-opus-5:high\n")
    for cur in ("kiro-api-key/claude-sonnet-5:high", "kiro-api-key/claude-haiku-4-5:low"):
        assert out(f'pace_demoted_from "{f}" hive architect {cur}') == "pi|kiro-api-key/claude-opus-5:high"
    assert out(f'pace_demoted_from "{f}" hive architect kiro-api-key/gpt-5-6-luna:high') == ""


def test_kiro_evict_targets(tmp_path):
    f = tmp_path / "kiro-evict"
    f.write_text("hive/architect|2000|google,anthropic\nhive-reef/guide|500|google\n")
    assert out(f'kiro_evict_targets "{f}" hive architect 1000') == "google anthropic"
    assert out(f'kiro_evict_targets "{f}" hive-reef guide 1000') == ""      # expired
    assert out(f'kiro_evict_targets "{f}" hive guide 1000') == ""


def pace_fn(names, snippet, env=None):
    extract = "; ".join(f'source <(sed -n "/^{n}() {{/,/^}}/p" "{PACE}")' for n in names)
    return subprocess.run(["bash", "-c", f'. "{LIB}"; {extract}; {snippet}'],
                          capture_output=True, text=True, timeout=60, env=env)


def kiro_hist(tmp_path, pts, reset="2026-10-01T00:00:00Z"):
    h = tmp_path / "hist.jsonl"
    h.write_text("".join(json.dumps({"ts": t, "provider": "kiro", "slot": "slot0",
                                     "pct": u / 100, "reset": epoch(reset), "used": u,
                                     "limit": 10000}) + "\n" for t, u in pts))
    return h


def budget(tmp_path, pts, now, last_act=0):
    h = kiro_hist(tmp_path, pts)
    (tmp_path / "last").write_text(str(last_act))
    r = pace_fn(["kiro_budget"], f'HISTORY="{h}"; NOW={now}; KIRO_LAST_ACT="{tmp_path}/last"; kiro_budget')
    return json.loads(r.stdout)


T0 = epoch("2026-09-25T13:40:00Z")   # 130.33 h before the reset


def test_kiro_budget_over():
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        # 60 credits/h over the last 40 min, 5947 left
        pts = [(T0 + i * 600, 4053 + 10 * i) for i in range(5)]
        b = budget(pathlib.Path(d), pts, T0 + 2400)
    assert b["verdict"] == "over" and b["burn"] == 60.0
    assert b["allowed"] == pytest.approx(5907 / ((epoch("2026-10-01T00:00:00Z") - T0 - 2400) / 3600) * 0.85, abs=0.1)
    assert b["allowed"] < 40


def test_kiro_budget_under_learning_settling(tmp_path):
    slow = [(T0 + i * 600, 4053 + 2 * i) for i in range(5)]           # 12 cr/h
    assert budget(tmp_path, slow, T0 + 2400)["verdict"] == "under"
    assert budget(tmp_path, slow[:2], T0 + 600)["verdict"] == "learning"
    # the fit never reaches back across the last actuation
    assert budget(tmp_path, slow, T0 + 2400, last_act=T0 + 1900)["verdict"] == "settling"
    # an old last reading is not a basis for action
    assert budget(tmp_path, slow, T0 + 2400 + 3600)["verdict"] == "stale"


def test_kiro_budget_ignores_the_month_rollover(tmp_path):
    pts = [(T0, 9990), (T0 + 600, 9995), (T0 + 1200, 5), (T0 + 1800, 10), (T0 + 2400, 15), (T0 + 3000, 20)]
    b = budget(tmp_path, pts, T0 + 3000)
    assert b["used"] == 20 and b["burn"] == 30.0


FLEET_TSV = "\n".join("\t".join(r) for r in [
    ("hive", "architect", "pi", "kiro-api-key/claude-sonnet-5:high", "false", "15m"),
    ("hive", "sec-check", "pi", "kiro-api-key/gpt-5-6-luna:high", "false", "15m"),
    ("hive", "guide", "pi", "kiro-api-key/claude-sonnet-5:medium", "false", "4h"),
    ("hive", "telemetry", "pi", "kiro-api-key/claude-sonnet-5:medium", "false", "paused"),
    ("hive", "supervisor", "pi", "kiro-api-key/claude-sonnet-5:medium", "false", "4h"),  # pinned
    ("hive", "scanner", "claude", "claude-sonnet-5", "false", "5m"),
])

ACTUATE = r'''
provider_of_agent() { local p; p=$(hive_provider_of "$1" "$2"); case "$p" in kiro|anthropic|google|openai) echo "$p";; esac; }
PACE_PIN=",hive/supervisor,"; pace_pinned() { [ "${PACE_PIN#*,$1/$2,}" != "$PACE_PIN" ]; }
set_model() { echo "$1/$2 $3 $4" >> "$T/set"; }
usage_data() { printf '%s' "$USAGE"; }
moved=0; NOW=1000
DEMOTED="$T/pace-demoted"; KIRO_EVICT="$T/kiro-evict"; KIRO_LAST_ACT="$T/last"; touch "$DEMOTED"
kiro_budget_actuate; echo "moved=$moved"
'''


def actuate(tmp_path, kb, fleet=FLEET_TSV, verdicts="{}", usage="{}", demoted=""):
    (tmp_path / "pace-demoted").write_text(demoted)
    env = dict(__import__("os").environ, T=str(tmp_path), KB=json.dumps(kb), FLEET=fleet,
               VERDICTS=verdicts, USAGE=usage)
    r = pace_fn(["kiro_budget_actuate", "kiro_rows", "kicks_per_hour", "kiro_note_act"], ACTUATE, env=env)
    sets = (tmp_path / "set").read_text().splitlines() if (tmp_path / "set").exists() else []
    return r, sets


def test_kiro_over_demotes_biggest_saving_first_until_the_gap_closes(tmp_path):
    r, sets = actuate(tmp_path, {"verdict": "over", "burn": 60, "allowed": 30})
    # weights (mult x kicks/h): architect 1.3*4=5.2, sec-check 1.1*4=4.4, guide and
    # (pinned) supervisor 1.3*0.25 -> savings ~21 + ~16.4 cr/h close the 30 cr/h gap;
    # pinned supervisor and never-kicked telemetry are never candidates.
    assert sets == ["hive/architect pi kiro-api-key/claude-haiku-4-5:low",
                    "hive/sec-check pi kiro-api-key/claude-haiku-4-5:low"], r.stdout + r.stderr
    assert "hive/architect|pi|kiro-api-key/claude-sonnet-5:high" in (tmp_path / "pace-demoted").read_text()
    assert (tmp_path / "last").read_text().strip() == "1000"


def test_kiro_over_keeps_the_original_rung_in_the_journal(tmp_path):
    fleet = "hive\tarchitect\tpi\tkiro-api-key/claude-sonnet-5:high\tfalse\t15m"
    actuate(tmp_path, {"verdict": "over", "burn": 60, "allowed": 40}, fleet=fleet,
            demoted="hive/architect|pi|kiro-api-key/claude-opus-5:high\n")
    assert (tmp_path / "pace-demoted").read_text() == "hive/architect|pi|kiro-api-key/claude-opus-5:high\n"


def test_kiro_over_with_nothing_to_demote_caps_onto_a_pool_with_headroom(tmp_path):
    fleet = ("hive\tarchitect\tpi\tkiro-api-key/claude-haiku-4-5:low\tfalse\t15m\n"
             "hive\tguide\tpi\tkiro-api-key/claude-haiku-4-5:low\tfalse\t4h")
    usage = json.dumps({"google": "96% used resets=x", "anthropic": "40% used resets=y"})
    r, sets = actuate(tmp_path, {"verdict": "over", "burn": 60, "allowed": 40}, fleet=fleet,
                      verdicts=json.dumps({"anthropic": {"verdict": "on-pace"}}), usage=usage)
    assert sets == []
    rows = (tmp_path / "kiro-evict").read_text().splitlines()
    assert [x.split("|")[0] for x in rows] == ["hive/architect", "hive/guide"]
    assert all(x.endswith("|anthropic") for x in rows)   # agy 96%: no headroom


def test_kiro_over_saturated_when_no_pool_has_headroom(tmp_path):
    fleet = "hive\tarchitect\tpi\tkiro-api-key/claude-haiku-4-5:low\tfalse\t15m"
    usage = json.dumps({"google": "96% used", "anthropic": "40% used"})
    r, sets = actuate(tmp_path, {"verdict": "over", "burn": 60, "allowed": 40}, fleet=fleet,
                      verdicts=json.dumps({"anthropic": {"verdict": "hot"}}), usage=usage)
    assert "SATURATED" in r.stdout and not (tmp_path / "kiro-evict").exists()


def test_kiro_under_promotes_one_notch_only_within_headroom(tmp_path):
    fleet = ("hive\tarchitect\tpi\tkiro-api-key/claude-haiku-4-5:low\tfalse\t15m\n"
             "hive\tguide\tpi\tkiro-api-key/claude-haiku-4-5:low\tfalse\t4h")
    demoted = ("hive/architect|pi|kiro-api-key/claude-opus-5:high\n"
               "hive/guide|pi|kiro-api-key/claude-sonnet-5:medium\n")
    r, sets = actuate(tmp_path, {"verdict": "under", "burn": 10, "allowed": 40}, fleet=fleet, demoted=demoted)
    # guide adds the least burn; promoted to its original rung, so its row goes
    assert sets == ["hive/guide pi kiro-api-key/claude-sonnet-5:medium"], r.stdout + r.stderr
    assert "hive/guide|" not in (tmp_path / "pace-demoted").read_text()
    # a promotion that would push the ratio past PROMOTE_MAX is refused
    (tmp_path / "set").unlink()
    r, sets = actuate(tmp_path, {"verdict": "under", "burn": 23, "allowed": 40},
                      fleet=fleet.split("\n")[0], demoted=demoted)
    assert sets == []
