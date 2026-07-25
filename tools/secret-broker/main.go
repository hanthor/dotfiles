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
// The secret source is pluggable: -source=stub (placeholders) or -source=bw
// (regular Bitwarden vault via the `bw` CLI, using a BW_SESSION; self-heals an
// expired session via BW_PASSWORD). Secrets Manager (paid) is intentionally not
// used.
//
// Blast radius: the broker holds unattended vault access, so compromising the
// broker host exposes every secret it can serve — and with -source=bw a standing
// master password lives on the host. Shrink the read scope by pointing the
// broker's `bw` account at a dedicated collection (see README). Deliberate,
// documented tradeoff. Keep the client manual/opt-in until it has been run live.
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
	"os/signal"
	"strings"
	"syscall"
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
		sourceKind = flag.String("source", envOr("BROKER_SOURCE", "stub"), "secret source: stub|bw")
		adminCSV   = flag.String("admins", os.Getenv("BROKER_ADMINS"), "comma-separated StableNodeIDs allowed to approve nodes")
		pendingTTL = flag.Duration("pending-ttl", 30*time.Minute, "how long a pending (unapproved) request is kept")
		configPath = flag.String("config", envOr("BROKER_CONFIG", ""), "path to per-node policy JSON (see policy.example.json)")
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

	// Per-node policy. Loaded from -config if set, else empty (a node then
	// authorizes but receives an empty secret set — safe default).
	pol := policy{byStableID: map[string][]secretRef{}, def: nil}
	if *configPath != "" {
		loaded, perr := loadPolicy(*configPath)
		if perr != nil {
			log.Fatalf("load policy: %v", perr)
		}
		pol = loaded
		log.Printf("loaded policy: %d node(s), %d default ref(s)", len(pol.byStableID), len(pol.def))
	}
	var src SecretSource
	switch *sourceKind {
	case "bw":
		src = newBwSource(pol, os.Getenv("BW_BIN"), 15*time.Second)
	case "stub":
		src = stubSource{pol: pol}
	default:
		log.Fatalf("unknown -source %q (want stub|bw)", *sourceKind)
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

	h := &handler{resolveID: tsnetResolver(lc), reg: reg, src: src, requireTag: *requireTag}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/secrets", h.getSecrets)
	mux.HandleFunc("/v1/whoami", h.whoami)
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

	// Graceful shutdown: drain HTTP then deregister the tsnet node (matters most
	// for ephemeral auth keys — the node should leave the tailnet cleanly).
	httpSrv := &http.Server{Handler: mux}
	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
		<-sig
		log.Println("shutting down...")
		sctx, scancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer scancel()
		_ = httpSrv.Shutdown(sctx)
	}()
	if err := httpSrv.Serve(ln); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

// handler holds the request-scoped dependencies. Identity resolution is injected
// (resolveID) so the HTTP layer never trusts caller-asserted identity and can be
// tested with a fake resolver in handler_test.go.
type handler struct {
	resolveID  func(*http.Request) (identity, error)
	reg        *registry
	src        SecretSource
	requireTag string
}

// tsnetResolver resolves the WireGuard-authenticated caller via WhoIs.
// r.RemoteAddr on a tsnet listener is the caller's tailnet IP:port.
func tsnetResolver(lc *local.Client) func(*http.Request) (identity, error) {
	return func(r *http.Request) (identity, error) {
		who, err := lc.WhoIs(r.Context(), r.RemoteAddr)
		if err != nil || who.Node == nil {
			return identity{}, &brokerError{status: http.StatusForbidden, msg: "could not identify caller"}
		}
		return identity{
			StableID: string(who.Node.StableID),
			Hostname: who.Node.ComputedName, // display only
			Tags:     append([]string(nil), who.Node.Tags...),
		}, nil
	}
}

func (h *handler) getSecrets(w http.ResponseWriter, r *http.Request) {
	id, err := h.resolveID(r)
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

// whoami echoes the caller's broker-visible identity + fingerprint. Useful during
// onboarding: the node sees exactly what the broker will authorize on (its
// StableID, not its hostname) and the fingerprint to match against the pending list.
func (h *handler) whoami(w http.ResponseWriter, r *http.Request) {
	id, err := h.resolveID(r)
	if err != nil {
		writeJSON(w, statusOf(err), map[string]any{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"identity":       id,
		"fingerprint":    fingerprint(id.StableID),
		"hasRequiredTag": id.hasTag(h.requireTag),
	})
}

func (h *handler) adminPending(w http.ResponseWriter, r *http.Request) {
	id, err := h.resolveID(r)
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
	id, err := h.resolveID(r)
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
