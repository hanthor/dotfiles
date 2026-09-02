#!/usr/bin/env python3
"""Generate per-hive branding CSS from the shared palette base.

Each hive gets its own mark and wordmark, so a glance at the tab tells you
which fleet you are looking at. The bee/HIVE wordmark is the upstream default;
it stays correct for upstream and wrong for us.

TEXT IS REPLACED BY COLLAPSING THE ORIGINAL AND DRAWING A ::after. The dashboard
renders the mark and wordmark as literal text nodes:

    <span class="oc-logo-icon">🐝</span>
    <div class="oc-logo-title">HIVE</div>
    <div class="oc-logo-sub">GATEWAY DASHBOARD</div>
    <h1><span class="bee">🐝</span> KubeStellar Hive Dashboard …

CSS cannot edit a text node, so each is zeroed with font-size:0 and the
replacement drawn in a pseudo-element at an explicit size. Fragile if upstream
renames these classes — which is exactly why the upstream ask is a real content
override, not more CSS.

NOT reachable from CSS, and deliberately left alone rather than faked:
  - the favicon (an SVG data: URI in <link>)
  - <title> / og:title
  - the "KubeStellar Hive Dashboard" text in <h1> (only its emoji is a span)
"""
import pathlib
import sys

HIVES = {
    "reef":   ("🪸", "REEF",   "APPLICATIONS"),
    "school": ("🐟", "SCHOOL", "OPERATING SYSTEM"),
}

base = pathlib.Path("branding.css").read_text()

TMPL = """
/* ── %(name)s identity ────────────────────────────────────────────────── */
/* Replaces the upstream bee/HIVE wordmark. See make-branding.py for why this
   is done with pseudo-elements and what it deliberately cannot reach. */
.oc-logo-icon { font-size: 0 !important; }
.oc-logo-icon::after { content: "%(mark)s"; font-size: 26px; line-height: 1; }

.oc-logo-title { font-size: 0 !important; }
.oc-logo-title::after {
  content: "%(title)s";
  font-size: 20px; font-weight: 800; letter-spacing: .06em; color: var(--accent);
}

.oc-logo-sub { font-size: 0 !important; }
.oc-logo-sub::after {
  content: "%(sub)s";
  font-size: 10px; font-weight: 700; letter-spacing: .11em; color: var(--muted);
}

h1 .bee { font-size: 0 !important; }
h1 .bee::after { content: "%(mark)s"; font-size: 1rem; line-height: 1; }
"""

for name, (mark, title, sub) in HIVES.items():
    out = base + TMPL % {"name": name, "mark": mark, "title": title, "sub": sub}
    pathlib.Path(f"branding-{name}.css").write_text(out)
    print(f"wrote branding-{name}.css  ({mark} {title} / {sub})")
