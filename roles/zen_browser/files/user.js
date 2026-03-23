// Firefox Sync
user_pref("identity.fxaccounts.enabled", true);

// Telemetry off
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);

// Skip first-run
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");

// Auto-update extensions
user_pref("extensions.update.autoUpdateDefault", true);
