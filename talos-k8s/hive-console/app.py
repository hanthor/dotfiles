#!/usr/bin/env python3
"""hive-console — one page for the whole fleet.

Answers, in one place: how much provider quota is left, what every hive agent
is doing (and whether it is actually PRODUCING, not just "running"), which
contributor workers are connected to which hubs, and lets an owner change an
agent's backend/model or pause/resume it.

WHY IT LIVES IN THE CLUSTER, IN THE `hive` NAMESPACE, ON THE HIVE NODE
---------------------------------------------------------------------
It mounts the hive PVC READ-ONLY. That is only possible from a pod in the same
namespace on the same node (RWO binds to a node, not to a single pod), which is
why the Deployment copies hive's nodeSelector + control-plane toleration.

That one mount buys three things no other design gets cheaply:
  1. AUTH. /dashboard-sessions.json is the hive dashboard's own session store,
     so this console validates the SAME `hive_session` cookie. Served from the
     same host (hive.tunaos.org/console), the browser sends that cookie
     automatically: log in once at the hive dashboard via GitHub device flow
     and the console is authed too. No second credential, no BasicAuth prompt,
     and the authorized_users allowlist keeps working.
  2. Anthropic headroom, read live from the Claude Code OAuth token on the PVC
     (the same path hive-rotate.sh's probe_anthropic uses).
  3. Mutations. The caller's own owner cookie is FORWARDED to the hive API, so
     writes carry real attribution and hive re-validates them. `X-Hive-Internal`
     is read-only for mutations, so it is used only for reads.

Stdlib only, on purpose: the app ships as a ConfigMap over a stock python
image, so there is no image to build, push, or keep patched.
"""

import base64
import html
import http.server
import json
import os
import socketserver
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PORT = int(os.environ.get("PORT", "8080"))
PREFIX = os.environ.get("URL_PREFIX", "/console").rstrip("/")
HIVE_API = os.environ.get("HIVE_API", "http://hive.hive.svc.cluster.local:3002")
HIVE_DATA = os.environ.get("HIVE_DATA", "/hive-data")
INTERNAL_TOKEN = os.environ.get("HIVE_DASHBOARD_TOKEN", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
CONTRIB_NS = os.environ.get("CONTRIB_NS", "hive-contributors")
# Providers whose headroom cannot be read over plain HTTP (their CLI is the
# only probe) are filled in by hive-rotate.sh publishing this ConfigMap.
USAGE_CM = os.environ.get("USAGE_CONFIGMAP", "hive-provider-usage")

SESSIONS = os.path.join(HIVE_DATA, "dashboard-sessions.json")
CLAUDE_CREDS = os.path.join(HIVE_DATA, "home/.claude/.credentials.json")

K8S_HOST = os.environ.get("KUBERNETES_SERVICE_HOST", "")
K8S_PORT = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
SA = "/var/run/secrets/kubernetes.io/serviceaccount"


def _now():
    return datetime.now(timezone.utc)


def _get(url, headers=None, data=None, method=None, timeout=15, ctx=None):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


# ── caching ───────────────────────────────────────────────────────────────
# Every panel refreshes on its own clock. Quota APIs in particular are rate
# limited and move in minutes, not seconds, so hammering them on each page
# load would be both rude and useless.
_cache, _cache_lock = {}, threading.Lock()


def cached(key, ttl, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    try:
        val = {"ok": True, "data": fn(), "at": _now().isoformat()}
    except Exception as e:  # a dead panel must never take the page down
        val = {"ok": False, "error": f"{type(e).__name__}: {e}", "at": _now().isoformat()}
    with _cache_lock:
        _cache[key] = (time.time(), val)
    return val


# ── auth ──────────────────────────────────────────────────────────────────
def owner_session(cookie_header):
    """Validate the caller's hive_session against hive's OWN session store.

    Returns the session dict for a live owner session, else None. Expiry and
    role are both checked here rather than trusted from the cookie, and the
    store is re-read every time so a logout or expiry takes effect at once.
    """
    if not cookie_header:
        return None
    sid = None
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "hive_session":
            sid = v
    if not sid:
        return None
    try:
        with open(SESSIONS) as f:
            store = json.load(f)
    except Exception:
        return None
    s = store.get(sid)
    if not isinstance(s, dict) or s.get("Role") != "owner":
        return None
    try:
        exp = s.get("ExpiresAt", "")
        if datetime.fromisoformat(exp.replace("Z", "+00:00")) <= _now():
            return None
    except Exception:
        return None
    return s


# ── data sources ──────────────────────────────────────────────────────────
def hive_get(path):
    return json.loads(_get(HIVE_API + path, {"X-Hive-Internal": INTERNAL_TOKEN}))


def hive_mutate(path, cookie, method="POST", body=None, timeout=30):
    """Writes go out as the CALLER, not as the console."""
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Cookie": f"hive_session={cookie}"}
    if data:
        hdrs["Content-Type"] = "application/json"
    return _get(HIVE_API + path, hdrs, data=data, method=method, timeout=timeout)


def k8s(path):
    with open(f"{SA}/token") as f:
        tok = f.read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    return json.loads(
        _get(f"https://{K8S_HOST}:{K8S_PORT}{path}", {"Authorization": f"Bearer {tok}"}, ctx=ctx)
    )


def anthropic_usage():
    with open(CLAUDE_CREDS) as f:
        tok = json.load(f)["claudeAiOauth"]["accessToken"]
    raw = json.loads(
        _get(
            "https://api.anthropic.com/api/oauth/usage",
            {"Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20"},
        )
    )
    out = []
    for lim in raw.get("limits", []):
        if lim.get("percent") is None:
            continue
        # Label by RESET HORIZON, not by percent. The API does not name these
        # windows, and an earlier version inferred the label from the sort
        # order by percent — which mislabelled them the moment the session
        # window was the busiest one. The rolling session window is simply the
        # one that resets soonest; the weekly caps reset days out.
        d = _delta(lim.get("resets_at") or "")
        kind = "weekly" if d is None or d > 6 * 3600 else "5-hour session"
        out.append({"percent": lim["percent"], "resets_at": lim.get("resets_at"), "kind": kind})
    out.sort(key=lambda x: (x["kind"] != "5-hour session", -x["percent"]))
    return out


def deepseek_usage():
    raw = json.loads(
        _get("https://api.deepseek.com/user/balance", {"Authorization": f"Bearer {DEEPSEEK_KEY}"})
    )
    bal = (raw.get("balance_infos") or [{}])[0].get("total_balance")
    return {"available": raw.get("is_available"), "balance": bal}


def published_usage():
    """google/openai headroom, published by hive-rotate.sh (their only probe is
    a CLI pane, which this pod has no way to drive)."""
    cm = k8s(f"/api/v1/namespaces/hive/configmaps/{USAGE_CM}")
    return {
        "data": {k: v for k, v in (cm.get("data") or {}).items() if k != "updated_at"},
        "updated_at": (cm.get("data") or {}).get("updated_at"),
    }


def contributor_pods():
    pods = k8s(f"/api/v1/namespaces/{CONTRIB_NS}/pods")
    out = []
    for p in pods.get("items", []):
        st = p.get("status", {})
        cs = st.get("containerStatuses") or []
        out.append(
            {
                "name": p["metadata"]["name"],
                "phase": st.get("phase"),
                "ready": sum(1 for c in cs if c.get("ready")),
                "total": len(cs),
                "restarts": sum(c.get("restartCount", 0) for c in cs),
                "node": p.get("spec", {}).get("nodeName"),
                "started": st.get("startTime"),
            }
        )
    return sorted(out, key=lambda x: x["name"])


# ── rendering ─────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0d1117;color:#c9d1d9;font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:#58a6ff}
header{padding:18px 24px;border-bottom:1px solid #21262d;display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:17px;letter-spacing:.2px}
.sub{color:#8b949e;font-size:12px}
main{padding:20px 24px;display:grid;gap:20px;max-width:1400px}
section{border:1px solid #21262d;border-radius:8px;background:#161b22;overflow:hidden}
h2{margin:0;padding:11px 16px;font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:#8b949e;border-bottom:1px solid #21262d;display:flex;justify-content:space-between;gap:12px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{padding:8px 16px;text-align:left;border-bottom:1px solid #21262d;white-space:nowrap;font-size:13px}
th{color:#8b949e;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
tr:last-child td{border-bottom:none}
.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}.dim{color:#8b949e}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.bar{position:relative;height:6px;background:#21262d;border-radius:3px;width:150px;overflow:hidden}
.bar>i{position:absolute;inset:0 auto 0 0;border-radius:3px}
.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;border:1px solid #30363d;color:#8b949e}
.err{padding:12px 16px;color:#f85149;font-size:12px}
form{display:inline}
select,button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:3px 7px;font-size:12px}
button{cursor:pointer}button:hover{border-color:#58a6ff}
.act{display:flex;gap:5px;align-items:center;flex-wrap:wrap}
footer{padding:14px 24px;color:#8b949e;font-size:11px;border-top:1px solid #21262d}
"""

BACKENDS = ["claude", "agy", "codex", "pi", "copilot"]
MODELS = [
    "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5",
    "gemini-3.7-flash-high", "gemini-3.7-flash-low", "gemini-3.6-flash",
    "gpt-5.6-sol", "gpt-5.6-luna",
    "deepseek-v4-flash", "deepseek-v4-pro",
]


def e(x):
    return html.escape(str(x if x is not None else ""))


def bar(pct):
    c = "#3fb950" if pct < 60 else ("#d29922" if pct < 85 else "#f85149")
    return f'<div class="bar"><i style="width:{min(pct,100)}%;background:{c}"></i></div>'


def _delta(iso):
    try:
        return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - _now()).total_seconds()
    except Exception:
        return None


def _hms(s):
    s = int(abs(s))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s//60}m"
    if s < 86400:
        return f"{s//3600}h{(s%3600)//60:02d}m"
    return f"{s//86400}d{(s%86400)//3600:02d}h"


def age(iso):
    """Past timestamps read as '5m ago'."""
    if not iso:
        return "—"
    d = _delta(iso)
    return e(iso) if d is None else f"{_hms(d)} ago"


def until(iso):
    """Future timestamps read as 'in 4h12m' — a quota reset is ahead of now, so
    rendering it with age() would show a meaningless negative."""
    if not iso:
        return "—"
    d = _delta(iso)
    if d is None:
        return e(iso)
    return f"in {_hms(d)}" if d > 0 else f"{_hms(d)} ago"


def sec_err(title, blk):
    return f'<section><h2>{title}</h2><div class="err">unavailable — {e(blk.get("error"))}</div></section>'


def render_usage(ant, deep, pub):
    rows = ""
    if ant["ok"]:
        for lim in ant["data"]:
            rows += (
                f'<tr><td>anthropic <span class="dim">({lim["kind"]})</span></td>'
                f'<td>{bar(lim["percent"])}</td><td class="mono">{lim["percent"]}%</td>'
                f'<td class="dim mono">resets {until(lim["resets_at"])}</td></tr>'
            )
    else:
        rows += f'<tr><td>anthropic</td><td colspan="3" class="bad">{e(ant.get("error"))}</td></tr>'

    if deep["ok"]:
        d = deep["data"]
        b = d.get("balance")
        try:
            neg = float(str(b).replace("$", "")) < 1
        except Exception:
            neg = True
        cls = "bad" if (neg or not d.get("available")) else "ok"
        rows += (
            f'<tr><td>deepseek</td><td class="{cls}">{"available" if d.get("available") else "UNAVAILABLE"}</td>'
            f'<td class="mono {cls}">${e(b)}</td><td class="dim">prepaid credit</td></tr>'
        )
    else:
        rows += f'<tr><td>deepseek</td><td colspan="3" class="bad">{e(deep.get("error"))}</td></tr>'

    stamp = ""
    if pub["ok"]:
        # anthropic and deepseek are read live above; showing the ConfigMap's
        # copy of them too would put two differently-aged numbers for the same
        # provider side by side, which reads as a discrepancy rather than as a
        # cache. Only the CLI-pane-probed providers come from here.
        for k, v in sorted(pub["data"]["data"].items()):
            if k in ("anthropic", "deepseek"):
                continue
            rows += f'<tr><td>{e(k)}</td><td colspan="2" class="mono">{e(v)}</td><td class="dim">via hive-rotate</td></tr>'
        stamp = f'<span class="dim">google/openai measured {age(pub["data"].get("updated_at"))}</span>'
    else:
        rows += f'<tr><td colspan="4" class="dim">google/openai headroom not published yet — {e(pub.get("error"))}</td></tr>'
    return (
        f"<section><h2>Provider headroom{stamp}</h2><div class='wrap'><table>"
        f"<tr><th>provider</th><th>used</th><th></th><th>note</th></tr>{rows}</table></div></section>"
    )


def render_agents(st):
    if not st["ok"]:
        return sec_err("Hive agents", st)
    rows = ""
    prod_bad = 0
    for a in st["data"].get("agents", []):
        conds = {c["type"]: c for c in a.get("conditions", [])}
        def cond(n):
            c = conds.get(n)
            if not c:
                return '<span class="dim">—</span>'
            good = c.get("status") == "True"
            cls = "ok" if good else "bad"
            return f'<span class="{cls}" title="{e(c.get("message"))}">{e(c.get("reason"))}</span>'
        if conds.get("Producing", {}).get("status") == "False":
            prod_bad += 1
        paused = a.get("paused")
        n = e(a["name"])
        opts_b = "".join(
            f'<option{" selected" if b==a.get("cli") else ""}>{b}</option>' for b in BACKENDS
        )
        opts_m = "".join(
            f'<option{" selected" if m==a.get("model") else ""}>{m}</option>' for m in MODELS
        )
        rows += f"""<tr>
<td><b>{n}</b></td>
<td class="mono">{e(a.get('cli'))}</td>
<td class="mono dim">{e(a.get('model'))}</td>
<td class="mono">{e(a.get('cadence'))}</td>
<td>{'<span class="warn">paused</span>' if paused else '<span class="ok">active</span>'}</td>
<td>{cond('Authenticated')}</td>
<td>{cond('Producing')}</td>
<td><div class="act">
<form method="post" action="{PREFIX}/act"><input type="hidden" name="agent" value="{n}">
<input type="hidden" name="op" value="set">
<select name="backend">{opts_b}</select><select name="model">{opts_m}</select>
<button>apply</button></form>
<form method="post" action="{PREFIX}/act"><input type="hidden" name="agent" value="{n}">
<input type="hidden" name="op" value="{'resume' if paused else 'pause'}">
<button>{'resume' if paused else 'pause'}</button></form>
<form method="post" action="{PREFIX}/act"><input type="hidden" name="agent" value="{n}">
<input type="hidden" name="op" value="kick"><button>kick</button></form>
</div></td></tr>"""
    gov = st["data"].get("governor", {}) or {}
    hdr = (
        f'<span class="dim">mode <b>{e(gov.get("mode"))}</b> · '
        f'{e(gov.get("issues"))} issues / {e(gov.get("prs"))} PRs · '
        f'{prod_bad} not producing</span>'
    )
    return (
        f"<section><h2>Hive agents — watchdog{hdr}</h2><div class='wrap'><table>"
        "<tr><th>agent</th><th>backend</th><th>model</th><th>cadence</th><th>state</th>"
        "<th>auth</th><th>producing</th><th>actions</th></tr>"
        f"{rows}</table></div></section>"
    )


def render_contributors(pods, fleet):
    rows = ""
    if pods["ok"]:
        for p in pods["data"]:
            healthy = p["ready"] == p["total"] and p["phase"] == "Running"
            rows += (
                f'<tr><td class="mono">{e(p["name"])}</td>'
                f'<td class="{"ok" if healthy else "bad"}">{e(p["phase"])} {p["ready"]}/{p["total"]}</td>'
                f'<td class="mono">{p["restarts"]}</td>'
                f'<td class="dim">{age(p["started"])}</td>'
                f'<td class="dim mono">{e(p["node"])}</td></tr>'
            )
    else:
        rows = f'<tr><td colspan="5" class="bad">{e(pods.get("error"))}</td></tr>'

    frows = ""
    if fleet["ok"]:
        for c in fleet["data"].get("clankers", []):
            t = c.get("current_task") or {}
            frows += (
                f'<tr><td class="mono">{e(c.get("cli_backend"))}</td>'
                f'<td class="mono dim">{e(c.get("model") or "—")}</td>'
                f'<td class="mono">{e(c.get("contributor_id"))}</td>'
                f'<td class="mono">{e(c.get("trust_tier"))}</td>'
                f'<td>{e(t.get("key") or "idle")}</td>'
                f'<td class="dim">{age(c.get("last_activity"))}</td></tr>'
            )
        if not frows:
            frows = '<tr><td colspan="6" class="warn">no contributor connected to this hub</td></tr>'
    else:
        frows = f'<tr><td colspan="6" class="bad">{e(fleet.get("error"))}</td></tr>'

    return f"""<section><h2>Contributor workers <span class="dim">namespace {e(CONTRIB_NS)}</span></h2>
<div class='wrap'><table><tr><th>pod</th><th>status</th><th>restarts</th><th>age</th><th>node</th></tr>{rows}</table></div></section>
<section><h2>Connected to this hub <span class="dim">one profile, many sockets</span></h2>
<div class='wrap'><table><tr><th>backend</th><th>model</th><th>contributor id</th><th>tier</th><th>task</th><th>last activity</th></tr>{frows}</table></div></section>"""


def page(session, flash=""):
    ant = cached("anthropic", 60, anthropic_usage)
    deep = cached("deepseek", 300, deepseek_usage)
    pub = cached("published", 60, published_usage)
    st = cached("status", 15, lambda: hive_get("/api/status"))
    fleet = cached("fleet", 20, lambda: hive_get("/api/contribute/fleet"))
    pods = cached("pods", 20, contributor_pods)

    who = e(session.get("Username") or session.get("User") or "owner")
    fl = f'<div class="err" style="color:#3fb950">{e(flash)}</div>' if flash else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>hive console</title><style>{CSS}</style></head><body>
<header><h1>hive console</h1>
<span class="sub">tuna-os · <a href="/">hive dashboard</a> · signed in as {who}</span>
<span class="sub" style="margin-left:auto">{_now().strftime('%Y-%m-%d %H:%M:%S UTC')} · <a href="{PREFIX}/">refresh</a></span>
</header>{fl}<main>
{render_usage(ant, deep, pub)}
{render_agents(st)}
{render_contributors(pods, fleet)}
</main>
<footer>Reads via X-Hive-Internal (read-only). Writes are forwarded as your own
owner session, so hive re-validates every change. Quota panels are cached
60&ndash;300s.</footer></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # one line per request, no client spoofing
        print(f"{self.command} {self.path} -> {a[1] if len(a) > 1 else ''}", flush=True)

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _deny(self):
        self._send(
            401,
            "<!doctype html><meta charset=utf-8><style>body{background:#0d1117;color:#c9d1d9;"
            "font:15px system-ui;padding:60px;text-align:center}a{color:#58a6ff}</style>"
            "<h2>Not signed in</h2><p>This console shares the hive dashboard's session.</p>"
            '<p><a href="/">Sign in at the hive dashboard</a>, then come back.</p>',
        )

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/healthz", PREFIX + "/healthz"):
            return self._send(200, "ok", "text/plain")
        if not path.startswith(PREFIX):
            return self._send(404, "not found", "text/plain")
        s = owner_session(self.headers.get("Cookie"))
        if not s:
            return self._deny()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if path == PREFIX + "/api/state":
            return self._send(
                200,
                json.dumps(
                    {
                        "anthropic": cached("anthropic", 60, anthropic_usage),
                        "deepseek": cached("deepseek", 300, deepseek_usage),
                        "status": cached("status", 15, lambda: hive_get("/api/status")),
                    }
                ),
                "application/json",
            )
        return self._send(200, page(s, (q.get("m") or [""])[0]))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        # ALWAYS drain the request body before responding, including on the
        # reject paths. This is HTTP/1.1 with keep-alive: bailing out early
        # leaves the unread body in the socket, and the server then parses
        # those bytes as the NEXT request line — observed as
        # "Unsupported method ('agent=guide&op=kickPOST')" and a bogus 501
        # for what was actually a clean 401.
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n > 0 else b""
        if path != PREFIX + "/act":
            return self._send(404, "not found", "text/plain")
        s = owner_session(self.headers.get("Cookie"))
        if not s:
            return self._deny()
        form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
        agent = (form.get("agent") or [""])[0]
        op = (form.get("op") or [""])[0]
        # Re-extract the caller's cookie: mutations go out as THEM, so hive
        # applies its own owner check and the change is attributable.
        sid = ""
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "hive_session":
                sid = v
        msgs = []
        try:
            if op == "set":
                b = (form.get("backend") or [""])[0]
                m = (form.get("model") or [""])[0]
                # Backend first: a failed switch + successful model set leaves the
                # agent on the old CLI with a foreign model name, which is a hard
                # startup failure. Same ordering hive-rotate.sh uses.
                r1 = json.loads(hive_mutate(f"/api/switch/{agent}/{b}", sid))
                if r1.get("status") != "switched":
                    raise RuntimeError(f"switch failed: {r1.get('error') or r1}")
                r2 = json.loads(hive_mutate(f"/api/model/{agent}/{m}", sid))
                msgs.append(f"{agent} → {b}/{m} ({r2.get('status') or r2.get('error')})")
            elif op == "kick":
                # A kick blocks until the agent's CLI answers, which for a busy
                # or wedged TUI is far longer than any sane request timeout —
                # hive-rotate.sh backgrounds it for exactly this reason. Fire it
                # off and report dispatch, rather than showing the operator a
                # TimeoutError for a kick that did in fact happen.
                threading.Thread(
                    target=lambda: hive_mutate(f"/api/kick/{agent}", sid, timeout=180),
                    daemon=True,
                ).start()
                msgs.append(f"{agent}: kick dispatched")
            elif op in ("pause", "resume"):
                r = json.loads(hive_mutate(f"/api/{op}/{agent}", sid))
                msgs.append(f"{agent}: {r.get('status') or r.get('error')}")
            else:
                msgs.append("unknown op")
        except Exception as ex:
            msgs.append(f"{agent}: FAILED — {type(ex).__name__}: {ex}")
        with _cache_lock:
            _cache.pop("status", None)  # show the result, not the pre-write snapshot
        self._send(303, "", "text/plain", {"Location": PREFIX + "/?m=" + urllib.parse.quote("; ".join(msgs))})


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"hive-console on :{PORT} prefix={PREFIX}", flush=True)
    Server(("", PORT), Handler).serve_forever()
