import subprocess
import sys

import yaml

from conftest import REPO

NEW_IP = "13.62.161.5"
PG_HOST = "postgres.postgres.svc.cluster.local"
CLUSTER_ISSUER = "letsencrypt-cloudflare"
MEDIA_CLAIM = "synapse-media-preseed"


def render(input_values: dict) -> dict:
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ess-render-values.py")],
        input=yaml.safe_dump(input_values),
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return yaml.safe_load(r.stdout)


def minimal_input(**overrides) -> dict:
    base = {
        "synapse": {"postgres": {"host": "old-host"}},
        "matrixAuthenticationService": {"postgres": {"host": "old-host"}},
        "matrixRTC": {"sfu": {"manualIP": "old-ip"}},
        "certManager": {"clusterIssuer": "old-issuer"},
    }
    base.update(overrides)
    return base


def test_rewrites_synapse_and_mas_postgres_host():
    out = render(minimal_input())
    assert out["synapse"]["postgres"]["host"] == PG_HOST
    assert out["matrixAuthenticationService"]["postgres"]["host"] == PG_HOST


def test_disables_in_chart_postgres():
    out = render(minimal_input())
    assert out["postgres"]["enabled"] is False


def test_preserves_existing_postgres_keys_when_disabling():
    out = render(minimal_input(postgres={"existingKey": "keep-me"}))
    assert out["postgres"]["existingKey"] == "keep-me"
    assert out["postgres"]["enabled"] is False


def test_rewrites_sfu_manual_ip():
    out = render(minimal_input())
    assert out["matrixRTC"]["sfu"]["manualIP"] == NEW_IP


def test_rewrites_all_host_aliases_ips():
    values = minimal_input()
    values["matrixRTC"]["hostAliases"] = [
        {"hostnames": ["a.example"], "ip": "old-ip-1"},
        {"hostnames": ["b.example"], "ip": "old-ip-2"},
    ]
    out = render(values)
    ips = [alias["ip"] for alias in out["matrixRTC"]["hostAliases"]]
    assert ips == [NEW_IP, NEW_IP]
    # hostnames are untouched
    assert out["matrixRTC"]["hostAliases"][0]["hostnames"] == ["a.example"]


def test_no_host_aliases_key_is_a_noop():
    values = minimal_input()
    assert "hostAliases" not in values["matrixRTC"]
    out = render(values)
    assert "hostAliases" not in out["matrixRTC"]


def test_rewrites_cluster_issuer():
    out = render(minimal_input())
    assert out["certManager"]["clusterIssuer"] == CLUSTER_ISSUER


def test_sets_media_existing_claim_creating_nested_keys():
    out = render(minimal_input())
    assert out["synapse"]["media"]["storage"]["existingClaim"] == MEDIA_CLAIM


def test_preserves_existing_media_storage_keys():
    values = minimal_input()
    values["synapse"]["media"] = {"storage": {"size": "50Gi"}}
    out = render(values)
    assert out["synapse"]["media"]["storage"]["size"] == "50Gi"
    assert out["synapse"]["media"]["storage"]["existingClaim"] == MEDIA_CLAIM


def test_sets_ingress_class_name():
    out = render(minimal_input())
    assert out["ingress"]["className"] == "traefik"


def test_preserves_existing_ingress_keys():
    out = render(minimal_input(ingress={"annotations": {"a": "b"}}))
    assert out["ingress"]["annotations"] == {"a": "b"}
    assert out["ingress"]["className"] == "traefik"


def test_unrelated_top_level_keys_pass_through_unchanged():
    values = minimal_input()
    values["elementWeb"] = {"enabled": True}
    out = render(values)
    assert out["elementWeb"] == {"enabled": True}
