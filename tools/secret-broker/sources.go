package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"time"
)

// secretRef names a secret the broker may hand out and where it lives in
// Bitwarden Secrets Manager (SMID = the SM secret UUID).
type secretRef struct {
	Name string `json:"name"` // key written on the target, e.g. "kubeconfig"
	SMID string `json:"smID"` // Bitwarden Secrets Manager secret id
}

// policy is the least-privilege map: which secrets a given node may receive.
// Authorization is by StableID; a node gets ONLY the refs listed for it (plus
// any defaults). Pure and unit-tested — no network.
type policy struct {
	byStableID map[string][]secretRef
	def        []secretRef // handed to every authorized node (e.g. tailscale authkey)
}

func (p policy) refsFor(id identity) []secretRef {
	out := append([]secretRef(nil), p.def...)
	out = append(out, p.byStableID[id.StableID]...)
	return out
}

// ── stubSource ────────────────────────────────────────────────────────────
// Spike/test source: returns placeholder values for whatever the policy allows.
// No real secret material ever.

type stubSource struct{ pol policy }

func (s stubSource) SecretsFor(id identity) (map[string]string, error) {
	refs := s.pol.refsFor(id)
	out := map[string]string{}
	for _, r := range refs {
		out[r.Name] = "STUB:" + r.SMID + ":not-a-real-secret"
	}
	return out, nil
}

// ── bwsSource ─────────────────────────────────────────────────────────────
// Production source: reads from Bitwarden Secrets Manager via the `bws` CLI,
// authenticated by BWS_ACCESS_TOKEN (a machine-account token, read-scoped to a
// single onboarding project — categorically smaller blast radius than the vault
// master password). Compile-verified only here; needs a real token to run.

type bwsSource struct {
	pol     policy
	bwsBin  string        // path to `bws` (default "bws")
	timeout time.Duration // per-secret fetch timeout
}

func newBwsSource(pol policy, bwsBin string, timeout time.Duration) bwsSource {
	if bwsBin == "" {
		bwsBin = "bws"
	}
	if timeout == 0 {
		timeout = 10 * time.Second
	}
	return bwsSource{pol: pol, bwsBin: bwsBin, timeout: timeout}
}

// bwsSecret is the subset of `bws secret get <id>` JSON we consume.
type bwsSecret struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

func (s bwsSource) SecretsFor(id identity) (map[string]string, error) {
	refs := s.pol.refsFor(id)
	out := map[string]string{}
	for _, r := range refs {
		val, err := s.fetch(r.SMID)
		if err != nil {
			return nil, &brokerError{status: 502, msg: fmt.Sprintf("fetch %s: %v", r.Name, err)}
		}
		out[r.Name] = val
	}
	return out, nil
}

func (s bwsSource) fetch(smID string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), s.timeout)
	defer cancel()
	// BWS_ACCESS_TOKEN is inherited from the broker process environment.
	cmd := exec.CommandContext(ctx, s.bwsBin, "secret", "get", smID)
	stdout, err := cmd.Output()
	if err != nil {
		return "", err
	}
	var sec bwsSecret
	if err := json.Unmarshal(stdout, &sec); err != nil {
		return "", fmt.Errorf("parse bws output: %w", err)
	}
	return sec.Value, nil
}
