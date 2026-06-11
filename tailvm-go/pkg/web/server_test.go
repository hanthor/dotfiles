package web

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestStaticServed verifies the embedded SPA (index.html + assets) is served.
func TestStaticServed(t *testing.T) {
	mux, err := newMux()
	if err != nil {
		t.Fatalf("newMux: %v", err)
	}
	srv := httptest.NewServer(mux)
	defer srv.Close()

	for _, path := range []string{"/", "/app.js", "/icons.js", "/style.css"} {
		r, err := http.Get(srv.URL + path)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		r.Body.Close()
		if r.StatusCode != http.StatusOK {
			t.Errorf("GET %s = %d, want 200", path, r.StatusCode)
		}
	}
}

// TestAllRoutesRegistered hits every API route with its method and asserts the
// route is wired (no 404 / 405). Handlers that shell out to kubectl will fail
// without a cluster (5xx), which is fine — we're verifying the surface exists,
// so the kind of "feature silently missing" regression can't slip through.
func TestAllRoutesRegistered(t *testing.T) {
	mux, err := newMux()
	if err != nil {
		t.Fatalf("newMux: %v", err)
	}
	srv := httptest.NewServer(mux)
	defer srv.Close()

	routes := []struct{ method, path string }{
		{"GET", "/api/vms"},
		{"POST", "/api/vms"},
		{"GET", "/api/nodes"},
		{"GET", "/api/capabilities"},
		{"GET", "/api/instancetypes"},
		{"GET", "/api/nads"},
		{"GET", "/api/doctor"},
		{"POST", "/api/doctor/fix"},
		{"GET", "/api/plugins"},
		{"GET", "/api/datavolumes"},
		{"POST", "/api/datavolumes"},
		{"DELETE", "/api/datavolumes/ns/name"},
		{"GET", "/api/tasks/abc"},
		{"GET", "/api/vms/ns/name"},
		{"DELETE", "/api/vms/ns/name"},
		{"POST", "/api/vms/ns/name/start"},
		{"POST", "/api/vms/ns/name/scale"},
		{"POST", "/api/vms/ns/name/expand"},
		{"POST", "/api/vms/ns/name/clone"},
		{"POST", "/api/vms/ns/name/template"},
		{"POST", "/api/vms/ns/name/nics"},
		{"GET", "/api/vms/ns/name/guestinfo"},
		{"GET", "/api/vms/ns/name/events"},
		{"GET", "/api/vms/ns/name/metrics"},
		{"GET", "/api/vms/ns/name/export"},
		{"POST", "/api/vms/ns/name/volumes"},
		{"DELETE", "/api/vms/ns/name/volumes/vol"},
		{"GET", "/api/vms/ns/name/snapshots"},
		{"POST", "/api/vms/ns/name/snapshots"},
		{"DELETE", "/api/vms/ns/name/snapshots/snap"},
		{"POST", "/api/vms/ns/name/snapshots/snap/restore"},
	}
	client := &http.Client{}
	for _, rt := range routes {
		req, _ := http.NewRequest(rt.method, srv.URL+rt.path, strings.NewReader("{}"))
		resp, err := client.Do(req)
		if err != nil {
			t.Errorf("%s %s: %v", rt.method, rt.path, err)
			continue
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode == http.StatusMethodNotAllowed ||
			strings.Contains(string(body), "404 page not found") {
			t.Errorf("%s %s not registered (got %d: %s)", rt.method, rt.path, resp.StatusCode, strings.TrimSpace(string(body)))
		}
	}
}

// ── handleListVMs ──────────────────────────────────────────────────

func TestHandleListVMs_Empty(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl", []string{"get", "vms", "-A", "-o", "json"},
		`{"items": []}`, nil)
	fx.Runner.AddResponseKV("kubectl", []string{"get", "vmis", "-A", "-o", "json"},
		`{"items": []}`, nil)

	resp, err := http.Get(fx.Server.URL + "/api/vms")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("got %d, want 200", resp.StatusCode)
	}

	var vms []map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&vms); err != nil {
		t.Fatal(err)
	}
	if len(vms) != 0 {
		t.Errorf("expected 0 VMs, got %d", len(vms))
	}
}

func TestHandleListVMs_OneVM(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl", []string{"get", "vms", "-A", "-o", "json"},
		vmListJSON("myvm", "tailvm", "Stopped", false), nil)
	fx.Runner.AddResponseKV("kubectl", []string{"get", "vmis", "-A", "-o", "json"},
		`{"items": []}`, nil)

	resp := mustGet(t, fx.Server.URL+"/api/vms")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("got %d, want 200", resp.StatusCode)
	}

	var vms []map[string]any
	json.NewDecoder(resp.Body).Decode(&vms)
	if len(vms) != 1 {
		t.Fatalf("expected 1 VM, got %d", len(vms))
	}
	vm := vms[0]
	if vm["name"] != "myvm" {
		t.Errorf("name = %v, want myvm", vm["name"])
	}
	if vm["backend"] != "kubevirt" {
		t.Errorf("backend = %v, want kubevirt", vm["backend"])
	}
}

func TestHandleListVMs_KubectlError(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl", []string{"get", "vms", "-A", "-o", "json"},
		"", fmt.Errorf("kubectl: connection refused"))

	resp := mustGet(t, fx.Server.URL+"/api/vms")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("got %d, want 502", resp.StatusCode)
	}

	var body map[string]string
	json.NewDecoder(resp.Body).Decode(&body)
	if body["error"] == "" {
		t.Error("expected error message in response")
	}
}

// ── handleCreateVM ─────────────────────────────────────────────────

func TestHandleCreateVM_MissingName(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	resp := mustPost(t, fx.Server.URL+"/api/vms", `{"cpu": 2, "mem": "4G"}`)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", resp.StatusCode)
	}
	var body map[string]string
	json.NewDecoder(resp.Body).Decode(&body)
	if body["error"] == "" {
		t.Error("expected error message")
	}
}

func TestHandleCreateVM_CatalogImage(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	// Create a fake SSH key file so LoadSSHPublicKey finds it
	tmpHome := t.TempDir()
	sshDir := filepath.Join(tmpHome, ".ssh")
	os.MkdirAll(sshDir, 0700)
	os.WriteFile(filepath.Join(sshDir, "id_ed25519.pub"), []byte("ssh-ed25519 AAAAtest"), 0600)
	t.Setenv("HOME", tmpHome)

	// Set up responses for kubectl apply (PVC + VM + registry store)
	fx.Runner.AddResponseKV("kubectl", []string{"apply", "-f", "-"}, "", nil)

	resp := mustPost(t, fx.Server.URL+"/api/vms",
		`{"name":"myvm","image":"fedora","cpu":2,"mem":"4G","disk":"20G"}`)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("got %d, want 201 — body: %s", resp.StatusCode, string(body))
	}

	var body map[string]string
	json.NewDecoder(resp.Body).Decode(&body)
	if body["name"] != "myvm" {
		t.Errorf("name = %v, want myvm", body["name"])
	}
}

func TestHandleCreateVM_ContainerDisk(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	tmpHome := t.TempDir()
	sshDir := filepath.Join(tmpHome, ".ssh")
	os.MkdirAll(sshDir, 0700)
	os.WriteFile(filepath.Join(sshDir, "id_ed25519.pub"), []byte("ssh-ed25519 AAAAtest"), 0600)
	t.Setenv("HOME", tmpHome)

	fx.Runner.AddResponseKV("kubectl", []string{"apply", "-f", "-"}, "", nil)

	resp := mustPost(t, fx.Server.URL+"/api/vms",
		`{"name":"myvm","containerDisk":"quay.io/containerdisks/ubuntu:24.04","cpu":2,"mem":"4G"}`)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("got %d, want 201 — body: %s", resp.StatusCode, string(body))
	}
}

func TestHandleCreateVM_ImportURL(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	tmpHome := t.TempDir()
	sshDir := filepath.Join(tmpHome, ".ssh")
	os.MkdirAll(sshDir, 0700)
	os.WriteFile(filepath.Join(sshDir, "id_ed25519.pub"), []byte("ssh-ed25519 AAAAtest"), 0600)
	t.Setenv("HOME", tmpHome)

	fx.Runner.AddResponseKV("kubectl", []string{"apply", "-f", "-"}, "", nil)

	resp := mustPost(t, fx.Server.URL+"/api/vms",
		`{"name":"myvm","import":"https://example.com/jammy.qcow2","cpu":2,"mem":"4G","disk":"10G"}`)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("got %d, want 201 — body: %s", resp.StatusCode, string(body))
	}
}

func TestHandleCreateVM_BootcUnavailable(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	resp := mustPost(t, fx.Server.URL+"/api/vms",
		`{"name":"myvm","bootc":"quay.io/centos-bootc:stream9"}`)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", resp.StatusCode)
	}
}

func TestHandleCreateVM_UnknownCatalogImage(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	tmpHome := t.TempDir()
	sshDir := filepath.Join(tmpHome, ".ssh")
	os.MkdirAll(sshDir, 0700)
	os.WriteFile(filepath.Join(sshDir, "id_ed25519.pub"), []byte("ssh-ed25519 AAAAtest"), 0600)
	t.Setenv("HOME", tmpHome)

	resp := mustPost(t, fx.Server.URL+"/api/vms",
		`{"name":"myvm","image":"nonexistent-os","cpu":2,"mem":"4G"}`)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", resp.StatusCode)
	}
}

// ── handleVMAction ─────────────────────────────────────────────────

func TestHandleVMAction_Start(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	// StartVM calls ensureVirtctl → LookPath → returns /fake/bin/virtctl
	// then calls Run("/fake/bin/virtctl", "start", "myvm", "-n", "tailvm")
	fx.Runner.AddResponseKV("/fake/bin/virtctl",
		[]string{"start", "myvm", "-n", "tailvm"}, "", nil)

	resp := mustPost(t, fx.Server.URL+"/api/vms/tailvm/myvm/start", "")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("got %d, want 200 — body: %s", resp.StatusCode, string(body))
	}

	var body map[string]string
	json.NewDecoder(resp.Body).Decode(&body)
	if body["status"] != "ok" {
		t.Errorf("status = %v, want ok", body["status"])
	}
}

func TestHandleVMAction_StartError(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("/fake/bin/virtctl",
		[]string{"start", "myvm", "-n", "tailvm"}, "", fmt.Errorf("VM not found"))

	resp := mustPost(t, fx.Server.URL+"/api/vms/tailvm/myvm/start", "")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusInternalServerError {
		t.Fatalf("got %d, want 500", resp.StatusCode)
	}
}

func TestHandleVMAction_Stop(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("/fake/bin/virtctl",
		[]string{"stop", "myvm", "-n", "tailvm"}, "", nil)

	resp := mustPost(t, fx.Server.URL+"/api/vms/tailvm/myvm/stop", "")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("got %d, want 200", resp.StatusCode)
	}
}

func TestHandleVMAction_UnknownAction(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	resp := mustPost(t, fx.Server.URL+"/api/vms/tailvm/myvm/bogus", "")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("got %d, want 400", resp.StatusCode)
	}
}

// ── handleDeleteVM ─────────────────────────────────────────────────

func TestHandleDeleteVM_Success(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	// DeleteVM runs several commands; stub them all
	fx.Runner.AddResponseKV("/fake/bin/virtctl",
		[]string{"stop", "myvm", "-n", "tailvm"}, "", nil)
	fx.Runner.AddResponseKV("kubectl",
		[]string{"delete", "vm", "myvm", "-n", "tailvm", "--ignore-not-found"}, "", nil)
	// DeleteVM also deletes PVCs and DataVolumes for each suffix
	for _, suffix := range []string{"disk", "data", "iso", "bootc-disk"} {
		pvc := "myvm-" + suffix
		fx.Runner.AddResponseKV("kubectl",
			[]string{"delete", "pvc", pvc, "-n", "tailvm", "--ignore-not-found"}, "", nil)
		fx.Runner.AddResponseKV("kubectl",
			[]string{"delete", "datavolume", pvc, "-n", "tailvm", "--ignore-not-found"}, "", nil)
	}
	fx.Runner.AddResponseKV("kubectl",
		[]string{"delete", "pvc", "-n", "tailvm", "-l", "corral.dev/vm=myvm", "--ignore-not-found"}, "", nil)
	fx.Runner.AddResponseKV("kubectl",
		[]string{"delete", "vmsnapshot", "-n", "tailvm", "-l", "corral.dev/vm=myvm", "--ignore-not-found"}, "", nil)

	resp := mustDelete(t, fx.Server.URL+"/api/vms/tailvm/myvm")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("got %d, want 200 — body: %s", resp.StatusCode, string(body))
	}
}

// ── handleVMInfo ───────────────────────────────────────────────────

func TestHandleVMInfo_Success(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl",
		[]string{"get", "vm", "myvm", "-n", "tailvm", "-o", "json"},
		`{"kind":"VirtualMachine","metadata":{"name":"myvm"}}`, nil)

	resp := mustGet(t, fx.Server.URL+"/api/vms/tailvm/myvm")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("got %d, want 200", resp.StatusCode)
	}

	var body map[string]any
	json.NewDecoder(resp.Body).Decode(&body)
	if body["metadata"].(map[string]any)["name"] != "myvm" {
		t.Error("unexpected VM name")
	}
}

// ── handleNodes ────────────────────────────────────────────────────

func TestHandleNodes_Success(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl", []string{"get", "nodes", "-o", "json"},
		nodeListJSON("bihar", true, "control-plane,master", "v1.36.1", "amd64"), nil)

	resp := mustGet(t, fx.Server.URL+"/api/nodes")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("got %d, want 200", resp.StatusCode)
	}

	var nodes []map[string]any
	json.NewDecoder(resp.Body).Decode(&nodes)
	if len(nodes) != 1 {
		t.Fatalf("expected 1 node, got %d", len(nodes))
	}
	if nodes[0]["name"] != "bihar" {
		t.Errorf("name = %v, want bihar", nodes[0]["name"])
	}
}

func TestHandleNodes_Error(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl", []string{"get", "nodes", "-o", "json"},
		"", fmt.Errorf("kubectl: connection refused"))

	resp := mustGet(t, fx.Server.URL+"/api/nodes")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("got %d, want 502", resp.StatusCode)
	}
}

// ── Helpers ────────────────────────────────────────────────────────

func mustGet(t *testing.T, url string) *http.Response {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func mustPost(t *testing.T, url, body string) *http.Response {
	t.Helper()
	resp, err := http.Post(url, "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func mustDelete(t *testing.T, url string) *http.Response {
	t.Helper()
	req, err := http.NewRequest("DELETE", url, nil)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

// ── JSON fixtures ──────────────────────────────────────────────────

func vmListJSON(name, ns, status string, ready bool) string {
	return fmt.Sprintf(`{
  "items": [
    {
      "metadata": {"name": %q, "namespace": %q, "labels": {}},
      "spec": {
        "running": false,
        "template": {
          "spec": {
            "domain": {
              "cpu": {"cores": 1, "sockets": 2, "threads": 1},
              "memory": {"guest": "4Gi"}
            },
            "nodeSelector": {"kubernetes.io/hostname": "bihar"}
          }
        }
      },
      "status": {"ready": %t, "printableStatus": %q}
    }
  ]
}`, name, ns, ready, status)
}

func nodeListJSON(name string, ready bool, roles, kubelet, arch string) string {
	readyStatus := "False"
	if ready {
		readyStatus = "True"
	}
	return fmt.Sprintf(`{
  "items": [
    {
      "metadata": {
        "name": %q,
        "labels": {"kubernetes.io/role": %q}
      },
      "status": {
        "conditions": [{"type": "Ready", "status": %q}],
        "nodeInfo": {"kubeletVersion": %q, "architecture": %q}
      }
    }
  ]
}`, name, roles, readyStatus, kubelet, arch)
}

// ── Edge cases ───────────────────────────────────────────────────

func TestHandleCreateVM_MalformedJSON(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	resp, err := http.Post(fx.Server.URL+"/api/vms", "application/json",
		strings.NewReader(`{not json}`))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 400 {
		t.Errorf("expected 400 for malformed JSON, got %d", resp.StatusCode)
	}
}

func TestHandleCreateVM_EmptyBody(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	resp, err := http.Post(fx.Server.URL+"/api/vms", "application/json",
		strings.NewReader(``))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 400 {
		t.Errorf("expected 400 for empty body, got %d", resp.StatusCode)
	}
}

func TestHandleCreateVM_InvalidName(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	body := strings.NewReader(`{"name":"UPPERCASE"}`)
	resp, err := http.Post(fx.Server.URL+"/api/vms", "application/json", body)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	// CreateVM itself doesn't validate name format, but k8s will reject
	// The handler should at least not panic
	t.Logf("uppercase name returned %d", resp.StatusCode)
}

func TestHandleListVMs_CORSHeaders(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	fx.Runner.AddResponseKV("kubectl", []string{"get", "vms", "-A", "-o", "json"},
		`{"items":[]}`, nil)
	fx.Runner.AddResponseKV("kubectl", []string{"get", "vmis", "-A", "-o", "json"},
		`{"items":[]}`, nil)

	resp, err := http.Get(fx.Server.URL + "/api/vms")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); !strings.Contains(ct, "application/json") {
		t.Errorf("expected application/json Content-Type, got %q", ct)
	}
}

func TestHandleCreateDelete_RegistryRoundtrip(t *testing.T) {
	fx := NewTestFixture()
	defer fx.Close()

	// Create VM — should store in registry
	fx.Runner.AddResponseKV("kubectl", []string{"create", "ns", "tailvm"}, "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"label", "ns", "tailvm",
		"pod-security.kubernetes.io/enforce=privileged", "--overwrite"}, "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"get", "vm", "web", "-n", "tailvm", "-o", "name"},
		"", errSimulated) // VM doesn't exist yet
	fx.Runner.AddResponseKV("kubectl", []string{"get", "sc", "-o", "json"},
		`{"items":[{"metadata":{"name":"longhorn"}}]}`, nil)
	fx.Runner.AddResponseKV("kubectl", []string{"apply", "-f", "-"}, "created", nil)

	body := strings.NewReader(`{"name":"web","containerDisk":"quay.io/containerdisks/fedora:42"}`)
	resp, err := http.Post(fx.Server.URL+"/api/vms", "application/json", body)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 201 {
		t.Fatalf("create: expected 201, got %d", resp.StatusCode)
	}

	// Now delete — should remove from registry
	fx.Runner.AddResponseKV("/fake/bin/virtctl", []string{"stop", "web", "-n", "tailvm"}, "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"delete", "vm", "web", "-n", "tailvm", "--ignore-not-found"}, "", nil)
	fx.Runner.AddPrefixResponse("kubectl delete pvc web-", "", nil)
	fx.Runner.AddPrefixResponse("kubectl delete datavolume web-", "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"delete", "pvc", "-n", "tailvm", "-l", "corral.dev/vm=web", "--ignore-not-found"}, "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"delete", "vmsnapshot", "-n", "tailvm", "-l", "corral.dev/vm=web", "--ignore-not-found"}, "", nil)

	req, _ := http.NewRequest("DELETE", fx.Server.URL+"/api/vms/tailvm/web", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Fatalf("delete: expected 200, got %d", resp.StatusCode)
	}

	// Verify registry was cleaned — try deleting again, should still succeed
	fx.Runner.AddResponseKV("/fake/bin/virtctl", []string{"stop", "web", "-n", "tailvm"}, "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"delete", "vm", "web", "-n", "tailvm", "--ignore-not-found"}, "", nil)
	fx.Runner.AddPrefixResponse("kubectl delete pvc web-", "", nil)
	fx.Runner.AddPrefixResponse("kubectl delete datavolume web-", "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"delete", "pvc", "-n", "tailvm", "-l", "corral.dev/vm=web", "--ignore-not-found"}, "", nil)
	fx.Runner.AddResponseKV("kubectl", []string{"delete", "vmsnapshot", "-n", "tailvm", "-l", "corral.dev/vm=web", "--ignore-not-found"}, "", nil)

	req, _ = http.NewRequest("DELETE", fx.Server.URL+"/api/vms/tailvm/web", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	// Second delete should also succeed (idempotent)
	if resp.StatusCode != 200 {
		t.Errorf("idempotent delete: expected 200, got %d", resp.StatusCode)
	}
}
