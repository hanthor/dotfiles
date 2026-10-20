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
    def __init__(self, args, node, *, live=False, lan_port=None):
        self.node = node
        self.artifacts = args.artifacts
        self.child = None
        self.log = (args.artifacts / f"{node}-{'install' if live else 'boot'}-{time.time_ns()}.log").open("w", buffering=1)
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
                "-display", "none", "-serial", "stdio", "-monitor", "none", "-no-reboot",
                "-netdev", f"user,id=nat,restrict={'off' if lan_port else 'on'}",
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
        self.child = pexpect.spawn("qemu-system-x86_64", qemu, encoding="utf-8", codec_errors="replace",
                                   dimensions=(40, 140), timeout=300, maxread=65536, searchwindowsize=100000)
        self.child.logfile_read = self.log

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
        self.child.sendline("export PS1='NODE_USER_PROMPT> '")
        self.child.expect(r"(?m)^NODE_USER_PROMPT> ")
        self.child.sendline("sudo -k; sudo -v")
        outcome = self.child.expect([r"\[sudo\] password for .*:", "NODE_USER_PROMPT> "], timeout=30)
        if outcome == 0:
            self.child.sendline(PASSWORD)
            self.child.expect("NODE_USER_PROMPT> ", timeout=30)
        self.child.sendline("sudo bash --noprofile --norc")
        self.child.expect(r"(?m)[^\r\n]*# ", timeout=30)
        self.root_prompt()

    def root_prompt(self):
        self.child.sendline(f"export PS1='{PROMPT}'; stty -echo")
        self.child.expect(rf"(?m)^{PROMPT}")

    def run(self, script, *, timeout=240):
        encoded = base64.b64encode(script.encode()).decode()
        marker = "COMMAND_RESULT_" + secrets.token_hex(8)
        self.child.sendline(f"printf %s '{encoded}' | base64 -d > /run/home-k8s-proof.sh; bash -euo pipefail /run/home-k8s-proof.sh; result=$?; printf '\\n{marker}:%s\\n' \"$result\"")
        self.child.expect(rf"(?m)^{marker}:([0-9]+)\r?$", timeout=timeout)
        output = ANSI.sub("", self.child.before).replace("\r", "")
        if self.child.match.group(1) != "0":
            raise RuntimeError(f"{self.node}: guest command failed:\n{output[-16000:]}")
        self.child.expect(PROMPT)
        return output

    def poweroff(self):
        self.child.sendline("sync; poweroff")
        self.child.expect(pexpect.EOF, timeout=120)


def section(output, marker):
    match = re.search(rf"(?ms)^{marker}_BEGIN\n(.*?)\n{marker}_END$", output)
    if match is None:
        raise RuntimeError(f"Missing guest proof section {marker}:\n{output[-16000:]}")
    return match.group(1)


def install(args):
    node = args.node
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
        vm.send("\x01\x0b" + node + "\r")
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
        unit = "server" if node == "bihar" else "agent"
        output = vm.run(f'''test "$(id -u)" = 0
test "$(hostname)" = {node}
test "$(getenforce)" = Enforcing
test ! -e /etc/bootc-installer/live-iso-mode
test ! -e /usr/bin/bootc-installer-tui
test ! -e /etc/rancher/k3s/activate
systemctl is-enabled k3s@{unit}.service
if systemctl is-active --quiet k3s@{unit}.service; then exit 1; fi
systemctl is-active NetworkManager firewalld iscsid.socket
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables
k3s --version
cat /proc/cmdline
printf '\\nBOOTC_BEGIN\\n'
bootc status --format json
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
        (args.artifacts / f"{node}-installed-proof.txt").write_text(output)
        vm.poweroff()
        print(f"TUI_INSTALLED_NODE_PASSED={node}: UEFI, user/sudo, Enforcing SELinux, bootc target, gated K3s", flush=True)
    finally:
        vm.close()


def cluster(args):
    identities = [json.loads((args.artifacts / f"{node}-identity.json").read_text()) for node in ("bihar", "karnataka")]
    for key in ("machine_id", "iqn"):
        if identities[0][key] == identities[1][key]:
            raise RuntimeError(f"Cloned node identity: {key}")
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
path=$(k3s kubectl get pv "$pv" -o jsonpath='{.spec.hostPath.path}')
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
    installer.add_argument("node", choices=("bihar", "karnataka"))
    commands.add_parser("cluster")
    args = parser.parse_args()
    args.artifacts = args.artifacts.resolve()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    if args.accel == "kvm" and not os.access("/dev/kvm", os.R_OK | os.W_OK):
        parser.error("KVM requested but /dev/kvm is unavailable; select a KVM runner or explicitly use --accel tcg")
    if args.command == "install":
        install(args)
    else:
        cluster(args)


if __name__ == "__main__":
    main()
