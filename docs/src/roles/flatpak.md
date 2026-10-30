# flatpak

**Unit:** `units/flatpak.sh`  
**Tags:** `packages`, `desktop`, `flatpak`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_flatpak: true` or `machine_profile: vm-test`.

The unit requires Flatpak and `yq`. It reads system remotes and `system_flatpaks` from `units/flatpak-packages.yml`, adds remotes, removes system Firefox and Thunderbird Flatpaks, and installs missing applications from Flathub. A failed batch is retried individually. A dangling `/var/lib/flatpak` symlink is preserved: restore its target before retrying system operations. User operations and wrapper deployment remain independent. `DOTFILES_UPGRADE=1` or `true` requests a best-effort system update. System operations require root or non-interactive sudo.

`flatpark_flatpaks` in the same file lists system applications installed from the `flatpark` remote instead of Flathub (currently `com.automattic.Beeper`); the key may be omitted. The remote must also appear in `flatpak_remotes`.

The `beeper-login` unit then signs Beeper in on desktops where `com.automattic.Beeper` is installed. Beeper Desktop only supports emailed one-time codes (no password sign-in), so the unit starts sign-in through the local Desktop API (`127.0.0.1:23373`), reads the code from an IMAP mailbox, and unlocks encryption with the Recovery Code. It reads the Bitwarden login `beeper` (see [Bitwarden](../bitwarden.md)), is skipped with `--no-secrets` or a locked vault, never prompts, and does nothing once Beeper reports `ready`. It launches Beeper only on a fresh install (no `~/.var/app/com.automattic.Beeper/config/BeeperTexts`) or with `BEEPER_LOGIN_FORCE=1`; otherwise it queries a running app. Opt out per host with `skip_beeper: true`. Chat-network accounts (WhatsApp, Telegram and so on) are not signed in and still need linking in the app.

Host-specific `user_flatpak_remotes` and `user_flatpaks` in `host_vars/<machine>.yml` are applied with `--user`, separately from the system store. For `himachal`, these configure FlatPark and user Flathub, then install `org.tunaos.blueshell`, `org.tunaos.tavern`, and `org.tunaos.compass` from FlatPark. An already installed user app with a different origin is preserved rather than switched. This installation does not configure or unlock Compass's keyring or establish an application login; those depend on the user's session and app setup.

The unit also writes `chromium`, `chromium-browser`, `google-chrome`, and `google-chrome-stable` wrappers in `~/.local/bin`, invoking `org.chromium.Chromium` via Flatpak. Existing custom files and symlinks are preserved; matching managed wrappers have their mode corrected. Wrappers are attempted even if Flatpak is unavailable.
