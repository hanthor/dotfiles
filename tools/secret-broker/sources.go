package main

import (
	"context"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// secretRef names a secret the broker may hand out and where it lives in the
// regular Bitwarden vault (accessed via the `bw` CLI).
//
//	Item — bw item id or name
//	Get  — which part of the item to read: notes|password|username|uri|totp
//	       (default "notes"; secure notes hold things like kubeconfig/talosconfig)
type secretRef struct {
	Name string `json:"name"`
	Item string `json:"item"`
	Get  string `json:"get,omitempty"`
}

func (r secretRef) getObject() string {
	if r.Get == "" {
		return "notes"
	}
	return r.Get
}

// policy is the least-privilege map: which secrets a given node may receive.
// Authorization is by StableID; a node gets ONLY the refs listed for it (plus
// any defaults). Pure and unit-tested — no network.
type policy struct {
	byStableID map[string][]secretRef
	def        []secretRef // handed to every authorized node
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
		out[r.Name] = "STUB:" + r.Item + ":" + r.getObject() + ":not-a-real-secret"
	}
	return out, nil
}

// ── bwSource ──────────────────────────────────────────────────────────────
// Production source: reads from the regular Bitwarden vault via the `bw` CLI.
//
// Auth: the broker process holds a BW_SESSION (from the env). For unattended
// operation, if a `bw get` fails while BW_PASSWORD is set, the source re-unlocks
// (`bw unlock --passwordenv BW_PASSWORD --raw`) once and retries — so an expired
// session self-heals. This means a standing master password lives on the broker
// host; scope the blast radius by pointing the broker's `bw` account at a
// dedicated read-only collection (see the README runbook). Compile-verified here;
// needs a logged-in `bw` to run.

type bwSource struct {
	pol     policy
	bwBin   string
	timeout time.Duration

	mu      sync.Mutex
	session string // cached; refreshed on lock
}

func newBwSource(pol policy, bwBin string, timeout time.Duration) *bwSource {
	if bwBin == "" {
		bwBin = "bw"
	}
	if timeout == 0 {
		timeout = 15 * time.Second
	}
	return &bwSource{pol: pol, bwBin: bwBin, timeout: timeout, session: os.Getenv("BW_SESSION")}
}

func (s *bwSource) SecretsFor(id identity) (map[string]string, error) {
	refs := s.pol.refsFor(id)
	out := map[string]string{}
	for _, r := range refs {
		val, err := s.fetch(r)
		if err != nil {
			return nil, &brokerError{status: 502, msg: "fetch " + r.Name + ": " + err.Error()}
		}
		out[r.Name] = val
	}
	return out, nil
}

func (s *bwSource) fetch(r secretRef) (string, error) {
	val, err := s.bwGet(r)
	// Self-heal an expired/locked session once if we have a master password.
	if err != nil && os.Getenv("BW_PASSWORD") != "" {
		if rerr := s.refresh(); rerr == nil {
			val, err = s.bwGet(r)
		}
	}
	return val, err
}

func (s *bwSource) bwGet(r secretRef) (string, error) {
	s.mu.Lock()
	session := s.session
	s.mu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), s.timeout)
	defer cancel()
	args := []string{"get", r.getObject(), r.Item}
	if session != "" {
		args = append(args, "--session", session)
	}
	out, err := exec.CommandContext(ctx, s.bwBin, args...).Output()
	if err != nil {
		return "", err
	}
	return strings.TrimRight(string(out), "\r\n"), nil
}

func (s *bwSource) refresh() error {
	ctx, cancel := context.WithTimeout(context.Background(), s.timeout)
	defer cancel()
	// Reads the master password from BW_PASSWORD; requires the account to be
	// logged in already (`bw login` / `bw login --apikey` done once on the host).
	out, err := exec.CommandContext(ctx, s.bwBin, "unlock", "--passwordenv", "BW_PASSWORD", "--raw").Output()
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.session = strings.TrimRight(string(out), "\r\n")
	s.mu.Unlock()
	return nil
}
