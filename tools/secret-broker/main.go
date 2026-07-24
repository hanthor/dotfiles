// Command secret-broker is a Phase 1 SPIKE for QR secret onboarding (issue #49).
//
// It joins the tailnet as its own node (via tsnet) and serves secrets over the
// tailnet ONLY. For each request it resolves the caller's *verified* tailnet
// identity with LocalClient().WhoIs — the WireGuard-authenticated peer, not
// anything the caller asserts — and:
//
//  1. Admission gate: the caller must carry an ACL tag (default tag:fleet).
//     This is coarse — EVERY fleet node has it — so it gates reachability,
//     not which secrets you get.
//  2. Scoping: secrets are keyed on the node's StableNodeID, assigned by the
//     coordination server and UNFORGEABLE. We deliberately do NOT key on
//     hostname/DNSName: Phase 0 sets --hostname=<name> and that field is
//     user-settable, so a malicious node could claim to be "bihar".
//  3. Bootstrap-of-trust: a brand-new node has no prior StableNodeID mapping.
//     That first-contact case is made EXPLICIT below (TOFU for the spike) — in
//     production this is exactly where a phone-conveyed one-time pairing token
//     would gate issuance. It is not an implicit map lookup.
//
// This is a spike: one endpoint, stub secret source, no persistence. The value
// is proving identity-gated delivery. Compile-verified only — a live run needs a
// TS_AUTHKEY (to bring the broker onto the tailnet) which isn't minted here.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"tailscale.com/tsnet"
)

// identity is the verified, server-resolved caller identity we act on.
type identity struct {
	StableID string   `json:"stableID"` // unforgeable — the scoping key
	Hostname string   `json:"hostname"` // user-settable — display/logging ONLY
	Tags     []string `json:"tags"`
}

func (id identity) hasTag(want string) bool {
	for _, t := range id.Tags {
		if t == want {
			return true
		}
	}
	return false
}

// provenance records how the returned secrets were authorized — so the caller
// (and us, in logs) can see whether this was a known node or a first-contact
// bootstrap that the spike auto-trusted.
type provenance string

const (
	provKnown provenance = "known-node"         // StableID was already registered
	provTOFU  provenance = "tofu-first-contact" // brand-new node, spike auto-registered it
)

// SecretSource returns the least-privilege secret set for a node. The stub below
// is the spike; a production impl reads Bitwarden (bw get ... scoped to the node)
// and would REPLACE first-contact TOFU with pairing-token verification.
type SecretSource interface {
	SecretsFor(id identity) (map[string]string, provenance, error)
}

// stubSource is an in-memory SecretSource. Seed it with known StableIDs, or let
// unknown nodes through via TOFU when -tofu is set. Everything here is a
// placeholder — no real secret material.
type stubSource struct {
	mu    sync.Mutex
	tofu  bool
	known map[string]map[string]string // StableID -> secret map
	seen  map[string]string            // StableID -> hostname first seen (TOFU registry)
}

func newStubSource(tofu bool) *stubSource {
	return &stubSource{
		tofu:  tofu,
		known: map[string]map[string]string{},
		seen:  map[string]string{},
	}
}

func (s *stubSource) SecretsFor(id identity) (map[string]string, provenance, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if secrets, ok := s.known[id.StableID]; ok {
		return secrets, provKnown, nil
	}

	// ── Bootstrap-of-trust decision point ─────────────────────────────────
	// A node we've never issued to. In the real broker this is where a
	// one-time pairing token (conveyed by the phone at approval time) MUST be
	// verified before issuing anything. The spike instead trust-on-first-uses
	// so the end-to-end path is demonstrable — clearly labelled as such.
	if !s.tofu {
		return nil, "", errUnregistered
	}
	s.seen[id.StableID] = id.Hostname
	placeholder := map[string]string{
		"PLACEHOLDER_BOOTSTRAP_SECRET": "issued-by-spike-not-a-real-secret",
		"note":                         "production: gate this on a phone-conveyed one-time pairing token",
	}
	s.known[id.StableID] = placeholder
	return placeholder, provTOFU, nil
}

// errUnregistered is returned when a node is unknown and TOFU is off.
var errUnregistered = &brokerError{status: http.StatusForbidden, msg: "node not registered; pairing required (spike: pass -tofu to auto-register)"}

type brokerError struct {
	status int
	msg    string
}

func (e *brokerError) Error() string { return e.msg }

func main() {
	var (
		hostname   = flag.String("hostname", envOr("TS_HOSTNAME", "secret-broker"), "tailnet hostname for the broker node")
		addr       = flag.String("addr", envOr("BROKER_ADDR", ":8080"), "tailnet listen address")
		requireTag = flag.String("require-tag", envOr("BROKER_REQUIRE_TAG", "tag:fleet"), "ACL tag a caller must carry (admission gate)")
		stateDir   = flag.String("state-dir", envOr("TS_STATE_DIR", ""), "tsnet state dir (default: OS config dir)")
		tofu       = flag.Bool("tofu", os.Getenv("BROKER_TOFU") == "1", "SPIKE: trust-on-first-use for unknown nodes (stand-in for pairing tokens)")
	)
	flag.Parse()

	authKey := os.Getenv("TS_AUTHKEY")
	if authKey == "" {
		log.Println("warning: TS_AUTHKEY is empty; tsnet will prompt for interactive login on first run")
	}

	srv := &tsnet.Server{
		Hostname: *hostname,
		AuthKey:  authKey,
		Dir:      *stateDir, // empty => default per-user location
	}
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	if _, err := srv.Up(ctx); err != nil {
		log.Fatalf("tsnet did not come up: %v", err)
	}

	lc, err := srv.LocalClient()
	if err != nil {
		log.Fatalf("LocalClient: %v", err)
	}

	src := newStubSource(*tofu)

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/secrets", func(w http.ResponseWriter, r *http.Request) {
		// Resolve the WireGuard-authenticated peer. r.RemoteAddr on a tsnet
		// listener is the caller's tailnet IP:port — exactly what WhoIs wants.
		who, err := lc.WhoIs(r.Context(), r.RemoteAddr)
		if err != nil || who.Node == nil {
			log.Printf("whois failed for %s: %v", r.RemoteAddr, err)
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "could not identify caller"})
			return
		}

		id := identity{
			StableID: string(who.Node.StableID),
			Hostname: who.Node.ComputedName, // display only
			Tags:     append([]string(nil), who.Node.Tags...),
		}

		// (1) Admission gate — coarse. tag present => may reach the broker.
		if !id.hasTag(*requireTag) {
			log.Printf("deny %s (stable=%s): missing %s; tags=%v", id.Hostname, id.StableID, *requireTag, id.Tags)
			writeJSON(w, http.StatusForbidden, map[string]any{
				"error":    "missing required tag",
				"required": *requireTag,
				"identity": id,
			})
			return
		}

		// (2)+(3) Scope by unforgeable StableID; first-contact handled explicitly.
		secrets, prov, err := src.SecretsFor(id)
		if err != nil {
			status := http.StatusForbidden
			if be, ok := err.(*brokerError); ok {
				status = be.status
			}
			writeJSON(w, status, map[string]any{"error": err.Error(), "identity": id})
			return
		}

		log.Printf("issue to stable=%s host=%s prov=%s", id.StableID, id.Hostname, prov)
		writeJSON(w, http.StatusOK, map[string]any{
			// Echo the RESOLVED identity so the caller can see that scoping is by
			// stableID, and that hostname is whatever the node claimed.
			"identity":   id,
			"provenance": prov,
			"secrets":    secrets,
			"warning":    "hostname is user-settable; authorization is scoped to stableID only",
		})
	})

	// Liveness probe that doesn't leak anything.
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})

	ln, err := srv.Listen("tcp", *addr)
	if err != nil {
		log.Fatalf("tailnet listen %s: %v", *addr, err)
	}
	log.Printf("secret-broker up as %q, serving %s on the tailnet (require %s, tofu=%v)", *hostname, *addr, *requireTag, *tofu)
	log.Fatal(http.Serve(ln, mux))
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}

func envOr(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}
