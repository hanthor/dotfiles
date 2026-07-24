package main

import (
	"os"
	"path/filepath"
	"testing"
)

func writeTemp(t *testing.T, content string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "policy.json")
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestLoadPolicy_Valid(t *testing.T) {
	p, err := loadPolicy(writeTemp(t, `{
		"defaults": [{"name":"ts-authkey","smID":"sm-ts"}],
		"nodes": {"nABC": [{"name":"kubeconfig","smID":"sm-kube"}]}
	}`))
	if err != nil {
		t.Fatal(err)
	}
	refs := p.refsFor(identity{StableID: "nABC"})
	if len(refs) != 2 { // default + node
		t.Fatalf("want 2 refs, got %d", len(refs))
	}
}

func TestLoadPolicy_RejectsUnknownField(t *testing.T) {
	if _, err := loadPolicy(writeTemp(t, `{"nodez": {}}`)); err == nil {
		t.Fatal("unknown field must be rejected (typo protection)")
	}
}

func TestLoadPolicy_RejectsEmptyName(t *testing.T) {
	if _, err := loadPolicy(writeTemp(t, `{"nodes":{"nABC":[{"name":"","smID":"x"}]}}`)); err == nil {
		t.Fatal("empty ref name must be rejected")
	}
}

func TestLoadPolicy_RejectsEmptySMID(t *testing.T) {
	if _, err := loadPolicy(writeTemp(t, `{"nodes":{"nABC":[{"name":"k","smID":""}]}}`)); err == nil {
		t.Fatal("empty smID must be rejected")
	}
}

func TestLoadPolicy_RejectsDuplicateName(t *testing.T) {
	if _, err := loadPolicy(writeTemp(t, `{"nodes":{"nABC":[{"name":"k","smID":"a"},{"name":"k","smID":"b"}]}}`)); err == nil {
		t.Fatal("duplicate ref name must be rejected")
	}
}

func TestLoadPolicy_MissingFile(t *testing.T) {
	if _, err := loadPolicy(filepath.Join(t.TempDir(), "nope.json")); err == nil {
		t.Fatal("missing file must error")
	}
}

// The shipped example must actually parse — a broken template is a footgun.
func TestLoadPolicy_ExampleParses(t *testing.T) {
	if _, err := loadPolicy("policy.example.json"); err != nil {
		t.Fatalf("policy.example.json must parse: %v", err)
	}
}
