package main

import (
	"crypto/sha256"
	"encoding/base32"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// ── Identity ──────────────────────────────────────────────────────────────
// The verified, server-resolved caller identity. StableID is the coordination-
// server-assigned node id and is UNFORGEABLE — it is the only field we ever
// authorize on. Hostname is user-settable (Phase 0 sets --hostname) and is kept
// for display/logging ONLY.

type identity struct {
	StableID string   `json:"stableID"`
	Hostname string   `json:"hostname"`
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

// fingerprint is a short, human-verifiable code derived from the unforgeable
// StableID. The new node prints its own; the operator sees the same value in the
// pending list and matches them out-of-band before approving (anti-MITM).
func fingerprint(stableID string) string {
	sum := sha256.Sum256([]byte(stableID))
	b32 := strings.ToUpper(base32.StdEncoding.WithPadding(base32.NoPadding).EncodeToString(sum[:]))
	return fmt.Sprintf("%s-%s-%s", b32[0:4], b32[4:8], b32[8:12])
}

// ── Decision ──────────────────────────────────────────────────────────────

type decisionKind int

const (
	// denied: not allowed, and not turned into a pending request (e.g. missing tag).
	decisionDenied decisionKind = iota
	// pending: unknown-but-eligible node; recorded, awaiting operator approval.
	decisionPending
	// authorized: operator-approved node; issue secrets.
	decisionAuthorized
)

type decision struct {
	kind        decisionKind
	reason      string
	fingerprint string // set for pending/authorized
}

// ── Approval registry ─────────────────────────────────────────────────────
// Race-free pairing: an unknown eligible node's request is QUEUED (pending) and
// the operator approves a SPECIFIC StableID (mirrors Tailscale device approval).
// We never auto-approve "the next node within a time window" — tag:fleet is
// broadly held, so a time-only window is a race; identity-bound approval is not.

type pendingReq struct {
	Identity  identity
	FirstSeen time.Time
}

type registry struct {
	mu         sync.Mutex
	now        func() time.Time
	pendingTTL time.Duration
	admins     map[string]bool       // StableID allowlist for admin ops
	approved   map[string]bool       // StableID -> approved
	pending    map[string]pendingReq // StableID -> queued request
}

func newRegistry(adminIDs []string, pendingTTL time.Duration, now func() time.Time) *registry {
	if now == nil {
		now = time.Now
	}
	admins := map[string]bool{}
	for _, a := range adminIDs {
		if a = strings.TrimSpace(a); a != "" {
			admins[a] = true
		}
	}
	return &registry{
		now:        now,
		pendingTTL: pendingTTL,
		admins:     admins,
		approved:   map[string]bool{},
		pending:    map[string]pendingReq{},
	}
}

func (r *registry) isAdmin(id identity) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.admins[id.StableID]
}

// resolve decides what to do for a node request. requireTag is the coarse
// admission gate; StableID (never hostname) is the authorization key.
func (r *registry) resolve(id identity, requireTag string) decision {
	if !id.hasTag(requireTag) {
		return decision{kind: decisionDenied, reason: "missing required tag " + requireTag}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.approved[id.StableID] {
		return decision{kind: decisionAuthorized, fingerprint: fingerprint(id.StableID)}
	}
	// Queue (or refresh) a pending request for the operator to approve.
	r.pending[id.StableID] = pendingReq{Identity: id, FirstSeen: r.now()}
	return decision{
		kind:        decisionPending,
		reason:      "awaiting operator approval",
		fingerprint: fingerprint(id.StableID),
	}
}

// approve moves a pending StableID to approved. Admin-gated by caller identity.
func (r *registry) approve(caller identity, targetStableID string) error {
	if !r.isAdmin(caller) {
		return &brokerError{status: 403, msg: "not an admin identity"}
	}
	targetStableID = strings.TrimSpace(targetStableID)
	if targetStableID == "" {
		return &brokerError{status: 400, msg: "missing target stableID"}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.approved[targetStableID] = true
	delete(r.pending, targetStableID)
	return nil
}

// listPending returns non-expired pending requests, admin-gated.
func (r *registry) listPending(caller identity) ([]pendingReq, error) {
	if !r.isAdmin(caller) {
		return nil, &brokerError{status: 403, msg: "not an admin identity"}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	out := []pendingReq{}
	for id, p := range r.pending {
		if r.pendingTTL > 0 && r.now().Sub(p.FirstSeen) > r.pendingTTL {
			delete(r.pending, id)
			continue
		}
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].FirstSeen.Before(out[j].FirstSeen) })
	return out, nil
}

// ── SecretSource ──────────────────────────────────────────────────────────
// Returns the least-privilege secret set for an authorized node. Implementations
// live in sources.go (stub for the spike; bws-backed for production).

type SecretSource interface {
	SecretsFor(id identity) (map[string]string, error)
}

// ── errors ────────────────────────────────────────────────────────────────

type brokerError struct {
	status int
	msg    string
}

func (e *brokerError) Error() string { return e.msg }

func statusOf(err error) int {
	if be, ok := err.(*brokerError); ok {
		return be.status
	}
	return 500
}
