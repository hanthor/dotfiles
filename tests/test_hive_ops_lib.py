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
    ("kiro-api-key/claude-sonnet-5", ""),
    ("kiro-api-key/claude-opus-5:high", "kiro-api-key/claude-sonnet-5:high"),
    ("kiro-api-key/gpt-5-6-sol:high", "kiro-api-key/gpt-5-6-luna:high"),
    ("kiro-api-key/claude-sonnet-5:medium", ""),
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
