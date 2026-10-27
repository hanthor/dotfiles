# zen_browser

**Unit:** `units/zen-browser.sh`  
**Tags:** `desktop`, `browser`, `zen_browser`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_zen_browser: true` or `machine_profile: vm-test`.

The unit best-effort pins Zen in the GNOME dock, removes Firefox and Thunderbird dock entries, and sets browser MIME defaults when the Zen Flatpak data directory exists. A live user session is needed for dock changes.

If Zen's Flatpak `profiles.ini` is absent, profile and policy steps are skipped. Otherwise it resolves `Profile0` and merges `units/zen-browser/user.js` into a managed block in that profile's `user.js`, retaining unrelated preferences. It merges `units/zen-browser/policies.json` into both the system Flatpak Zen distribution policy and `~/.zen/distribution/policies.json`, preserving unrelated policy keys and list entries. The system policy requires root or non-interactive sudo; malformed or incompatible existing policies fail rather than being discarded.

Firefox Account setup is handled by the separate [browser-fxa unit](browser_fxa.md), not by this unit. A successful configuration does not verify a browser login.
