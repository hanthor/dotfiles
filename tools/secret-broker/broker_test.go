package main

import (
	"testing"
	"time"
)

const (
	fleetTag = "tag:fleet"
	adminID  = "nADMIN000001"
	nodeA    = "nAAAA0000001"
	nodeB    = "nBBBB0000002"
)

func fleet(stableID, hostname string) identity {
	return identity{StableID: stableID, Hostname: hostname, Tags: []string{fleetTag}}
}

// A caller lacking the required tag is DENIED outright — never queued.
func TestResolve_MissingTag_Denied(t *testing.T) {
	r := newRegistry([]string{adminID}, time.Hour, time.Now)
	untagged := identity{StableID: nodeA, Hostname: "x", Tags: []string{"tag:something-else"}}
	d := r.resolve(untagged, fleetTag)
	if d.kind != decisionDenied {
		t.Fatalf("want denied, got %v (%s)", d.kind, d.reason)
	}
	if _, ok := r.pending[nodeA]; ok {
		t.Fatal("denied node must not be queued as pending")
	}
}

// An unknown but eligible node is PENDING (queued), not authorized.
func TestResolve_UnknownEligible_Pending(t *testing.T) {
	r := newRegistry([]string{adminID}, time.Hour, time.Now)
	d := r.resolve(fleet(nodeA, "kanpur"), fleetTag)
	if d.kind != decisionPending {
		t.Fatalf("want pending, got %v", d.kind)
	}
	if d.fingerprint != fingerprint(nodeA) {
		t.Fatalf("pending fingerprint mismatch")
	}
	if _, ok := r.pending[nodeA]; !ok {
		t.Fatal("pending node should be queued")
	}
}

// Approval is scoped to a SPECIFIC StableID: approving A must not authorize B.
// This is the race guard — a second node cannot ride an approval meant for another.
func TestApprove_IsIdentityScoped_NoRace(t *testing.T) {
	r := newRegistry([]string{adminID}, time.Hour, time.Now)
	r.resolve(fleet(nodeA, "kanpur"), fleetTag)
	r.resolve(fleet(nodeB, "attacker"), fleetTag)

	admin := identity{StableID: adminID, Tags: []string{fleetTag}}
	if err := r.approve(admin, nodeA); err != nil {
		t.Fatalf("approve A: %v", err)
	}
	if d := r.resolve(fleet(nodeA, "kanpur"), fleetTag); d.kind != decisionAuthorized {
		t.Fatalf("A should be authorized after approval, got %v", d.kind)
	}
	if d := r.resolve(fleet(nodeB, "attacker"), fleetTag); d.kind == decisionAuthorized {
		t.Fatal("B must NOT be authorized by A's approval (race)")
	}
}

// Only an admin StableID may approve; a non-admin (even tagged) is rejected.
func TestApprove_NonAdmin_Rejected(t *testing.T) {
	r := newRegistry([]string{adminID}, time.Hour, time.Now)
	r.resolve(fleet(nodeA, "kanpur"), fleetTag)
	nonAdmin := fleet(nodeB, "randomnode")
	if err := r.approve(nonAdmin, nodeA); err == nil {
		t.Fatal("non-admin approval must be rejected")
	}
	if statusOf(r.approve(nonAdmin, nodeA)) != 403 {
		t.Fatal("non-admin approval should be 403")
	}
	if d := r.resolve(fleet(nodeA, "kanpur"), fleetTag); d.kind == decisionAuthorized {
		t.Fatal("node must not become authorized via a rejected admin call")
	}
}

// listPending is admin-gated too.
func TestListPending_NonAdmin_Rejected(t *testing.T) {
	r := newRegistry([]string{adminID}, time.Hour, time.Now)
	r.resolve(fleet(nodeA, "kanpur"), fleetTag)
	if _, err := r.listPending(fleet(nodeB, "randomnode")); err == nil {
		t.Fatal("non-admin listPending must be rejected")
	}
}

// Expired pending requests are dropped, not surfaced or auto-approved.
func TestPending_Expires(t *testing.T) {
	now := time.Unix(1_000_000, 0)
	clock := func() time.Time { return now }
	r := newRegistry([]string{adminID}, 10*time.Minute, clock)
	r.resolve(fleet(nodeA, "kanpur"), fleetTag)

	now = now.Add(11 * time.Minute) // advance past TTL
	admin := identity{StableID: adminID, Tags: []string{fleetTag}}
	list, err := r.listPending(admin)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 0 {
		t.Fatalf("expired pending should be gone, got %d", len(list))
	}
}

// Forged hostname does not move authorization: a node claiming hostname "bihar"
// still resolves under its OWN stableID and gets nothing bihar-specific.
func TestForgedHostname_DoesNotEscalate(t *testing.T) {
	r := newRegistry([]string{adminID}, time.Hour, time.Now)
	admin := identity{StableID: adminID, Tags: []string{fleetTag}}

	// Operator approved the real bihar (nodeB) and it has a bihar-only secret.
	r.resolve(fleet(nodeB, "bihar"), fleetTag)
	if err := r.approve(admin, nodeB); err != nil {
		t.Fatal(err)
	}
	pol := policy{byStableID: map[string][]secretRef{
		nodeB: {{Name: "bihar-only", SMID: "sm-bihar"}},
	}}
	src := stubSource{pol: pol}

	// Attacker node (nodeA) sets --hostname=bihar but is a different stableID.
	attacker := identity{StableID: nodeA, Hostname: "bihar", Tags: []string{fleetTag}}
	r.resolve(attacker, fleetTag)
	if err := r.approve(admin, nodeA); err != nil { // even if somehow approved,
		t.Fatal(err)
	}
	got, err := src.SecretsFor(attacker)
	if err != nil {
		t.Fatal(err)
	}
	if _, leaked := got["bihar-only"]; leaked {
		t.Fatal("attacker claiming hostname bihar must NOT receive bihar's secrets")
	}
}

// Policy is least-privilege: a node receives only its refs (plus defaults).
func TestPolicy_LeastPrivilege(t *testing.T) {
	pol := policy{
		byStableID: map[string][]secretRef{
			nodeA: {{Name: "kubeconfig", SMID: "sm-kube"}},
		},
		def: []secretRef{{Name: "ts-authkey", SMID: "sm-ts"}},
	}
	src := stubSource{pol: pol}

	a, _ := src.SecretsFor(fleet(nodeA, "kanpur"))
	if _, ok := a["kubeconfig"]; !ok {
		t.Fatal("nodeA should get its kubeconfig")
	}
	if _, ok := a["ts-authkey"]; !ok {
		t.Fatal("nodeA should get the default ts-authkey")
	}
	b, _ := src.SecretsFor(fleet(nodeB, "other"))
	if _, ok := b["kubeconfig"]; ok {
		t.Fatal("nodeB must NOT get nodeA's kubeconfig")
	}
	if _, ok := b["ts-authkey"]; !ok {
		t.Fatal("nodeB should still get the default")
	}
}
