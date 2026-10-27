#!/usr/bin/env python3
"""Join Tailscale without placing vault or Tailscale credentials in argv."""
import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


def fail(message):
    print(message, file=sys.stderr)
    return 1


def interrupt(_signal, _frame):
    raise InterruptedError()


def main():
    if len(sys.argv) != 4:
        return fail("Tailscale enrollment requires machine, domain and privilege mode")
    machine, domain, root_mode = sys.argv[1:]
    try:
        result = subprocess.run(["bw", "get", "item", "tailscale-apikey"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=True, text=True)
        key = json.loads(result.stdout)["login"]["password"]
        if not isinstance(key, str) or not key.strip():
            raise ValueError("empty key")
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        return fail("Unable to read a nonempty Tailscale key from Bitwarden")

    authorization = "Basic " + base64.b64encode((key + ":").encode()).decode()
    headers = {"Authorization": authorization, "Content-Type": "application/json"}
    try:
        request = urllib.request.Request("https://api.tailscale.com/api/v2/tailnet/-/devices", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            devices = json.load(response).get("devices", [])
        if not isinstance(devices, list):
            raise ValueError("invalid device list")
    except (OSError, ValueError, TypeError):
        # The old role explicitly treated the list operation as best effort.
        print("warn: could not read Tailscale device list; stale-device cleanup skipped")
        devices = []
    old = next((device.get("id") for device in devices
                if isinstance(device, dict) and device.get("name") == machine + "." + domain
                and device.get("id")), None)
    if old is not None:
        try:
            url = "https://api.tailscale.com/api/v2/device/" + urllib.parse.quote(str(old), safe="")
            request = urllib.request.Request(url, headers=headers, method="DELETE")
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError("unexpected response")
        except (OSError, ValueError):
            return fail("Unable to remove the matching stale Tailscale device; join skipped")

    # The auth key is read from a private file by tailscale; the file and its
    # containing directory are removed even on normal termination signals.
    old_handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with tempfile.TemporaryDirectory(prefix="dotfiles-tailscale-") as directory:
            path = os.path.join(directory, "authkey")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(key)
            command = ([] if root_mode == "root" else ["sudo", "-n"]) + [
                "tailscale", "up", "--auth-key=file:" + path,
                "--advertise-tags=tag:fleet", "--accept-routes", "--hostname", machine,
            ]
            environment = os.environ.copy()
            environment.pop("BW_SESSION", None)
            result = subprocess.run(command, env=environment,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                return fail("Tailscale join failed; check the daemon and key permissions")
    except (OSError, InterruptedError):
        return fail("Tailscale join interrupted or could not be started")
    finally:
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)
    return 0


if __name__ == "__main__":
    sys.exit(main())
