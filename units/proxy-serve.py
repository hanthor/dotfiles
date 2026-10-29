#!/usr/bin/env python3
"""Check the node's default HTTPS Serve handler, not unrelated handlers."""
import json
import sys
from urllib.parse import urlsplit


def mapping(value):
    if not isinstance(value, dict):
        raise ValueError("unexpected Tailscale status structure")
    return value


def main(status_path, serve_path):
    with open(status_path, encoding="utf-8") as source:
        status = mapping(json.load(source))
    with open(serve_path, encoding="utf-8") as source:
        serve = json.load(source)
    if serve is None:
        serve = {}
    serve = mapping(serve)
    name = mapping(status.get("Self")).get("DNSName")
    if not isinstance(name, str) or not name.rstrip("."):
        raise ValueError("Tailscale did not report the node DNS name")
    web = mapping(serve.get("Web", {}))
    tcp = mapping(serve.get("TCP", {}))
    endpoint = web.get(name.rstrip(".") + ":443")
    port = tcp.get("443")
    if endpoint is None or port is None:
        print("false")
        return
    handlers = mapping(mapping(endpoint).get("Handlers", {}))
    root = handlers.get("/")
    if root is None:
        print("false")
        return
    target = mapping(root).get("Proxy", "")
    if not isinstance(target, str):
        raise ValueError("unexpected Tailscale proxy target")
    url = urlsplit(target)
    matches = (mapping(port).get("HTTPS") is True and url.scheme == "http"
               and url.hostname == "127.0.0.1" and url.port == 9000
               and url.path in ("", "/") and not url.query and not url.fragment
               and url.username is None and url.password is None)
    print("true" if matches else "false")

if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("invalid Serve status query")
        main(*sys.argv[1:])
    except (OSError, ValueError, TypeError) as error:
        print(f"Tailscale Serve status: {error}", file=sys.stderr)
        sys.exit(1)
