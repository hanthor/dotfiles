"""Unit tests for talos-k8s/hive/ops/scripts/hive-tiers.sh.

The script rebuilds hive-rotate.sh's capability tiers from the Artificial
Analysis API. `curl` is replaced by a stub on PATH that writes a canned JSON
body and prints an HTTP status, so nothing touches the network. HIVE_ROTATE_STATE
and HOME point into tmp_path, so the real tier cache is never read or written.
"""
import json
import subprocess

import pytest

from conftest import REPO, write_stub

TIERS = REPO / "talos-k8s/hive/ops/scripts/hive-tiers.sh"


def model(slug, creator, agentic, price=1.0, coding=10.0, name=None):
    return {
        "slug": slug,
        "name": name or slug,
        "model_creator": {"name": creator},
        "evaluations": {
            "artificial_analysis_agentic_index": agentic,
            "artificial_analysis_coding_index": coding,
        },
        "price_1m_output_tokens": price,
    }


@pytest.fixture
def env(stub_env, tmp_path):
    bindir, e = stub_env
    state = tmp_path / "state"
    e["HIVE_ROTATE_STATE"] = str(state)
    e.pop("AA_API_KEY", None)
    e.pop("KUBERNETES_SERVICE_HOST", None)
    return bindir, e, state


def stub_api(bindir, status, body):
    """curl stub: copies `body` to the -o target and prints `status` (for -w)."""
    payload = bindir / "payload.json"
    payload.write_text(body if isinstance(body, str) else json.dumps(body))
    write_stub(bindir, "curl", f"""
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    -H) echo "$2" >> "{bindir}/headers" ; shift ;;
  esac
  shift
done
cp "{payload}" "$out"
printf '%s' '{status}'
""")


def run(env_pair, *args, **extra):
    _, e, _ = env_pair
    e = {**e, **extra}
    return subprocess.run(["bash", str(TIERS), *args], capture_output=True,
                          text=True, timeout=30, env=e)


def rows(state):
    lines = (state / "tiers.tsv").read_text().splitlines()
    return [ln.split("\t") for ln in lines if not ln.startswith("#")]


# ── argument handling and `show` ──────────────────────────────────────────

def test_unknown_action_is_usage_error(env):
    r = run(env, "bogus")
    assert r.returncode == 2
    assert "usage:" in r.stderr


def test_show_without_cache_fails(env):
    r = run(env, "show")
    assert r.returncode == 1
    assert "no tier cache" in r.stderr


def test_show_defaults_to_show_and_prints_cache(env):
    _, _, state = env
    state.mkdir()
    (state / "tiers.tsv").write_text(
        "# generated 2026-01-01T00:00:00+00:00 from https://example.test\n"
        "# tier<TAB>provider\n"
        "T1\tanthropic\tclaude\topus-5\t55\t25\n")
    r = run(env)
    assert r.returncode == 0
    assert r.stdout.startswith("tier\tprovider\tbackend\tmodel\tagentic")
    assert "T1\tanthropic\tclaude\topus-5\t55\t25" in r.stdout
    assert "# generated: 2026-01-01T00:00:00+00:00 from https://example.test" in r.stdout
    # comment lines of the cache are not echoed as rows
    assert "# tier<TAB>provider" not in r.stdout


# ── refresh: key lookup ───────────────────────────────────────────────────

def test_refresh_without_key_keeps_cache(env):
    _, _, state = env
    state.mkdir()
    (state / "tiers.tsv").write_text("T1\tanthropic\tclaude\told\t50\t1\n")
    r = run(env, "refresh")
    assert r.returncode == 1
    assert "no Artificial Analysis API key" in r.stderr
    assert (state / "tiers.tsv").read_text() == "T1\tanthropic\tclaude\told\t50\t1\n"


def test_refresh_reads_key_from_config_file(env):
    bindir, e, state = env
    stub_api(bindir, "200", {"data": [model("anthropic-claude-opus-5", "Anthropic", 55)]})
    cfg = bindir.parent / "home" / ".config" / "hive"
    cfg.mkdir(parents=True)
    (cfg / "aa-api-key").write_text("file-key\r\n")
    r = run(env, "refresh")
    assert r.returncode == 0, r.stderr
    assert "x-api-key: file-key" in (bindir / "headers").read_text()


def test_env_key_wins_over_config_file(env):
    bindir, e, state = env
    stub_api(bindir, "200", {"data": [model("anthropic-claude-opus-5", "Anthropic", 55)]})
    cfg = bindir.parent / "home" / ".config" / "hive"
    cfg.mkdir(parents=True)
    (cfg / "aa-api-key").write_text("file-key\n")
    r = run(env, "refresh", AA_API_KEY="env-key")
    assert r.returncode == 0, r.stderr
    assert "x-api-key: env-key" in (bindir / "headers").read_text()


# ── refresh: API failures never clobber the cache ─────────────────────────

@pytest.mark.parametrize("status,body", [
    ("500", {"data": [model("anthropic-claude-opus-5", "Anthropic", 55)]}),
    ("401", {"error": "bad key"}),
    ("200", {"error": "no data field"}),
    ("200", "not json at all"),
])
def test_api_failure_keeps_cache(env, status, body):
    bindir, _, state = env
    state.mkdir()
    (state / "tiers.tsv").write_text("T1\tanthropic\tclaude\told\t50\t1\n")
    stub_api(bindir, status, body)
    r = run(env, "refresh", AA_API_KEY="k")
    assert r.returncode == 1
    assert "benchmark API returned HTTP" in r.stderr
    assert (state / "tiers.tsv").read_text() == "T1\tanthropic\tclaude\told\t50\t1\n"
    assert not (state / "aa-models.json.tmp").exists()


def test_no_usable_models_keeps_cache(env):
    """Only creators the hive cannot launch, or unscored models: nothing to write."""
    bindir, _, state = env
    state.mkdir()
    (state / "tiers.tsv").write_text("T1\tanthropic\tclaude\told\t50\t1\n")
    stub_api(bindir, "200", {"data": [
        model("google-gemini-9", "Google", 70),
        model("deepseek-ai-v9", "DeepSeek", 60),
        model("anthropic-unscored", "Anthropic", None),
    ]})
    r = run(env, "refresh", AA_API_KEY="k")
    assert r.returncode == 1
    assert "no usable models parsed" in r.stderr
    assert (state / "tiers.tsv").read_text() == "T1\tanthropic\tclaude\told\t50\t1\n"
    assert not (state / "tiers.tsv.tmp").exists()


# ── refresh: banding, filtering and shaping ───────────────────────────────

def test_tier_bands_use_absolute_agentic_score(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [
        model("anthropic-claude-opus-5", "Anthropic", 58.2),
        model("anthropic-claude-edge-high", "Anthropic", 48.0),   # exactly the T1 cut
        model("openai-gpt-mid", "OpenAI", 47.9),                  # just below -> T2
        model("openai-gpt-low-mid", "OpenAI", 30.0),              # exactly the T2 cut
        model("openai-gpt-weak", "OpenAI", 29.9),                 # just below -> T3
    ]})
    r = run(env, "refresh", AA_API_KEY="k")
    assert r.returncode == 0, r.stderr
    tier = {m[3]: m[0] for m in rows(state)}
    assert tier == {
        "claude-opus-5": "T1",
        "claude-edge-high": "T1",
        "gpt-mid": "T2",
        "gpt-low-mid": "T2",
        "gpt-weak": "T3",
    }


def test_provider_and_backend_mapping_and_slug_prefixes(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [
        model("anthropic-claude-opus-5", "Anthropic", 55),
        model("openai-gpt-6", "OpenAI", 50),
        model("google-gemini-9", "Google", 70),       # excluded: no usable backend
        model("deepseek-ai-v9", "DeepSeek", 65),      # excluded: no longer funded
        model("mistral-large", "Mistral", 60),        # excluded: not launchable
    ]})
    r = run(env, "refresh", AA_API_KEY="k")
    assert r.returncode == 0, r.stderr
    got = {(m[1], m[2], m[3]) for m in rows(state)}
    assert got == {("anthropic", "claude", "claude-opus-5"),
                   ("openai", "codex", "gpt-6")}


def test_creator_match_is_case_insensitive(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [model("anthropic-claude-x", "ANTHROPIC PBC", 55)]})
    run(env, "refresh", AA_API_KEY="k")
    assert [(m[1], m[2]) for m in rows(state)] == [("anthropic", "claude")]


def test_keeps_best_two_per_tier_and_provider(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [
        model("anthropic-a", "Anthropic", 52),
        model("anthropic-b", "Anthropic", 58),
        model("anthropic-c", "Anthropic", 55),
        model("anthropic-d", "Anthropic", 49),
        model("openai-z", "OpenAI", 50),
    ]})
    run(env, "refresh", AA_API_KEY="k")
    anthropic_t1 = [m[3] for m in rows(state) if m[0] == "T1" and m[1] == "anthropic"]
    assert anthropic_t1 == ["b", "c"]            # best two, highest first
    assert [m[3] for m in rows(state) if m[1] == "openai"] == ["z"]


def test_rows_sorted_by_tier_then_descending_score(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [
        model("openai-gpt-low", "OpenAI", 10),
        model("openai-gpt-top", "OpenAI", 50),
        model("anthropic-claude-mid", "Anthropic", 40),
        model("anthropic-claude-x", "Anthropic", 58),
    ]})
    run(env, "refresh", AA_API_KEY="k")
    assert [(m[0], m[3]) for m in rows(state)] == [
        ("T1", "claude-x"), ("T1", "gpt-top"), ("T2", "claude-mid"), ("T3", "gpt-low")]


def test_missing_price_defaults_to_zero(env):
    bindir, _, state = env
    m = model("anthropic-claude-x", "Anthropic", 55)
    del m["price_1m_output_tokens"]
    stub_api(bindir, "200", {"data": [m]})
    run(env, "refresh", AA_API_KEY="k")
    assert rows(state)[0][5] == "0"


# ── refresh: output and cache file shape ──────────────────────────────────

def test_refresh_writes_header_and_reports_rungs(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [
        model("anthropic-claude-opus-5", "Anthropic", 55, price=25),
        model("openai-gpt-6", "OpenAI", 35, price=10),
    ]})
    r = run(env, "refresh", AA_API_KEY="k")
    assert r.returncode == 0, r.stderr
    assert "wrote 2 rungs to" in r.stdout
    assert str(state / "tiers.tsv") in r.stdout
    head = (state / "tiers.tsv").read_text().splitlines()
    assert head[0].startswith("# generated ")
    assert "artificialanalysis.ai/api/v2/language/models/free" in head[0]
    assert head[1].startswith("# tier")
    # the raw payload is kept for inspection, and no temp files are left behind
    assert (state / "aa-models.json").exists()
    assert not (state / "tiers.tsv.tmp").exists()
    assert not (state / "aa-models.json.tmp").exists()


def test_refresh_then_show_roundtrip(env):
    bindir, _, state = env
    stub_api(bindir, "200", {"data": [model("anthropic-claude-opus-5", "Anthropic", 55)]})
    assert run(env, "refresh", AA_API_KEY="k").returncode == 0
    r = run(env, "show")
    assert r.returncode == 0
    assert "T1\tanthropic\tclaude\tclaude-opus-5\t55\t1" in r.stdout
