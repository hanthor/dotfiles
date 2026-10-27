// Firefox Sync
user_pref("identity.fxaccounts.enabled", true);

// Sync engines — explicitly enable all useful ones
user_pref("services.sync.engine.addons", true);
user_pref("services.sync.engine.bookmarks", true);
user_pref("services.sync.engine.history", true);
user_pref("services.sync.engine.passwords", true);
user_pref("services.sync.engine.prefs", true);
user_pref("services.sync.engine.tabs", true);

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

// Disable built-in password manager (using Bitwarden instead)
user_pref("signon.rememberSignons", false);
user_pref("signon.autofillForms", false);
user_pref("signon.generation.enabled", false);
user_pref("signon.management.page.breach-alerts.enabled", false);
user_pref("extensions.formautofill.creditCards.enabled", false);
user_pref("extensions.formautofill.addresses.enabled", false);

// Disable swipe back/forward navigation
user_pref("browser.gesture.swipe.left", "");
user_pref("browser.gesture.swipe.right", "");
