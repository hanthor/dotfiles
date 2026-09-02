#!/usr/bin/env python3
"""check-pages.py — Playwright smoke test for the tuna-os hive surfaces.

Checks the things that actually break and that a curl cannot see: whether the
page renders at all, whether it throws in the browser, whether requests 404,
whether the branding tokens really landed, and whether the layout survives a
phone-width viewport.

  HIVE_SESSION=<cookie> ./check-pages.py [--shots DIR]

The session cookie is only needed for the authenticated surfaces; public pages
are checked regardless so a missing cookie degrades the run rather than
failing it.
"""
import argparse
import asyncio
import os
import sys

from playwright.async_api import async_playwright

# (label, url, needs_auth, must_contain)
PAGES = [
    ("hub front door", "https://hub.tunaos.org/", False, ["TunaOS Hive Constellation", "reef"]),
    ("hub registry api", "https://hub.tunaos.org/api/registry", False, ["hives"]),
    ("console", "https://school.tunaos.org/console/", True, ["Provider headroom", "Hive agents"]),
    ("school dashboard", "https://school.tunaos.org/", True, []),
    ("reef dashboard", "https://reef.tunaos.org/", True, []),
]

# Colours the branding override installs, checked as *computed* style so we
# prove the CSS applied rather than merely downloaded. BOTH themes are listed:
# the dashboard ships a light mode (body.light-mode) that overrides :root, so
# looking only for the dark palette reports a correctly-branded light page as
# unbranded — which it did.
BRAND_COLOURS = (
    "4, 22, 31",       # #04161f deep water   (dark bg)
    "232, 246, 248",   # #e8f6f8 foam         (dark ink)
    "242, 249, 250",   # #f2f9fa shallow      (light bg)
    "6, 35, 46",       # #06232e deep teal    (light ink)
)

# Cloudflare injects its analytics beacon into proxied HTML. It is blocked in
# this environment and is not served by us — failing the run on it would mean
# every page is permanently red for a third-party script we do not control.
IGNORED_ERROR_SUBSTRINGS = ("cloudflareinsights.com", "beacon.min.js")

# Endpoints the SPA probes optimistically and that legitimately 404 on a hive
# which does not use them. Verified individually rather than assumed:
#   /api/inference/models/*  optional inference providers we do not configure
#   /api/auth/token          an auth mode this deployment does not use
#   /api/pane/brainstorm     a pack agent deliberately TOMBSTONED here; the SPA
#                            still asks for its pane
# Listing them keeps the run's signal meaningful — a permanently-red check gets
# ignored, and then a real regression hides in the noise.
BENIGN_404_PATHS = (
    "/api/inference/models/",
    "/api/auth/token",
    "/api/pane/brainstorm",
)


async def check(page, label, url, expect, shots, session):
    errors, failed_reqs = [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("requestfailed",
            lambda r: failed_reqs.append(f"{r.method} {r.url.split('?')[0]}"))
    def _resp(r):
        u = r.url.split("?")[0]
        if r.status >= 500:
            failed_reqs.append(f"HTTP {r.status} {u}")
        elif r.status == 404 and not any(b in u for b in BENIGN_404_PATHS):
            failed_reqs.append(f"HTTP 404 {u}")
    page.on("response", _resp)

    out = {"label": label, "ok": True, "notes": []}
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        out["status"] = resp.status if resp else 0
    except Exception as e:  # a hang or TLS failure is a real result, not a crash
        out["ok"] = False
        out["status"] = 0
        out["notes"].append(f"navigation failed: {type(e).__name__}: {e}")
        return out

    await page.wait_for_timeout(2500)  # let the SPA paint

    if out["status"] >= 400:
        out["ok"] = False
        out["notes"].append(f"HTTP {out['status']}")

    body = (await page.content()) or ""
    for token in expect:
        if token not in body:
            out["ok"] = False
            out["notes"].append(f"missing text: {token!r}")

    # Computed colours prove the override applied rather than just loaded.
    try:
        bg = await page.evaluate("getComputedStyle(document.body).backgroundColor")
        fg = await page.evaluate("getComputedStyle(document.body).color")
        out["bg"], out["fg"] = bg, fg
        out["branded"] = any(c in (bg or "") or c in (fg or "") for c in BRAND_COLOURS)
    except Exception:
        out["branded"] = None

    # Horizontal overflow at phone width is the classic dashboard regression.
    try:
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(700)
        overflow = await page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
        if overflow:
            out["ok"] = False
            out["notes"].append("horizontal overflow at 390px")
        await page.set_viewport_size({"width": 1440, "height": 900})
    except Exception:
        pass

    # A console "Failed to load resource" line has no URL, so it cannot be
    # matched against BENIGN_404_PATHS; the response listener above already
    # judged those by URL. Drop the generic ones and trust that instead.
    ours = [e for e in errors
            if not any(i in e for i in IGNORED_ERROR_SUBSTRINGS)
            and "Failed to load resource" not in e]
    if ours:
        out["ok"] = False
        out["notes"].append(f"{len(ours)} console error(s): {ours[0][:110]}")
    if len(errors) != len(ours):
        out["notes"].append(f"{len(errors) - len(ours)} third-party error(s) ignored")
    hard = [r for r in failed_reqs
            if "favicon" not in r and not any(i in r for i in IGNORED_ERROR_SUBSTRINGS)]
    if hard:
        out["notes"].append(f"{len(hard)} failed request(s): {hard[0][:110]}")

    if shots:
        await page.wait_for_timeout(400)
        await page.screenshot(path=os.path.join(shots, f"{label.replace(' ', '-')}.png"),
                              full_page=True)
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="directory to write screenshots into")
    args = ap.parse_args()
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)

    session = os.environ.get("HIVE_SESSION", "")
    if not session:
        print("note: HIVE_SESSION unset — authenticated pages will be reported as gated\n")

    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        if session:
            await ctx.add_cookies([
                {"name": "hive_session", "value": session, "domain": d, "path": "/",
                 "secure": True, "httpOnly": True}
                for d in ("hive.tunaos.org", "school.tunaos.org", "reef.tunaos.org", "hub.tunaos.org")
            ])
        for label, url, needs_auth, expect in PAGES:
            if needs_auth and not session:
                results.append({"label": label, "ok": None, "status": "-",
                                "notes": ["skipped: no session"]})
                continue
            page = await ctx.new_page()
            results.append(await check(page, label, url, expect, args.shots, session))
            await page.close()
        await browser.close()

    print(f"{'PAGE':<20} {'HTTP':>5}  {'BRANDED':<8} NOTES")
    bad = 0
    for r in results:
        mark = "ok " if r["ok"] else ("--- " if r["ok"] is None else "FAIL")
        if r["ok"] is False:
            bad += 1
        brand = {True: "yes", False: "no", None: "?"}.get(r.get("branded"), "-")
        print(f"{mark} {r['label']:<16} {str(r.get('status')):>5}  {brand:<8} "
              f"{'; '.join(r.get('notes', [])) or '-'}")
        if r.get("bg"):
            print(f"     {'':<16} {'':>5}  bg={r['bg']} fg={r['fg']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
