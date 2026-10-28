#!/usr/bin/env python3
"""SSH units' shared, locked implementation; fleet data remains in inventory/vars."""
import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from osquery_native_inventory import group_contains, load_inventory

ROOT = Path(os.environ["DOTFILES_DIR"])
HOME = Path(os.environ["HOME"])
SSH = HOME / ".ssh"
MACHINE = os.environ["DOTFILES_MACHINE"]
BEGIN = "# BEGIN dotfiles SSH fleet"
END = "# END dotfiles SSH fleet"
AK_BEGIN = "# BEGIN dotfiles Bitwarden SSH keys"
AK_END = "# END dotfiles Bitwarden SSH keys"
RETIRED = {"matrix", "telengana"}
CHECK = os.environ.get("UNITS_CHECK") == "1"
PLANNED = {}


def run(args, *, data=None, env=None, timeout=30):
    return subprocess.run(args, input=data, text=True, capture_output=True, env=env, timeout=timeout)


def yaml_file(path, *, allow_empty=False):
    if allow_empty:
        lines = [line.split("#", 1)[0].strip() for line in path.read_text().splitlines()]
        if [line for line in lines if line] in ([], ["---"]):
            return {}
    try:
        result = run(["yq", "-o=json", ".", str(path)])
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0:
        value = json.loads(result.stdout)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(f"cannot read {path}: install yq or Python PyYAML") from exc
        try:
            value = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid YAML mapping: {path}")
    return value


def atomic(path, content, mode):
    if path.is_symlink():
        raise RuntimeError(f"refusing to replace symlink: {path}")
    if CHECK:
        if path.exists() and not path.is_file():
            raise RuntimeError(f"not a regular file: {path}")
        previous = text(path)
        if not path.exists() or previous != content or stat.S_IMODE(path.stat().st_mode) != mode:
            print(f"would write {path} (mode {mode:04o})")
        else:
            print(f"ok    {path}")
        PLANNED[path] = content
        return
    if path.exists() and path.read_text() == content:
        path.chmod(mode)
        return
    fd, name = tempfile.mkstemp(prefix=".ssh-fleet-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), mode)
            f.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def text(path):
    if CHECK and path in PLANNED:
        return PLANNED[path]
    return path.read_text() if path.exists() else ""


def split_block(original, begin, end):
    lines = original.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == begin]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == end]
    if len(starts) != len(ends) or len(starts) > 1 or (starts and starts[0] >= ends[0]):
        raise ValueError("malformed managed block")
    if not starts:
        return original, "", "", False
    start, finish = starts[0], ends[0]
    return "".join(lines[:start]), "".join(lines[start + 1:finish]), "".join(lines[finish + 1:]), True


def replace_block(original, begin, end, lines):
    before, _, after, found = split_block(original, begin, end)
    block = begin + "\n" + "\n".join(lines) + "\n" + end + "\n"
    if not found and before and not before.endswith("\n"):
        before += "\n"
    return before + block + after


def key_parts(key):
    if not isinstance(key, str):
        raise ValueError("invalid ed25519 public key")
    key = key.strip()
    if "\n" in key or "\r" in key:
        raise ValueError("invalid multiline public key")
    parts = key.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise ValueError("invalid ed25519 public key")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except ValueError as exc:
        raise ValueError("invalid ed25519 public key") from exc
    if len(blob) != 51 or blob[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20":
        raise ValueError("invalid ed25519 public key")
    return parts[:2]


def encrypted_public_key(private):
    # OpenSSH exposes an unauthenticated public key in its encrypted envelope.
    # Matching it catches a mismatched .pub, but cannot validate the ciphertext.
    lines = private.strip().splitlines()
    if len(lines) < 3 or lines[0] != "-----BEGIN OPENSSH PRIVATE KEY-----" or lines[-1] != "-----END OPENSSH PRIVATE KEY-----":
        raise RuntimeError("cannot inspect encrypted SSH private key")
    try:
        blob = base64.b64decode("".join(lines[1:-1]), validate=True)
        magic = b"openssh-key-v1\x00"
        if not blob.startswith(magic):
            raise ValueError()
        pos = len(magic)

        def field():
            nonlocal pos
            if pos + 4 > len(blob):
                raise ValueError()
            size = int.from_bytes(blob[pos:pos + 4], "big")
            pos += 4
            if size > len(blob) - pos:
                raise ValueError()
            value = blob[pos:pos + size]
            pos += size
            return value

        cipher, kdf, options = field(), field(), field()
        ciphers = {
            b"aes128-ctr": (16, 0), b"aes192-ctr": (16, 0), b"aes256-ctr": (16, 0),
            b"aes128-cbc": (16, 0), b"aes192-cbc": (16, 0), b"aes256-cbc": (16, 0),
            b"3des-cbc": (8, 0), b"aes128-gcm@openssh.com": (16, 16),
            b"aes256-gcm@openssh.com": (16, 16), b"chacha20-poly1305@openssh.com": (8, 16),
        }
        if cipher not in ciphers or kdf != b"bcrypt" or len(options) < 9 or pos + 4 > len(blob):
            raise ValueError()
        salt_len = int.from_bytes(options[:4], "big")
        if not salt_len or len(options) != 8 + salt_len or not int.from_bytes(options[-4:], "big"):
            raise ValueError()
        count = int.from_bytes(blob[pos:pos + 4], "big")
        pos += 4
        if count != 1:
            raise ValueError()
        public = field()
        encrypted = field()
        block_size, tag_size = ciphers[cipher]
        if len(encrypted) < block_size or len(encrypted) % block_size or len(blob) - pos != tag_size:
            raise ValueError()
        return key_parts("ssh-ed25519 " + base64.b64encode(public).decode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("cannot inspect encrypted SSH private key") from exc


def inspect_private_key(private, public, *, private_path=None):
    try:
        if private_path is not None:
            result = run(["ssh-keygen", "-y", "-P", "", "-f", str(private_path)])
            if result.returncode:
                raise RuntimeError("cannot validate SSH private key without prompting")
            return key_parts(result.stdout), True
        return derive_private_key(private), True
    except RuntimeError:
        if not public.exists():
            raise RuntimeError("encrypted or invalid SSH private key requires an existing public key")
        parts = encrypted_public_key(private)
        if key_parts(public.read_text()) != parts:
            raise RuntimeError("local SSH private and public keys do not match")
        print("PARTIAL: encrypted SSH key envelope matches; private contents cannot be verified without a passphrase")
        return parts, False


def ssh_data(item):
    data = item.get("sshKey") or {}
    if not isinstance(data, dict):
        raise ValueError("invalid Bitwarden SSH item")
    return data

def session_env():
    if os.environ.get("UNITS_NO_SECRETS") == "1":
        return None
    session = os.environ.get("BW_SESSION", "")
    if not session:
        try:
            session = Path("/tmp/bw_session").read_text().strip()
        except OSError:
            pass
    if not session:
        return None
    env = dict(os.environ, BW_SESSION=session)
    try:
        if run(["bw", "unlock", "--check"], env=env).returncode == 0:
            return env
    except (OSError, subprocess.SubprocessError):
        pass
    return None


class Fleet:
    def __init__(self):
        self.vars = yaml_file(ROOT / "group_vars/all.yml")
        host_file = ROOT / "host_vars" / (MACHINE + ".yml")
        local_vars = yaml_file(host_file, allow_empty=True) if host_file.exists() else {}
        fields = ("ansible_user", "ansible_port", "tailnet_name", "user_login", "user_email",
                  "machines", "machine_pubkeys", "ssh_mesh_exclude", "extra_authorized_keys",
                  "ssh_keys_force_push", "ssh_keys_force_authorized", "machine_profile", "skip_ssh_mesh")
        inventory = load_inventory(ROOT / "inventory.yml", fields=fields)
        self.hosts = inventory["_meta"]["hostvars"]
        self.host_vars = self.hosts.get(MACHINE, local_vars)
        self.vars.update(self.host_vars)
        self.vps = {name for name in self.hosts if group_contains(inventory, "vps", name)}
        self.login = self.vars["user_login"]
        self.email = self.vars["user_email"]
        self.machines = self.vars["machines"]
        self.env = None
        self.items = None
        self.key_ready = False
        self.key_verified = False
        self.key_deferred = False
        self.failed = False

    def step(self, label, fn):
        try:
            fn()
            print("ok    " + label)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
            # Never include subprocess stderr or private-key material in output.
            print("FAIL  " + label + ": " + str(exc))
            self.failed = True

    def unlock(self):
        self.env = session_env()
        if self.env is None:
            print("PARTIAL: vault locked or secrets disabled; Bitwarden SSH sync skipped")
            return
        result = run(["bw", "list", "items"], env=self.env, timeout=90)
        if result.returncode:
            raise RuntimeError("Bitwarden item listing failed; refusing to treat it as an empty vault")
        items = json.loads(result.stdout)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("invalid Bitwarden item listing")
        self.items = items

    def vault_item(self):
        if self.env is None:
            raise RuntimeError("Bitwarden session unavailable; refusing to generate a key")
        if self.items is None:
            raise RuntimeError("Bitwarden listing unavailable; refusing to generate or overwrite a key")
        name = f"{self.login}@{MACHINE}"
        matches = [i for i in self.items if isinstance(i, dict) and i.get("name") == name]
        if len(matches) > 1:
            raise RuntimeError("multiple Bitwarden SSH items have this machine name")
        if not matches:
            return None
        result = run(["bw", "get", "item", matches[0].get("id") or name], env=self.env)
        if result.returncode:
            raise RuntimeError("cannot retrieve machine SSH item from Bitwarden")
        item = json.loads(result.stdout)
        if not isinstance(item, dict) or item.get("name") != name:
            raise ValueError("invalid machine SSH item")
        return item

    def ensure_key(self):
        private, public = SSH / "id_ed25519", SSH / "id_ed25519.pub"
        if private.is_symlink() or public.is_symlink():
            raise RuntimeError("refusing to replace or chmod symlinked SSH keys")
        if not private.exists():
            if self.env is None:
                self.key_deferred = True
                print("PARTIAL: SSH identity deferred until an unlocked Bitwarden listing is available (run an unlocked apply)")
                return
            item = self.vault_item()
            if item is not None:
                key = ssh_data(item)
                priv, pub = key.get("privateKey"), key.get("publicKey")
                if not isinstance(priv, str) or not priv or not isinstance(pub, str) or not pub:
                    raise RuntimeError("machine's Bitwarden SSH item has no complete key pair")
                key_parts(pub)
                if public.exists() and key_parts(public.read_text()) != key_parts(pub):
                    raise RuntimeError("existing public key conflicts with Bitwarden key")
                # Validate the private key in a private temporary file before installation.
                fd, name = tempfile.mkstemp(prefix=".ssh-key-", dir=SSH)
                try:
                    with os.fdopen(fd, "w") as f:
                        f.write(priv.rstrip("\n") + "\n")
                    derived = run(["ssh-keygen", "-y", "-P", "", "-f", name])
                    if derived.returncode:
                        try:
                            restored_public = encrypted_public_key(priv)
                        except RuntimeError as exc:
                            raise RuntimeError("Bitwarden SSH key pair is invalid or does not match") from exc
                    else:
                        restored_public = key_parts(derived.stdout)
                    if restored_public != key_parts(pub):
                        raise RuntimeError("Bitwarden SSH key pair is invalid or does not match")
                    atomic(public, pub.rstrip("\n") + "\n", 0o644)
                    os.replace(name, private)
                finally:
                    if os.path.exists(name):
                        os.unlink(name)
            else:
                if public.exists():
                    raise RuntimeError("public key exists without private key; refusing to overwrite it")
                result = run(["ssh-keygen", "-q", "-t", "ed25519", "-C", MACHINE,
                              "-f", str(private), "-N", ""])
                if result.returncode:
                    raise RuntimeError("ssh-keygen failed")
        private.chmod(0o600)
        derived_parts, self.key_verified = inspect_private_key(private.read_text(), public, private_path=private)
        if not public.exists():
            atomic(public, " ".join(derived_parts) + " " + MACHINE + "\n", 0o644)
        if key_parts(public.read_text()) != derived_parts:
            raise RuntimeError("local SSH private and public keys do not match")
        private.chmod(0o600)
        public.chmod(0o644)
        self.key_ready = True

    def sync_key(self):
        if self.env is None:
            return
        if not self.key_ready:
            raise RuntimeError("local SSH key unavailable; Bitwarden unchanged")
        item = self.vault_item()
        private, public = SSH / "id_ed25519", SSH / "id_ed25519.pub"
        pub = " ".join(key_parts(public.read_text()))
        if item is not None:
            saved = ssh_data(item).get("publicKey", "")
            if saved and key_parts(saved) == key_parts(pub):
                return
            force = os.environ.get("SSH_KEYS_FORCE_PUSH", str(self.host_vars.get("ssh_keys_force_push", self.vars.get("ssh_keys_force_push", "false"))))
            if force.lower() not in ("true", "1", "yes"):
                print("WARNING: local SSH key differs from Bitwarden; vault left unchanged (set SSH_KEYS_FORCE_PUSH=true for an intentional rotation)")
                return
        if not self.key_verified:
            print("PARTIAL: encrypted SSH key not verified; Bitwarden key left unchanged")
            return
        fingerprint = run(["ssh-keygen", "-lf", str(public)])
        if fingerprint.returncode or len(fingerprint.stdout.split()) < 2:
            raise RuntimeError("cannot determine SSH fingerprint")
        if item is None:
            item = {"type": 5, "name": f"{self.login}@{MACHINE}"}
        item["sshKey"] = {"privateKey": private.read_text(), "publicKey": pub,
                          "keyFingerprint": fingerprint.stdout.split()[1]}
        encoded = run(["bw", "encode"], data=json.dumps(item), env=self.env)
        if encoded.returncode:
            raise RuntimeError("Bitwarden SSH item encoding failed")
        args = ["bw", "create", "item"] if not item.get("id") else ["bw", "edit", "item", item["id"]]
        if run(args, data=encoded.stdout, env=self.env).returncode:
            raise RuntimeError("Bitwarden SSH item write failed")
        # Include the just-created/updated item in this run's authorization
        # batch; the original listing was taken before the vault write.
        self.items = [old for old in self.items if old.get("name") != item["name"]] + [item]

    def config(self):
        path = SSH / "config"
        old = text(path)
        # Adopt the exact static header from the former role, then only its
        # recognizable host stanzas. Other user entries are never removed.
        legacy = ("Host *\n  AddKeysToAgent yes\n  IdentityFile ~/.ssh/id_ed25519\n"
                  "  ServerAliveInterval 30\n  ServerAliveCountMax 3\n"
                  "  # Reuse connections — big speedup for repeated SSH to the same host\n"
                  "  ControlMaster auto\n  ControlPersist 10m\n  ControlPath ~/.ssh/cp/%C\n"
                  "  # Don't hash known_hosts so tab-completion and doctor checks work\n"
                  "  HashKnownHosts no\n  # Compression on slow links; negligible on LAN/Tailscale\n"
                  "  Compression yes\n\n")
        if old.startswith(legacy):
            old = old[len(legacy):]
            for name in self.machines:
                pattern = (r"(?m)^Host " + re.escape(name) + r"\n  HostName [^\n]+\n"
                           r"(?:  Port [0-9]+\n)?  User [^\n]+\n  SendEnv BW_SESSION\n\n")
                old = re.sub(pattern, "", old, count=1)
        lines = ["Host *", "  AddKeysToAgent yes", "  IdentityFile ~/.ssh/id_ed25519",
                 "  ServerAliveInterval 30", "  ServerAliveCountMax 3", "  ControlMaster auto",
                 "  ControlPersist 10m", "  ControlPath ~/.ssh/cp/%C", "  HashKnownHosts no",
                 "  Compression yes", ""]
        for name, info in self.machines.items():
            host = self.hosts.get(name) or {}
            lines += [f"Host {name}", f"  HostName {info['hostname']}"]
            if "ansible_port" in host:
                lines.append(f"  Port {host['ansible_port']}")
            lines += [f"  User {host.get('ansible_user', self.login)}", "  SendEnv BW_SESSION", ""]
        atomic(path, replace_block(old, BEGIN, END, lines), 0o644)
        if CHECK:
            check_directory(SSH / "cp", 0o700)
        else:
            (SSH / "cp").mkdir(mode=0o700, exist_ok=True)
            (SSH / "cp").chmod(0o700)

    def signers(self):
        if self.key_deferred:
            print("PARTIAL: allowed signers deferred until SSH identity is available")
            return
        if not self.key_ready:
            raise RuntimeError("local SSH key unavailable")
        pub = text(SSH / "id_ed25519.pub").strip()
        key_parts(pub)
        line = f'{self.email} namespaces="git" {pub}'
        path = SSH / "allowed_signers"
        old = text(path)
        if line not in old.splitlines():
            old += ("\n" if old and not old.endswith("\n") else "") + line + "\n"
        atomic(path, old, 0o644)

    def authorize_vault(self):
        if self.env is None:
            return
        if self.items is None:
            raise RuntimeError("Bitwarden listing unavailable; authorized_keys unchanged")
        names = {f"{self.login}@{name}" for name in self.machines}
        keys = []
        for item in self.items:
            if not isinstance(item, dict) or item.get("name") not in names:
                continue
            pub = ssh_data(item).get("publicKey", "")
            if not isinstance(pub, str):
                raise ValueError("invalid Bitwarden public key")
            pub = pub.strip()
            if pub:
                key_parts(pub)
                keys.append(pub)
        if not keys:
            print("PARTIAL: no fleet SSH keys in Bitwarden; authorized_keys unchanged")
            return
        keys += self.host_vars.get("extra_authorized_keys", self.vars.get("extra_authorized_keys", [])) or []
        for key in keys:
            if not isinstance(key, str) or "\n" in key or "\r" in key:
                raise ValueError("invalid extra authorized key")
        path = SSH / "authorized_keys"
        old = text(path)
        # Force can remove only entries previously managed in our block; older
        # unmarked entries are indistinguishable from user keys and stay intact.
        force = os.environ.get("SSH_KEYS_FORCE_AUTHORIZED", str(self.host_vars.get("ssh_keys_force_authorized", self.vars.get("ssh_keys_force_authorized", "false"))))
        before, managed, after, _ = split_block(old, AK_BEGIN, AK_END)
        previous = managed.splitlines()
        if force.lower() not in ("true", "1", "yes"):
            keys = previous + keys
        outside = before + after
        existing = set(outside.splitlines())
        unique = list(dict.fromkeys(k.strip() for k in keys if k.strip() and k.strip() not in existing))
        atomic(path, replace_block(old, AK_BEGIN, AK_END, unique), 0o600)

    def authorize_git(self):
        keys = self.vars.get("machine_pubkeys") or {}
        path = SSH / "authorized_keys"
        old = text(path)
        before, _, after, _ = split_block(old, AK_BEGIN, AK_END)
        outside = before + after
        existing = set(outside.splitlines())
        for key in keys.values():
            key_parts(key)
            if key not in existing:
                old += ("\n" if old and not old.endswith("\n") else "") + key + "\n"
                existing.add(key)
        if keys:
            atomic(path, old, 0o600)
        if self.key_ready:
            own = text(SSH / "id_ed25519.pub")
            committed = keys.get(MACHINE, "")
            if not committed or key_parts(committed) != key_parts(own):
                print(f"WARNING: {MACHINE}'s SSH public key is missing or stale in group_vars/all.yml: {own.strip()}")

    def host_data(self, name):
        info = self.machines[name]
        host = self.hosts.get(name) or {}
        return info["hostname"], int(host.get("ansible_port", 22)), host.get("ansible_user", self.login)

    def scan(self, name):
        host, port, _ = self.host_data(name)
        kh = host if port == 22 else f"[{host}]:{port}"
        result = run(["ssh-keyscan", "-t", "ed25519", "-T", "5", "-p", str(port), host], timeout=8)
        if result.returncode:
            return False
        keys = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == kh:
                key_parts(" ".join(parts[1:]))
                keys.append(line)
        if not keys:
            return False
        path = SSH / "known_hosts"
        if path.is_symlink():
            raise RuntimeError("refusing to replace symlinked known_hosts")
        old = text(path)
        def matches(token):
            if not token.startswith("|1|"):
                return token.lower() == kh.lower()
            try:
                _, version, salt, digest = token.split("|")
                if version != "1":
                    return False
                actual = hmac.new(base64.b64decode(salt, validate=True), kh.encode(), hashlib.sha1).digest()
                return hmac.compare_digest(actual, base64.b64decode(digest, validate=True))
            except ValueError:
                return False

        kept, current = [], []
        for line in old.splitlines(keepends=True):
            parts = line.split(None, 1)
            if len(parts) != 2 or parts[0].startswith(("#", "@")):
                kept.append(line)
                continue
            names = parts[0].split(",")
            if not any(matches(token) for token in names):
                kept.append(line)
                continue
            current.append(parts[1].strip())
            remaining = [token for token in names if not matches(token)]
            if remaining:
                kept.append(",".join(remaining) + " " + parts[1])
        if sorted(current) == sorted(line.split(None, 1)[1] for line in keys):
            if CHECK:
                atomic(path, old, 0o644)
            else:
                path.chmod(0o644)
            return True
        content = "".join(kept)
        content += ("\n" if content and not content.endswith("\n") else "") + "\n".join(keys) + "\n"
        atomic(path, content, 0o644)
        return True

    def known_hosts(self):
        for name in self.machines:
            if name != MACHINE and name not in RETIRED:
                try:
                    self.scan(name)
                except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError) as exc:
                    print(f"warn: cannot refresh host key for {name}: {exc}")

    def mesh(self):
        if not self.key_ready:
            print("PARTIAL: SSH mesh probes deferred until SSH identity is available")
            return
        result = run(["python3", str(ROOT / "scripts/online_hosts.py"), "--peers"], timeout=15)
        if result.returncode:
            raise RuntimeError("cannot determine online tailnet peers")
        online = set(result.stdout.splitlines())
        excluded = set(self.host_vars.get("ssh_mesh_exclude", self.vars.get("ssh_mesh_exclude")) or []) | self.vps | RETIRED | {MACHINE}
        targets = [name for name in self.machines if name not in excluded
                   and (self.hosts.get(name) or {}).get("tailnet_name", name).lower() in online]
        failed = []
        for name in targets:
            host, port, user = self.host_data(name)
            target = f"{user}@{host}"
            args = ["ssh", "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
                    "-o", "ControlMaster=no", "-o", "ControlPath=none", "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ConnectTimeout=8", "-p", str(port), target, "true"]
            try:
                probe = run(args, timeout=15)
                if probe.returncode == 0:
                    continue
            except subprocess.TimeoutExpired:
                pass
            try:
                run(["ssh", "-O", "exit", "-p", str(port), target], timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # Never remove the old known-host entry unless a usable scan succeeds.
            try:
                self.scan(name)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError) as exc:
                print(f"warn: cannot refresh host key for {name}: {exc}")
            try:
                if run(args, timeout=15).returncode == 0:
                    continue
            except subprocess.TimeoutExpired:
                pass
            failed.append(name)
        if failed:
            raise RuntimeError("SSH mesh broken to: " + ", ".join(failed))
        print("SSH mesh OK: " + (", ".join(targets) if targets else "no fleet peers online"))


def check_directory(path, mode):
    if not path.exists():
        print(f"would create {path} (mode {mode:04o})")
    elif not path.is_dir():
        raise RuntimeError(f"not a directory: {path}")
    elif stat.S_IMODE(path.stat().st_mode) != mode:
        print(f"would set {path} mode {mode:04o}")
    else:
        print(f"ok    {path}")


def derive_private_key(private):
    # Validate in an anonymous fd without chmodding the key or prompting.
    if not hasattr(os, "memfd_create"):
        raise RuntimeError("SSH key inspection requires memfd_create")
    fd = os.memfd_create("ssh-fleet-key", 0)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(os.dup(fd), "w") as f:
            f.write(private.rstrip("\n") + "\n")
        result = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", f"/proc/self/fd/{fd}"],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=30, pass_fds=(fd,))
        if result.returncode:
            raise RuntimeError("cannot validate SSH private key without prompting")
        return key_parts(result.stdout)
    finally:
        os.close(fd)


class CheckFleet(Fleet):
    def ensure_key(self):
        private, public = SSH / "id_ed25519", SSH / "id_ed25519.pub"
        if private.is_symlink() or public.is_symlink():
            raise RuntimeError("refusing to replace or chmod symlinked SSH keys")
        if not private.exists():
            self.key_deferred = True
            print("PARTIAL: SSH identity restoration or generation depends on the vault")
            return
        if not private.is_file():
            raise RuntimeError(f"not a regular file: {private}")
        derived, self.key_verified = inspect_private_key(private.read_text(), public)
        if stat.S_IMODE(private.stat().st_mode) != 0o600:
            print(f"would set {private} mode 0600")
        if not public.exists():
            atomic(public, " ".join(derived) + " " + MACHINE + "\n", 0o644)
        elif not public.is_file() or key_parts(public.read_text()) != derived:
            raise RuntimeError("local SSH private and public keys do not match")
        elif stat.S_IMODE(public.stat().st_mode) != 0o644:
            print(f"would set {public} mode 0644")
        self.key_ready = True

    def known_hosts(self):
        failed = False
        for name in self.machines:
            if name != MACHINE and name not in RETIRED:
                try:
                    if not self.scan(name):
                        raise RuntimeError("no usable host key returned")
                except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError) as exc:
                    print(f"FAIL  cannot inspect host key for {name}: {exc}")
                    failed = True
        if failed:
            raise RuntimeError("one or more SSH host keys could not be inspected")

    def mesh(self):
        if not self.key_ready:
            print("PARTIAL: SSH mesh probes deferred until SSH identity is available")
            return
        result = run(["tailscale", "status", "--json"], timeout=15)
        if result.returncode:
            raise RuntimeError("cannot inspect online tailnet peers")
        status = json.loads(result.stdout)
        if not isinstance(status, dict):
            raise ValueError("invalid tailnet status")
        peers = status.get("Peer") or {}
        if not isinstance(peers, dict):
            raise ValueError("invalid tailnet peer listing")
        online = set()
        for peer in peers.values():
            if not isinstance(peer, dict):
                raise ValueError("invalid tailnet peer listing")
            if peer.get("Online"):
                online.add(((peer.get("DNSName") or "").split(".")[0] or peer.get("HostName") or "").lower())
        excluded = set(self.host_vars.get("ssh_mesh_exclude", self.vars.get("ssh_mesh_exclude")) or []) | self.vps | RETIRED | {MACHINE}
        targets = [name for name in self.machines if name not in excluded
                   and (self.hosts.get(name) or {}).get("tailnet_name", name).lower() in online]
        print("online SSH mesh targets: " + (", ".join(targets) if targets else "none"))
        if targets:
            raise RuntimeError("SSH authentication, retries and host-key refresh cannot safely be probed in check mode")


def check_main(mode):
    fleet = CheckFleet()
    if mode == "mesh" and (fleet.host_vars.get("machine_profile") == "vm-test" or fleet.host_vars.get("skip_ssh_mesh", False)):
        print("SKIPPED: SSH mesh disabled for this profile")
        return 0
    fleet.step("SSH directory", lambda: check_directory(SSH, 0o700))
    if os.environ.get("UNITS_NO_SECRETS") != "1" and (mode == "keys" or not (SSH / "id_ed25519").exists()):
        print("FAIL  cannot inspect Bitwarden SSH keys safely: item reads may persist audit events")
        fleet.failed = True
    fleet.step("SSH key pair", fleet.ensure_key)
    if mode == "keys":
        fleet.step("SSH config", fleet.config)
        if os.environ.get("UNITS_NO_SECRETS") == "1":
            print("SKIPPED: Bitwarden SSH synchronization (--no-secrets)")
        fleet.step("allowed signers", fleet.signers)
        fleet.step("known hosts", fleet.known_hosts)
    elif mode == "mesh":
        fleet.step("fleet authorized keys", fleet.authorize_git)
        fleet.step("mesh targets", fleet.mesh)
    else:
        raise ValueError("invalid mode")
    return int(fleet.failed)


def main(mode):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", MACHINE) or MACHINE in (".", ".."):
        raise ValueError("invalid machine name")
    if CHECK:
        return check_main(mode)
    SSH.mkdir(mode=0o700, exist_ok=True)
    SSH.chmod(0o700)
    lock_path = SSH / ".dotfiles-ssh.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fleet = Fleet()
        if mode == "mesh" and (fleet.host_vars.get("machine_profile") == "vm-test" or fleet.host_vars.get("skip_ssh_mesh", False)):
            print("SKIPPED: SSH mesh disabled for this profile")
            return 0
        # Mesh normally needs no vault; only consult it before creating a
        # missing identity, preventing a race with the keys unit's restore.
        if mode == "keys" or not (SSH / "id_ed25519").exists():
            fleet.step("Bitwarden session", fleet.unlock)
        fleet.step("SSH key pair", fleet.ensure_key)
        if mode == "keys":
            fleet.step("SSH config", fleet.config)
            fleet.step("Bitwarden SSH key sync", fleet.sync_key)
            fleet.step("allowed signers", fleet.signers)
            fleet.step("known hosts", fleet.known_hosts)
            fleet.step("Bitwarden authorized keys", fleet.authorize_vault)
        elif mode == "mesh":
            fleet.step("fleet authorized keys", fleet.authorize_git)
            fleet.step("mesh probes", fleet.mesh)
        else:
            raise ValueError("invalid mode")
        return int(fleet.failed)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1]))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        print("FAIL  SSH fleet: " + str(exc), file=sys.stderr)
        sys.exit(1)
