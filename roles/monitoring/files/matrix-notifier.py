#!/usr/bin/env python3
"""
Tiny Alertmanager → Matrix webhook bridge.
Receives Alertmanager webhook POST /alert and sends a formatted message
to a Matrix room via the Matrix Client API.

Required environment variables:
  MATRIX_HOMESERVER_URL   e.g. https://matrix.example.com
  MATRIX_TOKEN            bot access token (m.login.token or m.login.password)
  MATRIX_ROOM_ID          room ID, e.g. !abc123:example.com
"""

import json
import logging
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HOMESERVER = os.environ["MATRIX_HOMESERVER_URL"].rstrip("/")
TOKEN = os.environ["MATRIX_TOKEN"]
ROOM_ID = os.environ["MATRIX_ROOM_ID"]

SEVERITY_EMOJI = {"critical": "🔴", "warning": "🟡"}
STATUS_EMOJI = {"firing": "🔥", "resolved": "✅"}


def send_matrix_message(body: str, html: str) -> None:
    room = urllib.parse.quote(ROOM_ID, safe="")
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room}/send/m.room.message"
    payload = json.dumps({
        "msgtype": "m.text",
        "body": body,
        "format": "org.matrix.custom.html",
        "formatted_body": html,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            log.error("Matrix API returned %s", resp.status)


def format_alert(alert: dict) -> tuple[str, str]:
    status = alert.get("status", "unknown")
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    name = labels.get("alertname", "unknown")
    machine = labels.get("machine", labels.get("instance", "unknown"))
    severity = labels.get("severity", "info")
    summary = annotations.get("summary", name)
    description = annotations.get("description", "")

    s_emoji = STATUS_EMOJI.get(status, "❓")
    sev_emoji = SEVERITY_EMOJI.get(severity, "⚪")

    plain = f"{s_emoji} [{status.upper()}] {sev_emoji} {summary}"
    if description:
        plain += f"\n{description}"

    html = (
        f"<b>{s_emoji} [{status.upper()}] {sev_emoji} {summary}</b>"
        + (f"<br/><i>{description}</i>" if description else "")
        + f"<br/><code>machine={machine} severity={severity}</code>"
    )
    return plain, html


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress default access log
        log.debug(fmt, *args)

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/alert":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        for alert in data.get("alerts", []):
            plain, html = format_alert(alert)
            log.info("Sending: %s", plain[:120])
            try:
                send_matrix_message(plain, html)
            except Exception as exc:
                log.error("Failed to send to Matrix: %s", exc)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log.info("matrix-notifier listening on :%d → %s room %s", port, HOMESERVER, ROOM_ID)
    HTTPServer(("", port), Handler).serve_forever()
