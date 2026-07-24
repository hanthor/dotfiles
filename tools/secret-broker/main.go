// Command secret-broker is the Phase 1 tailnet identity secret broker for QR
// secret onboarding (issue #49). Design: docs/src/qr-onboarding.md.
//
// It joins the tailnet as its own node (tsnet) and serves secrets over the
// tailnet ONLY. For each request it resolves the caller's *verified* identity
// with LocalClient().WhoIs (the WireGuard-authenticated peer, not anything the
// caller asserts) and enforces:
//
//   - admission by ACL tag (default tag:fleet) — coarse reachability gate;
//   - authorization scoped to the UNFORGEABLE StableNodeID, never hostname
//     (Phase 0 sets --hostname and it is user-settable);
//   - race-free pairing: an unknown eligible node is QUEUED and the operator
//     approves that specific StableID (mirrors Tailscale device approval).
//
// The secret source is pluggable: -source=stub (spike, placeholders) or
// -source=bws (Bitwarden Secrets Manager via the `bws` CLI, read-scoped machine
// account token in BWS_ACCESS_TOKEN — no vault master password).
//
// Blast radius: even with a read-scoped SM token, compromising the broker host
// exposes every secret it can serve. This is a deliberate, documented tradeoff
// (see README "Blast radius"). Keep the client a manual, opt-in recipe — do not
// wire it into `just apply`/onboarding until it has been run live.
//
// Verification status: builds + vets; the pure gating logic is unit-tested
// (broker_test.go). Not run end-to-end — a live run needs a TS_AUTHKEY and a
// real BWS token, provisioned per the README runbook.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"tailscale.com/client/local"
	"tailscale.com/tsnet"
)

func main() {
	var (
		hostname   = flag.String("hostname", envOr("TS_HOSTNAME", "secret-broker"), "tailnet hostname for the broker node")
		addr       = flag.String("addr", envOr("BROKER_ADDR", ":8080"), "tailnet listen address")
		requireTag = flag.String("require-tag", envOr("BROKER_REQUIRE_TAG", "tag:fleet"), "ACL tag a caller must carry (admission gate)")
		stateDir   = flag.String("state-dir", envOr("TS_STATE_DIR", ""), "tsnet state dir (default: OS config dir)")
		sourceKind = flag.String("source", envOr("BROKER_SOURCE", "stub"), "secret source: stub|bws")
		adminCSV   = flag.String("admins", os.Getenv("BROKER_ADMINS"), "comma-separated StableNodeIDs allowed to approve nodes")
		pendingTTL = flag.Duration("pending-ttl", 30*time.Minute, "how long a pending (unapproved) request is kept")
	)
	flag.Parse()

	authKey := os.Getenv("TS_AUTHKEY")
	if authKey == "" {
		log.Println("warning: TS_AUTHKEY is empty; tsnet will prompt for interactive login on first run")
	}

	reg := newRegistry(splitCSV(*adminCSV), *pendingTTL, time.Now)
	if len(reg.admins) == 0 {
		log.Println("warning: no -admins set; approvals will be rejected until an admin StableID is configured")
	}

	// Secret source. Policy is empty by default — provision it per the runbook.
	// A node with no policy entries authorizes but receives an empty secret set.
	pol := policy{byStableID: map[string][]secretRef{}, def: nil}
	var src SecretSource
	switch *sourceKind {
	case "bws":
		src = newBwsSource(pol, os.Getenv("BWS_BIN"), 10*time.Second)
	case "stub":
		src = stubSource{pol: pol}
	default:
		log.Fatalf("unknown -source %q (want stub|bws)", *sourceKind)
	}

	srv := &tsnet.Server{Hostname: *hostname, AuthKey: authKey, Dir: *stateDir}
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

	h := &handler{lc: lc, reg: reg, src: src, requireTag: *requireTag}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/secrets", h.getSecrets)
	mux.HandleFunc("/v1/admin/pending", h.adminPending)
	mux.HandleFunc("/v1/admin/approve", h.adminApprove)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})

	ln, err := srv.Listen("tcp", *addr)
	if err != nil {
		log.Fatalf("tailnet listen %s: %v", *addr, err)
	}
	log.Printf("secret-broker up as %q on %s (source=%s require=%s admins=%d)", *hostname, *addr, *sourceKind, *requireTag, len(reg.admins))
	log.Fatal(http.Serve(ln, mux))
}

// handler holds the request-scoped dependencies. Identity resolution goes
// through whois so the HTTP layer never trusts caller-asserted identity.
type handler struct {
	lc         *local.Client
	reg        *registry
	src        SecretSource
	requireTag string
}

// whois resolves the WireGuard-authenticated caller. r.RemoteAddr on a tsnet
// listener is the caller's tailnet IP:port — exactly what WhoIs expects.
func (h *handler) whois(r *http.Request) (identity, error) {
	who, err := h.lc.WhoIs(r.Context(), r.RemoteAddr)
	if err != nil || who.Node == nil {
		return identity{}, &brokerError{status: http.StatusForbidden, msg: "could not identify caller"}
	}
	return identity{
		StableID: string(who.Node.StableID),
		Hostname: who.Node.ComputedName, // display only
		Tags:     append([]string(nil), who.Node.Tags...),
	}, nil
}

func (h *handler) getSecrets(w http.ResponseWriter, r *http.Request) {
	id, err := h.whois(r)
	if err != nil {
		writeJSON(w, statusOf(err), map[string]any{"error": err.Error()})
		return
	}
	d := h.reg.resolve(id, h.requireTag)
	switch d.kind {
	case decisionDenied:
		log.Printf("deny stable=%s host=%s: %s", id.StableID, id.Hostname, d.reason)
		writeJSON(w, http.StatusForbidden, map[string]any{"error": d.reason, "identity": id})
	case decisionPending:
		log.Printf("pending stable=%s host=%s fp=%s", id.StableID, id.Hostname, d.fingerprint)
		writeJSON(w, http.StatusAccepted, map[string]any{
			"status":      "pending",
			"message":     "awaiting operator approval; verify the fingerprint matches, then approve this stableID",
			"identity":    id,
			"fingerprint": d.fingerprint,
		})
	case decisionAuthorized:
		secrets, serr := h.src.SecretsFor(id)
		if serr != nil {
			writeJSON(w, statusOf(serr), map[string]any{"error": serr.Error(), "identity": id})
			return
		}
		log.Printf("issue stable=%s host=%s n=%d", id.StableID, id.Hostname, len(secrets))
		writeJSON(w, http.StatusOK, map[string]any{
			"identity":    id,
			"secrets":     secrets,
			"fingerprint": d.fingerprint,
			"warning":     "hostname is user-settable; authorization is scoped to stableID only",
		})
	}
}

func (h *handler) adminPending(w http.ResponseWriter, r *http.Request) {
	id, err := h.whois(r)
	if err != nil {
		writeJSON(w, statusOf(err), map[string]any{"error": err.Error()})
		return
	}
	list, aerr := h.reg.listPending(id)
	if aerr != nil {
		writeJSON(w, statusOf(aerr), map[string]any{"error": aerr.Error()})
		return
	}
	out := make([]map[string]any, 0, len(list))
	for _, p := range list {
		out = append(out, map[string]any{
			"stableID":    p.Identity.StableID,
			"hostname":    p.Identity.Hostname,
			"tags":        p.Identity.Tags,
			"fingerprint": fingerprint(p.Identity.StableID),
			"firstSeen":   p.FirstSeen.Format(time.RFC3339),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"pending": out})
}

func (h *handler) adminApprove(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "use POST"})
		return
	}
	id, err := h.whois(r)
	if err != nil {
		writeJSON(w, statusOf(err), map[string]any{"error": err.Error()})
		return
	}
	target := r.URL.Query().Get("id")
	if aerr := h.reg.approve(id, target); aerr != nil {
		writeJSON(w, statusOf(aerr), map[string]any{"error": aerr.Error()})
		return
	}
	log.Printf("approve by admin=%s target=%s", id.StableID, target)
	writeJSON(w, http.StatusOK, map[string]any{"approved": target})
}

// ── helpers ───────────────────────────────────────────────────────────────

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

func splitCSV(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
