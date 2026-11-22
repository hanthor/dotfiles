"""roles/omp routing: every model it names must be usable.

omp silently skips a fallback entry that is not allow-listed, and an id that
does not exist in the catalog only shows up as a failed fallback mid-session.
These checks catch the mistakes that broke routing before (2026-11-21).
"""
from fnmatch import fnmatch
from pathlib import Path
import re

import yaml

REPO = Path(__file__).resolve().parent.parent
ROUTING = REPO / "roles/omp/files/routing.yml"
ROUTE = REPO / "roles/omp/files/omp-route"

# ids that do not exist in omp's catalog, with what to use instead
NOT_IN_CATALOG = {
    "openrouter/auto": "openrouter/openrouter/auto",
    "openai-codex/gpt-6.1-sol": "openai-codex/gpt-6-luna (gpt-6.1-sol is OpenRouter-only)",
    "meta/muse-spark-1.3-contributor": "muse-code/muse-spark-1.3 (no META_API_KEY in the fleet)",
}


def routing():
    return yaml.safe_load(ROUTING.read_text())


def strip_thinking(model):
    return re.sub(r":(off|minimal|low|medium|high|xhigh|max)$", "", model)


def routed_models():
    cfg = routing()
    models = list(cfg["modelRoles"].values())
    for chain in cfg["retry"]["fallbackChains"].values():
        models.extend(chain)
    text = ROUTE.read_text()
    models += re.findall(r'^\s*"[a-z]+\|[^|]+\|([^"]+)"', text, re.M)
    models += re.findall(r'^LAST_RESORT="([^"]+)"', text, re.M)
    return [strip_thinking(m) for m in models]


def test_every_routed_model_is_allow_listed():
    allowed = routing()["enabledModels"]
    missing = sorted({m for m in routed_models() if not any(fnmatch(m, p) for p in allowed)})
    assert not missing, f"not in enabledModels: {missing}"


def test_no_model_that_is_missing_from_the_catalog():
    bad = sorted({m for m in routed_models() if m in NOT_IN_CATALOG})
    assert not bad, {m: NOT_IN_CATALOG[m] for m in bad}


def test_claude_holds_no_usage_reserve():
    assert routing()["retry"]["usageReservePct"] == 0
    assert 'CLAUDE_RESERVE_PCT="${OMP_ROUTE_CLAUDE_RESERVE_PCT:-0}"' in ROUTE.read_text()


def test_omp_route_finds_candidates():
    # guards the regex above against a silent format change
    assert len(re.findall(r'^\s*"[a-z]+\|', ROUTE.read_text(), re.M)) >= 4
