package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
)

// policyConfig is the on-disk shape of the per-node secret policy. Keying is by
// StableNodeID (the unforgeable id) — the same key the broker authorizes on.
//
//	{
//	  "defaults": [{"name": "ts-authkey", "item": "<bw-item>", "get": "password"}],
//	  "nodes": {
//	    "nABC123...": [{"name": "kubeconfig", "item": "<bw-item>", "get": "notes"}]
//	  }
//	}
type policyConfig struct {
	Comment  string                 `json:"_comment,omitempty"` // free-text note, ignored
	Defaults []secretRef            `json:"defaults"`
	Nodes    map[string][]secretRef `json:"nodes"`
}

// loadPolicy reads and validates a policy config file into a policy.
func loadPolicy(path string) (policy, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return policy{}, err
	}
	var cfg policyConfig
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&cfg); err != nil {
		return policy{}, fmt.Errorf("parse %s: %w", path, err)
	}
	if err := validateRefs("defaults", cfg.Defaults); err != nil {
		return policy{}, err
	}
	for node, refs := range cfg.Nodes {
		if node == "" {
			return policy{}, fmt.Errorf("node key must not be empty")
		}
		if err := validateRefs("node "+node, refs); err != nil {
			return policy{}, err
		}
	}
	byID := cfg.Nodes
	if byID == nil {
		byID = map[string][]secretRef{}
	}
	return policy{byStableID: byID, def: cfg.Defaults}, nil
}

func validateRefs(where string, refs []secretRef) error {
	seen := map[string]bool{}
	for i, r := range refs {
		if r.Name == "" {
			return fmt.Errorf("%s: ref %d has empty name", where, i)
		}
		if r.Item == "" {
			return fmt.Errorf("%s: ref %q has empty item", where, r.Name)
		}
		if seen[r.Name] {
			return fmt.Errorf("%s: duplicate ref name %q", where, r.Name)
		}
		seen[r.Name] = true
	}
	return nil
}
