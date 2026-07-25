package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// newTestHandler wires a handler whose identity resolver returns a fixed identity
// (as if WhoIs had authenticated that caller), so we can exercise the real HTTP
// surface — status codes on the deny paths — without a tailnet.
func newTestHandler(caller identity, admins []string, src SecretSource) (*handler, *registry) {
	reg := newRegistry(admins, time.Hour, time.Now)
	h := &handler{
		resolveID:  func(*http.Request) (identity, error) { return caller, nil },
		reg:        reg,
		src:        src,
		requireTag: fleetTag,
	}
	return h, reg
}

func do(h http.HandlerFunc, method, url string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h(rec, httptest.NewRequest(method, url, nil))
	return rec
}

// Untagged caller hitting /v1/secrets gets 403 (admission gate), not queued.
func TestHTTP_Secrets_UntaggedForbidden(t *testing.T) {
	caller := identity{StableID: nodeA, Hostname: "x", Tags: []string{"tag:other"}}
	h, reg := newTestHandler(caller, []string{adminID}, stubSource{})
	if got := do(h.getSecrets, "GET", "/v1/secrets").Code; got != http.StatusForbidden {
		t.Fatalf("want 403, got %d", got)
	}
	if _, ok := reg.pending[nodeA]; ok {
		t.Fatal("untagged caller must not be queued")
	}
}

// Unknown eligible caller gets 202 Accepted (pending), not secrets.
func TestHTTP_Secrets_UnknownPending(t *testing.T) {
	h, _ := newTestHandler(fleet(nodeA, "kanpur"), []string{adminID}, stubSource{})
	if got := do(h.getSecrets, "GET", "/v1/secrets").Code; got != http.StatusAccepted {
		t.Fatalf("want 202, got %d", got)
	}
}

// Full flow over HTTP: pending -> admin approves -> 200 with secrets.
func TestHTTP_ApproveFlow(t *testing.T) {
	pol := policy{byStableID: map[string][]secretRef{nodeA: {{Name: "k", Item: "k-item"}}}}
	node := fleet(nodeA, "kanpur")
	nodeH, reg := newTestHandler(node, []string{adminID}, stubSource{pol: pol})

	if got := do(nodeH.getSecrets, "GET", "/v1/secrets").Code; got != http.StatusAccepted {
		t.Fatalf("pre-approval want 202, got %d", got)
	}

	// Admin handler shares the same registry but resolves to the admin identity.
	adminH := &handler{
		resolveID: func(*http.Request) (identity, error) {
			return identity{StableID: adminID, Tags: []string{fleetTag}}, nil
		},
		reg:        reg,
		src:        stubSource{pol: pol},
		requireTag: fleetTag,
	}
	if got := do(adminH.adminApprove, "POST", "/v1/admin/approve?id="+nodeA).Code; got != http.StatusOK {
		t.Fatalf("approve want 200, got %d", got)
	}
	if got := do(nodeH.getSecrets, "GET", "/v1/secrets").Code; got != http.StatusOK {
		t.Fatalf("post-approval want 200, got %d", got)
	}
}

// whoami echoes the caller's own identity + fingerprint (no auth needed).
func TestHTTP_Whoami(t *testing.T) {
	caller := fleet(nodeA, "kanpur")
	h, _ := newTestHandler(caller, []string{adminID}, stubSource{})
	rec := do(h.whoami, "GET", "/v1/whoami")
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", rec.Code)
	}
	if body := rec.Body.String(); !strings.Contains(body, fingerprint(nodeA)) {
		t.Fatalf("whoami body should include the fingerprint; got %s", body)
	}
}

// A non-admin caller cannot approve over HTTP.
func TestHTTP_Approve_NonAdminForbidden(t *testing.T) {
	h, _ := newTestHandler(fleet(nodeB, "randomnode"), []string{adminID}, stubSource{})
	if got := do(h.adminApprove, "POST", "/v1/admin/approve?id="+nodeA).Code; got != http.StatusForbidden {
		t.Fatalf("want 403, got %d", got)
	}
}

// A non-admin caller cannot list pending over HTTP.
func TestHTTP_Pending_NonAdminForbidden(t *testing.T) {
	h, _ := newTestHandler(fleet(nodeB, "randomnode"), []string{adminID}, stubSource{})
	if got := do(h.adminPending, "GET", "/v1/admin/pending").Code; got != http.StatusForbidden {
		t.Fatalf("want 403, got %d", got)
	}
}

// approve rejects non-POST methods.
func TestHTTP_Approve_WrongMethod(t *testing.T) {
	h, _ := newTestHandler(identity{StableID: adminID, Tags: []string{fleetTag}}, []string{adminID}, stubSource{})
	if got := do(h.adminApprove, "GET", "/v1/admin/approve?id="+nodeA).Code; got != http.StatusMethodNotAllowed {
		t.Fatalf("want 405, got %d", got)
	}
}
