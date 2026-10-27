#!/usr/bin/env python3
"""Join Tailscale without placing vault or Tailscale credentials in argv."""
import json
import os
import signal
import subprocess
import sys
import tempfile


def fail(message):
    print(message, file=sys.stderr)
    return 1


def interrupt(_signal, _frame):
    raise InterruptedError()


def main():
    if len(sys.argv) != 4:
        return fail("Tailscale enrollment requires machine, domain and privilege mode")
    machine, _domain, root_mode = sys.argv[1:]
    try:
        result = subprocess.run(["bw", "get", "item", "tailscale-apikey"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=True, text=True)
        key = json.loads(result.stdout)["login"]["password"]
        if not isinstance(key, str) or not key.strip():
            raise ValueError("empty key")
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        return fail("Unable to read a nonempty Tailscale key from Bitwarden")

    # Cleanup is best effort. Suppress the helper's output: API errors may
    # contain credentials, and a failed release must not prevent joining.
    repo = os.environ.get("DOTFILES_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    environment = os.environ.copy()
    environment.pop("BW_SESSION", None)
    environment["TS_OAUTH_CLIENT_SECRET"] = key
    try:
        released = subprocess.run([sys.executable, os.path.join(repo, "scripts", "tailnet.py"),
                                   "release", machine], env=environment,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if released.returncode:
            print("warn: Tailscale stale-device cleanup failed; continuing with join")
    except OSError:
        print("warn: Tailscale stale-device cleanup failed; continuing with join")
    finally:
        environment.pop("TS_OAUTH_CLIENT_SECRET", None)

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
            # Neither the vault session nor the OAuth secret is needed by tailscale.
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
