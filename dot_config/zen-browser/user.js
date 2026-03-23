// Zen Browser user preferences
// Firefox Sync: prompt on first launch
user_pref("identity.fxaccounts.enabled", true);

// Don't show first-run pages
user_pref("browser.startup.firstrunSkipsHomepage", true);
user_pref("trailhead.firstrun.didSeeAboutWelcome", true);

// Disable telemetry
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);

// Extension updates
user_pref("extensions.update.autoUpdateDefault", true);
