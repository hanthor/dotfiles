#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pexpect==4.9.0"]
# ///
"""Install through the real TUI, then exercise the UEFI-booted node disks."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import time

import pexpect

USER = "nodeadmin"
PASSWORD = "Disposable-Tui-Only-42!"
PAYLOAD = "oci:/usr/share/home-k8s/payload"
PROMPT = "NODE_SMOKE_PROMPT> "
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class VM:
    def __init__(self, args, node, *, live=False, lan_port=None, outbound=False):
        self.node = node
        self.artifacts = args.artifacts
        self.child = None
        disk = args.artifacts / f"{node}-installed.qcow2"
        variables = args.artifacts / f"{node}-OVMF-VARS.fd"
        if live:
            if disk.exists() or variables.exists():
                raise RuntimeError(f"Refusing to overwrite an existing VM disk or NVRAM: {disk}")
            subprocess.run(["qemu-img", "create", "-f", "qcow2", str(disk), "32G"], check=True)
            shutil.copyfile("/usr/share/OVMF/OVMF_VARS_4M.fd", variables)
        elif not disk.is_file() or not variables.is_file():
            raise RuntimeError(f"Install {node} through the TUI first")
        memory = "4096" if live else ("2816" if node == "bihar" else "2304")
        qemu = ["-machine", f"q35,accel={args.accel}", "-cpu", "host" if args.accel == "kvm" else "max",
                "-smp", "2", "-m", memory,
                "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
                "-drive", f"if=pflash,format=raw,file={variables}",
                "-drive", f"if=virtio,format=qcow2,file={disk}",
                "-display", "none", "-chardev", "stdio,id=console,signal=off",
                "-serial", "chardev:console", "-monitor", "none", "-no-reboot",
                "-netdev", f"user,id=nat,restrict={'off' if lan_port or outbound else 'on'}",
                "-device", "virtio-net-pci,netdev=nat"]
        if live:
            qemu += ["-cdrom", str(args.artifacts / f"{node}-installer.iso"), "-boot", "order=d"]
        else:
            qemu += ["-boot", "order=c"]
        if lan_port:
            connection = "listen" if node == "bihar" else "connect"
            suffix = "05" if node == "bihar" else "06"
            qemu += ["-netdev", f"socket,id=lan,{connection}=127.0.0.1:{lan_port}",
                     "-device", f"virtio-net-pci,netdev=lan,mac=52:54:00:24:00:{suffix}"]
        self.log = (args.artifacts / f"{node}-{'install' if live else 'boot'}-{time.time_ns()}.log").open("w", buffering=1)
        try:
            self.child = pexpect.spawn("qemu-system-x86_64", qemu, encoding="utf-8", codec_errors="replace",
                                       dimensions=(40, 140), timeout=300, maxread=65536, searchwindowsize=100000)
            self.child.logfile_read = self.log
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.child is not None:
            if self.child.isalive():
                self.child.terminate(force=True)
            self.child.close()
        self.log.close()

    def send(self, text):
        self.child.send(text)
        time.sleep(0.5)

    def page(self, number):
        self.child.expect(f"Step {number} of 9:", timeout=60)
        print(f"{self.node}: actual TUI page {number}", flush=True)
        time.sleep(0.5)

    def root_login(self):
        self.child.expect("login:", timeout=600)
        self.child.sendline(USER)
        self.child.expect("Password:")
        self.child.sendline(PASSWORD)
        self.child.expect(r"(?m)[^\r\n]*\$ ", timeout=60)
        self.child.sendline("stty -echo; unset PROMPT_COMMAND")
        self.child.expect(r"\$ ", timeout=30)
        self.child.sendline("sudo -k; sudo -v")
        outcome = self.child.expect([r"\[sudo\] password for .*:", r"\$ "], timeout=30)
        if outcome == 0:
            self.child.sendline(PASSWORD)
            self.child.expect(r"\$ ", timeout=30)
        self.child.sendline("sudo bash --noprofile --norc")
        self.child.expect(r"(?m)[^\r\n]*# ", timeout=30)
        self.root_prompt()

    def root_prompt(self):
        # Disable echo before assigning PS1: matching the echoed assignment would
        # race the shell. Readline/OSC control sequences may precede the prompt.
        self.child.sendline("stty -echo; unset PROMPT_COMMAND")
        self.child.expect(r"# ", timeout=30)
        self.child.sendline(f"export PS1='{PROMPT}'")
        self.child.expect_exact(PROMPT, timeout=30)

    def run(self, script, *, timeout=240):
        encoded = base64.b64encode(script.encode()).decode()
        marker = "COMMAND_RESULT_" + secrets.token_hex(8)
        self.child.sendline("base64 -d > /run/home-k8s-proof.sh <<'HOME_K8S_SCRIPT'")
        for offset in range(0, len(encoded), 512):
            self.child.sendline(encoded[offset:offset + 512])
        self.child.sendline("HOME_K8S_SCRIPT")
        self.child.sendline(f"bash -euo pipefail /run/home-k8s-proof.sh; result=$?; printf '\\n{marker}:%s\\n' \"$result\"")
        self.child.expect(rf"(?m)^{marker}:([0-9]+)\r*\n", timeout=timeout)
        output = ANSI.sub("", self.child.before).replace("\r", "")
        if self.child.match.group(1) != "0":
            raise RuntimeError(f"{self.node}: guest command failed:\n{output[-16000:]}")
        self.child.expect(PROMPT)
        return output

    def poweroff(self):
        self.child.sendline("sync; poweroff")
        self.child.expect(pexpect.EOF, timeout=120)

    def reboot(self):
        # -no-reboot makes QEMU exit on the guest's actual reboot request.
        # The next VM starts the same disk/NVRAM, without any installer media.
        self.child.sendline("sync; systemctl reboot")
        self.child.expect(pexpect.EOF, timeout=180)


def inactive_k3s():
    return '''test ! -e /etc/rancher/k3s/activate
for role in server agent; do
  state=$(systemctl show "k3s@$role.service" --property=ActiveState --value)
  test "$state" = inactive
  test "$(systemctl show "k3s@$role.service" --property=ExecMainStartTimestampMonotonic --value)" = 0
done
if pgrep -x k3s; then exit 1; fi
'''


def starter_readiness():
    # This checks shipped support, not whether absent physical hardware works.
    return '''for module in amdgpu i915 xe kvm_intel kvm_amd iwlwifi mt7925e rtw89_8852be r8169; do
  modinfo -k "$(uname -r)" "$module" >/dev/null
done
rpm -q NetworkManager-wifi wpa_supplicant
command -v wpa_supplicant
python3 - <<'PY'
from pathlib import Path
assert list(Path("/usr/lib64/NetworkManager").glob("**/libnm-device-plugin-wifi.so")), "Missing actual NetworkManager WiFi plugin"
firmware = Path("/usr/lib/firmware")
required_firmware = (
    ("intel-ucode/*",), ("amdgpu/gc_11_5_1*.bin*",),
    ("i915/*",), ("xe/*",),
    ("iwlwifi-*.ucode*", "intel/iwlwifi/iwlwifi-*.ucode*"),
    ("mediatek/mt7925/WIFI_RAM_CODE_MT7925_1_1.bin*",),
    ("mediatek/mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin*",),
)
for patterns in required_firmware:
    assert any(path.is_file() for pattern in patterns for path in firmware.glob(pattern)), f"Missing firmware: {patterns}"
print("STARTER_HARDWARE_PAYLOAD_PASSED: modules, firmware, NetworkManager WiFi plugin, supplicant; no physical RF/GPU claim")
PY
for role in server agent; do
  state=$(systemctl is-enabled "k3s@$role.service" 2>/dev/null || true)
  test "$state" = disabled
done
test ! -e /etc/rancher/k3s/config.yaml
test ! -e /etc/rancher/k3s/token
if test -d /etc/rancher/k3s/config.yaml.d; then
  test -z "$(find /etc/rancher/k3s/config.yaml.d -mindepth 1 -print -quit)"
fi
'''


def assert_identity(identity):
    if not re.fullmatch(r"[0-9a-f]{32}", identity["machine_id"]) or identity["machine_id"] == "0" * 32:
        raise RuntimeError("Missing or invalid installed machine identity")
    if not identity["iqn"].startswith("InitiatorName=iqn."):
        raise RuntimeError("Missing installed iSCSI identity")


def assert_distinct_identities(artifacts, *, required=()):
    identities = {}
    for node in ("starter", "bihar", "karnataka"):
        path = artifacts / f"{node}-identity.json"
        if node in required or path.is_file():
            identities[node] = json.loads(path.read_text())
            assert_identity(identities[node])
    for key in ("machine_id", "iqn"):
        values = [identity[key] for identity in identities.values()]
        if len(values) != len(set(values)):
            raise RuntimeError(f"Cloned installed node identity: {key}")


def bootc_image(status, deployment):
    entry = status["status"].get(deployment)
    if not entry or not entry.get("image"):
        raise RuntimeError(f"Missing {deployment} bootc image")
    image = entry["image"]
    reference = image["image"]
    if reference.get("transport") != "registry":
        raise RuntimeError(f"Unexpected {deployment} bootc transport: {reference!r}")
    return reference["image"], image["imageDigest"]


def switch_state_script():
    return '''test "$(id -u)" = 0
test "$(getenforce)" = Enforcing
test "$(cat /proc/sys/kernel/hostname)" = starter-smoke
test ! -e /etc/bootc-installer/live-iso-mode
test ! -e /usr/bin/bootc-installer-tui
''' + inactive_k3s() + '''bootc status --format json > /run/home-k8s-bootc-status.json
printf '\\nBOOTC_BEGIN\\n'
cat /run/home-k8s-bootc-status.json
printf '\\nBOOTC_END\\n'
printf '\\nSTATE_BEGIN\\n'
python3 - <<'PY'
import grp
import json
from pathlib import Path
import pwd
import socket
user = pwd.getpwnam("nodeadmin")
print(json.dumps({
    "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    "hostname": socket.gethostname(),
    "machine_id": Path("/etc/machine-id").read_text().strip(),
    "iqn": Path("/etc/iscsi/initiatorname.iscsi").read_text().strip(),
    "sentinel": Path("/var/lib/home-k8s-switch-smoke/sentinel").read_text(),
    "admin": {
        "name": user.pw_name, "uid": user.pw_uid, "gid": user.pw_gid,
        "home": user.pw_dir, "shell": user.pw_shell,
        "groups": sorted(group.gr_name for group in grp.getgrall() if user.pw_name in group.gr_mem or user.pw_gid == group.gr_gid),
    },
}))
PY
printf '\\nSTATE_END\\n'
'''


def switch_starter(args):
    # All insecure transport configuration lives only inside this disposable
    # guest, is scoped to one authority, and is removed as soon as staging ends.
    registry_config = "/etc/containers/registries.conf.d/99-home-k8s-switch-smoke.conf"
    fixture = ""
    if args.insecure_registry:
        authority = args.insecure_registry
        if not re.fullmatch(r"(?:[A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9A-Fa-f:]+\])(?::[0-9]+)?", authority):
            raise RuntimeError("Insecure registry must be one exact host[:port], without wildcards or a URL scheme")
        if args.image.split("/", 1)[0] != authority:
            raise RuntimeError("Insecure registry must exactly match the target image registry")
        fixture = f'''mkdir -p /etc/containers/registries.conf.d
test ! -e {registry_config}
trap 'rm -f {registry_config}' EXIT
cat > {registry_config} <<'HOME_K8S_REGISTRY'
[[registry]]
prefix = {json.dumps(authority)}
location = {json.dumps(authority)}
insecure = true
HOME_K8S_REGISTRY
'''
    installed_status = json.loads((args.artifacts / "starter-bootc.json").read_text())
    installed_identity = json.loads((args.artifacts / "starter-identity.json").read_text())
    installed_ref, installed_digest = bootc_image(installed_status, "booted")
    sentinel = secrets.token_hex(32)
    vm = VM(args, "starter", outbound=True)
    try:
        vm.root_login()
        output = vm.run(f'''test ! -e /var/lib/home-k8s-switch-smoke
install -d -m 0700 /var/lib/home-k8s-switch-smoke
printf '%s' {shlex.quote(sentinel)} > /var/lib/home-k8s-switch-smoke/sentinel
''' + switch_state_script())
        before = json.loads(section(output, "STATE"))
        before_status = json.loads(section(output, "BOOTC"))
        if bootc_image(before_status, "booted") != (installed_ref, installed_digest):
            raise RuntimeError("Switch acceptance must start from the actually TUI-installed starter")
        if before_status["status"].get("staged") is not None:
            raise RuntimeError("Starter already has a staged deployment")
        for key in ("machine_id", "iqn"):
            if before[key] != installed_identity[key]:
                raise RuntimeError(f"Starter installed identity changed before switch: {key}")
        if before["sentinel"] != sentinel or before["admin"]["uid"] == 0:
            raise RuntimeError("Invalid starter sentinel or local administrator identity")
        output = vm.run(fixture + f'''bootc switch {shlex.quote(args.image)}
bootc status --format json > /run/home-k8s-bootc-status.json
printf '\\nBOOTC_BEGIN\\n'
cat /run/home-k8s-bootc-status.json
printf '\\nBOOTC_END\\n'
''', timeout=1800)
        staged_status = json.loads(section(output, "BOOTC"))
        if bootc_image(staged_status, "booted") != (installed_ref, installed_digest):
            raise RuntimeError("Switch unexpectedly replaced the booted deployment before reboot")
        if bootc_image(staged_status, "staged") != (args.image, args.expected_digest):
            raise RuntimeError("Staged switch target does not match the fixture's exact reference and digest")
        vm.reboot()
    finally:
        vm.close()
    vm = VM(args, "starter", outbound=True)
    try:
        # This is a new password + sudo authentication, not a retained root shell.
        vm.root_login()
        output = vm.run(f"test ! -e {registry_config}\n" + switch_state_script())
        after = json.loads(section(output, "STATE"))
        after_status = json.loads(section(output, "BOOTC"))
        booted_ref, booted_digest = bootc_image(after_status, "booted")
        if (booted_ref, booted_digest) != (args.image, args.expected_digest):
            raise RuntimeError("Reboot did not boot the exact switched image reference and digest")
        if after_status["status"].get("staged") is not None:
            raise RuntimeError("Switch target is still staged after reboot")
        if not before["boot_id"] or before["boot_id"] == after["boot_id"]:
            raise RuntimeError("Switch acceptance did not observe a new kernel boot")
        # /etc uses a three-way merge: the TUI's mutable hostname and admin must
        # survive even when the destination image supplies Bihar's defaults.
        for key in ("hostname", "machine_id", "iqn", "sentinel", "admin"):
            if before[key] != after[key]:
                raise RuntimeError(f"Switch lost persistent starter state: {key}")
        proof = {
            "schema_version": 1,
            "marker": "STARTER_SWITCH_PASSED",
            "image": args.image,
            "expected_digest": args.expected_digest,
            "booted_ref": booted_ref,
            "booted_digest": booted_digest,
            "previous_ref": installed_ref,
            "hostname": after["hostname"],
            "checks": {
                "rebooted": True, "staged_digest_verified": True,
                "admin_identity_preserved": True, "var_sentinel_preserved": True,
                "machine_identity_preserved": True, "hostname_preserved": True,
                "selinux_enforcing": True, "k3s_inactive": True,
                "activation_marker_absent": True, "registry_override_removed": True,
            },
        }
        vm.poweroff()
        (args.artifacts / "starter-switch-proof.txt").write_text(json.dumps(proof, indent=2) + "\n")
        print(f"STARTER_SWITCH_PASSED: booted {booted_ref}@{booted_digest}, actual reboot, persistent admin/data/hostname, Enforcing SELinux, no K3s activation", flush=True)
    finally:
        vm.close()

def section(output, marker):
    match = re.search(rf"(?ms)^{marker}_BEGIN\n(.*?)\n{marker}_END$", output)
    if match is None:
        raise RuntimeError(f"Missing guest proof section {marker}:\n{output[-16000:]}")
    return match.group(1)


def install(args):
    node = args.node
    hostname = "starter-smoke" if node == "starter" else node
    iso = args.artifacts / f"{node}-installer.iso"
    if not iso.is_file():
        raise RuntimeError(f"Missing installer ISO: {iso}")
    vm = VM(args, node, live=True)
    try:
        vm.child.expect("Run: bootc-installer-tui", timeout=420)
        vm.child.expect(r"(?m)[^\r\n]*# ")
        vm.root_prompt()
        output = vm.run("printf '\\nMEDIA_BEGIN\\n'; cat /etc/bootc-installer/media-input.json; printf '\\nMEDIA_END\\n'")
        media = json.loads(section(output, "MEDIA"))
        if media["image"] != PAYLOAD:
            raise RuntimeError("Installer must use its embedded offline OCI payload")
        if node == "starter" and not re.fullmatch(r"ghcr\.io/[^/]+/home-k8s-starter:testing", media["targetImgref"]):
            raise RuntimeError("Starter media must track its canonical GHCR starter image")
        (args.artifacts / f"{node}-media.json").write_text(json.dumps(media, indent=2) + "\n")
        vm.child.sendline("stty echo; export TERM=xterm-256color; stty cols 140 rows 40; bootc-installer-tui")
        vm.child.expect("Press Enter to begin", timeout=90)
        vm.send("\r")
        vm.page(1)
        vm.send("\r")
        vm.page(2)
        for _ in range(5):
            vm.send("\x1b[B")
        vm.send("\r")
        vm.child.expect("Custom image URL", timeout=30)
        vm.send(PAYLOAD + "\r")
        vm.page(3)
        vm.child.expect("/dev/vda", timeout=30)
        vm.send("\r")
        vm.page(4)
        vm.send("\r")
        vm.send("\x01\x0b" + hostname + "\r")
        vm.page(5)
        vm.send("\r")
        vm.page(6)
        for value in ("Home Node Admin", USER, PASSWORD, PASSWORD):
            vm.send(value + "\r")
        vm.page(7)
        vm.send("\r")
        vm.page(8)
        vm.child.expect("Installation Summary", timeout=30)
        vm.send("\x1b[D")
        vm.send("\r")
        vm.child.expect("Installing...", timeout=30)
        print(f"{node}: real backend installing from OCI; guest outbound networking blocked", flush=True)
        outcome = vm.child.expect(["Installation Complete!", "Installation failed:", "Error: exit status"], timeout=1800)
        if outcome != 0:
            raise RuntimeError(vm.child.before[-25000:] + vm.child.after)
        print(f"{node}: real TUI Installation Complete observed", flush=True)
        vm.send("\x03")
        vm.child.expect(PROMPT, timeout=30)
        vm.poweroff()
    finally:
        vm.close()
    print(f"{node}: removing ISO and booting installed disk through UEFI", flush=True)
    vm = VM(args, node)
    try:
        vm.root_login()
        role_check = starter_readiness() if node == "starter" else f"systemctl is-enabled k3s@{'server' if node == 'bihar' else 'agent'}.service\n"
        output = vm.run(f'''test "$(id -u)" = 0
test "$(cat /proc/sys/kernel/hostname)" = {hostname}
systemctl --failed --no-pager
journalctl -b -u systemd-modules-load.service -u gssproxy.service --no-pager
journalctl -b -k --no-pager
journalctl -b --no-pager _TRANSPORT=audit
test "$(getenforce)" = Enforcing
test ! -e /etc/bootc-installer/live-iso-mode
test ! -e /usr/bin/bootc-installer-tui
{inactive_k3s()}
{role_check}
systemctl is-active tailscaled
test "$(stat -c %a /var/lib/tailscale)" = 700
test "$(stat -c %u /var/lib/tailscale)" = 0
python3 - <<'PY'
import json
import subprocess
status = json.loads(subprocess.check_output(["tailscale", "status", "--json"], text=True))
assert status["BackendState"] == "NeedsLogin", "An image must not ship an enrolled Tailscale identity"
assert status.get("CurrentTailnet") is None, "An image must not join a tailnet automatically"
print("TAILSCALE_AWAITING_ENROLLMENT: real daemon responsive under Enforcing SELinux; private runtime state")
PY
systemctl is-active NetworkManager firewalld iscsid.socket gssproxy
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables
k3s --version
cat /proc/cmdline
bootc status --format json > /run/home-k8s-bootc-status.json
printf '\\nBOOTC_BEGIN\\n'
cat /run/home-k8s-bootc-status.json
printf '\\nBOOTC_END\\n'
matchpathcon /var/mnt/storage /var/lib/lemonade-cache
printf '\\nIDENTITY_BEGIN\\n'
python3 - <<'PY'
import json
from pathlib import Path
print(json.dumps({{"machine_id": Path("/etc/machine-id").read_text().strip(), "iqn": Path("/etc/iscsi/initiatorname.iscsi").read_text().strip()}}))
PY
printf '\\nIDENTITY_END\\n'
findmnt /
''')
        status = json.loads(section(output, "BOOTC"))
        ref = status["status"]["booted"]["image"]["image"]["image"]
        if ref != media["targetImgref"]:
            raise RuntimeError(f"Installed bootc target {ref!r} differs from media target {media['targetImgref']!r}")
        (args.artifacts / f"{node}-bootc.json").write_text(json.dumps(status, indent=2) + "\n")
        identity = json.loads(section(output, "IDENTITY"))
        (args.artifacts / f"{node}-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
        assert_distinct_identities(args.artifacts)
        (args.artifacts / f"{node}-installed-proof.txt").write_text(output)
        vm.poweroff()
        print(f"TUI_INSTALLED_NODE_PASSED={node}: UEFI, user/sudo, Enforcing SELinux, bootc target, gated K3s", flush=True)
    finally:
        vm.close()


def cluster(args):
    assert_distinct_identities(args.artifacts, required=("bihar", "karnataka"))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token = secrets.token_urlsafe(32)
    machines = []
    try:
        for node, suffix in (("bihar", "05"), ("karnataka", "06")):
            vm = VM(args, node, lan_port=port)
            machines.append(vm)
            vm.root_login()
            unit = "server" if node == "bihar" else "agent"
            address = "192.168.0.5" if node == "bihar" else "192.168.0.6"
            vm.run(f'''lan=$(python3 - <<'PY'
import json, subprocess
print(next(item["ifname"] for item in json.loads(subprocess.check_output(["ip", "-j", "link"])) if item.get("address") == "52:54:00:24:00:{suffix}"))
PY
)
nmcli connection add type ethernet ifname "$lan" con-name smoke-lan ipv4.method manual ipv4.addresses {address}/24 ipv4.never-default yes ipv6.method disabled
nmcli connection up smoke-lan
mkdir -p /etc/rancher/k3s/config.yaml.d
printf 'node-ip: {address}\\nflannel-iface: %s\\ntoken-file: /etc/rancher/k3s/token\\n' "$lan" > /etc/rancher/k3s/config.yaml.d/90-smoke.yaml
umask 077
printf '%s' '{token}' > /etc/rancher/k3s/token
touch /etc/rancher/k3s/activate
systemctl start --no-block k3s@{unit}.service
''')
            print(f"{node}: activated actual K3s on isolated VM LAN {address}", flush=True)
        output = machines[0].run('''export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
for attempt in $(seq 1 150); do
  if k3s kubectl get node bihar karnataka >/dev/null 2>&1; then break; fi
  sleep 4
done
k3s kubectl wait --for=condition=Ready node/bihar node/karnataka --timeout=600s
k3s kubectl create namespace installed-smoke
python3 - <<'PY'
import json
from pathlib import Path
resources = [
    {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": "proof", "namespace": "installed-smoke"},
        "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "local-path",
                 "resources": {"requests": {"storage": "16Mi"}}},
    },
    {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": "writer", "namespace": "installed-smoke"},
        "spec": {
            "nodeSelector": {"kubernetes.io/hostname": "karnataka"},
            "containers": [{
                "name": "writer", "image": "docker.io/library/busybox:1.37.0",
                "command": ["sh", "-ec", "mkdir -p /proof/www; printf home-k8s-installed-nodes > /proof/www/index.html; exec httpd -f -p 8080 -h /proof/www"],
                "volumeMounts": [{"name": "proof", "mountPath": "/proof"}],
            }],
            "volumes": [{"name": "proof", "persistentVolumeClaim": {"claimName": "proof"}}],
        },
    },
    {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": "client", "namespace": "installed-smoke"},
        "spec": {
            "nodeSelector": {"kubernetes.io/hostname": "bihar"},
            "containers": [{"name": "client", "image": "docker.io/library/busybox:1.37.0",
                            "command": ["sh", "-ec", "sleep 3600"]}],
        },
    },
]
Path('/run/installed-smoke.json').write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": resources}))
PY
k3s kubectl apply -f /run/installed-smoke.json
k3s kubectl -n installed-smoke wait --for=condition=Ready pod/writer pod/client --timeout=600s
k3s kubectl -n installed-smoke exec client -- nslookup kubernetes.default.svc.cluster.local
writer_ip=$(k3s kubectl -n installed-smoke get pod writer -o jsonpath='{.status.podIP}')
test "$(k3s kubectl -n installed-smoke exec client -- wget -qO- "http://$writer_ip:8080")" = home-k8s-installed-nodes
pv=$(k3s kubectl -n installed-smoke get pvc proof -o jsonpath='{.spec.volumeName}')
k3s kubectl get pv "$pv" -o yaml
path=$(k3s kubectl get pv "$pv" -o jsonpath='{.spec.local.path}{.spec.hostPath.path}')
case "$path" in /var/mnt/storage/*) ;; *) echo "Unexpected PV path: $path"; exit 1 ;; esac
k3s kubectl -n installed-smoke delete pod writer --wait=true
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/run/installed-smoke.json')
resources = json.loads(p.read_text())
resources["items"][1]["spec"]["containers"][0]["command"] = [
    "sh", "-ec", 'test "$(cat /proof/www/index.html)" = home-k8s-installed-nodes; exec httpd -f -p 8080 -h /proof/www',
]
p.write_text(json.dumps(resources))
PY
k3s kubectl apply -f /run/installed-smoke.json
k3s kubectl -n installed-smoke wait --for=condition=Ready pod/writer --timeout=300s
writer_ip=$(k3s kubectl -n installed-smoke get pod writer -o jsonpath='{.status.podIP}')
test "$(k3s kubectl -n installed-smoke exec client -- wget -qO- "http://$writer_ip:8080")" = home-k8s-installed-nodes
k3s kubectl get nodes -o wide
k3s kubectl -n installed-smoke get pods,pvc -o wide
printf 'INSTALLED_CLUSTER_PASSED: two Ready nodes, cross-node HTTP, cluster DNS, persistent local-path storage across pod replacement\\n'
''', timeout=1800)
        (args.artifacts / "cluster-proof.txt").write_text(output)
        print(output, flush=True)
        for vm in reversed(machines):
            vm.poweroff()
    finally:
        for vm in reversed(machines):
            vm.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--accel", choices=("kvm", "tcg"), default="kvm")
    commands = parser.add_subparsers(dest="command", required=True)
    installer = commands.add_parser("install")
    installer.add_argument("node", choices=("starter", "bihar", "karnataka"))
    commands.add_parser("cluster")
    switcher = commands.add_parser("switch-starter", help="Switch the TUI-installed starter, reboot, and verify persistent state")
    switcher.add_argument("--image", required=True, help="Exact target registry image reference")
    switcher.add_argument("--expected-digest", required=True, help="Manifest digest of the exact switch fixture")
    switcher.add_argument("--insecure-registry", metavar="HOST[:PORT]", help="Exact disposable guest-only HTTP registry authority")
    args = parser.parse_args()
    if args.command == "switch-starter":
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.expected_digest):
            parser.error("--expected-digest must be a sha256 manifest digest")
        if "/" not in args.image or args.image.startswith("-") or any(character.isspace() for character in args.image):
            parser.error("--image must be a fully qualified registry image reference")
    args.artifacts = args.artifacts.resolve()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    if args.accel == "kvm" and not os.access("/dev/kvm", os.R_OK | os.W_OK):
        parser.error("KVM requested but /dev/kvm is unavailable; select a KVM runner or explicitly use --accel tcg")
    if args.command == "install":
        install(args)
    elif args.command == "switch-starter":
        switch_starter(args)
    else:
        cluster(args)


if __name__ == "__main__":
    main()
