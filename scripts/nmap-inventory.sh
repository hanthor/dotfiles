#!/usr/bin/env bash
# LAN inventory via nmap + Tailscale.
# Prints: IP | MAC | Hostname | Tailscale status
#
# Defaults to 192.168.0.0/24. Override:  ./scripts/nmap-inventory.sh 10.0.0.0/24
set -euo pipefail

SUBNET="${1:-192.168.0.0/24}"

if ! command -v nmap >/dev/null; then
  echo "nmap not installed (brew install nmap)" >&2
  exit 1
fi

# nmap needs root to read MACs reliably; fall back to unprivileged otherwise.
SUDO=""
if [ "$EUID" -ne 0 ]; then
  if sudo -n true 2>/dev/null; then SUDO="sudo"; else
    echo "(running unprivileged — MAC column may be empty for non-arp hosts)" >&2
  fi
fi

scan_json=$($SUDO nmap -sn -oX - "$SUBNET" 2>/dev/null)

# Build Tailscale lookup table (IP -> hostname:status) from `tailscale status --json`
declare -A TS
if command -v tailscale >/dev/null && tailscale status >/dev/null 2>&1; then
  while IFS=$'\t' read -r ip name online; do
    [ -n "$ip" ] && TS["$ip"]="$name:$online"
  done < <(tailscale status --json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
peers = list(d.get('Peer', {}).values()) + [d.get('Self', {})]
for p in peers:
    if not p: continue
    name = (p.get('DNSName','').rstrip('.').split('.')[0] or p.get('HostName',''))
    online = 'online' if p.get('Online') else 'offline'
    for ip in p.get('TailscaleIPs', []) or []:
        print(f'{ip}\t{name}\t{online}')
")
fi

python3 - "$scan_json" <<'PY'
import sys, xml.etree.ElementTree as ET, os, subprocess
xml = sys.argv[1]
root = ET.fromstring(xml)
rows = []
for host in root.findall('host'):
    state = host.find('status').get('state')
    if state != 'up':
        continue
    ip = mac = vendor = hostname = ''
    for addr in host.findall('address'):
        t = addr.get('addrtype')
        if t == 'ipv4': ip = addr.get('addr','')
        elif t == 'mac':
            mac = addr.get('addr','')
            vendor = addr.get('vendor','')
    hn = host.find('hostnames/hostname')
    if hn is not None: hostname = hn.get('name','')
    rows.append((ip, mac, hostname or '-', vendor or '-'))

rows.sort(key=lambda r: tuple(int(x) for x in r[0].split('.')) if r[0] else (0,))

# Pull Tailscale table from env (passed below) — simpler: re-read tailscale here
ts = {}
try:
    out = subprocess.run(['tailscale','status','--json'], capture_output=True, text=True, check=True).stdout
    import json
    d = json.loads(out)
    peers = list(d.get('Peer', {}).values()) + ([d.get('Self')] if d.get('Self') else [])
    for p in peers:
        name = (p.get('DNSName','').rstrip('.').split('.')[0] or p.get('HostName',''))
        online = 'online' if p.get('Online') else 'offline'
        for ip in p.get('TailscaleIPs', []) or []:
            ts[ip] = (name, online)
except Exception:
    pass

print(f"{'IP':<16} {'MAC':<19} {'Hostname':<22} {'Vendor':<28} {'Tailscale'}")
print('-'*110)
for ip, mac, hostname, vendor in rows:
    tsinfo = ts.get(ip, ('',''))
    tsstr = f"{tsinfo[0]} ({tsinfo[1]})" if tsinfo[0] else ''
    print(f"{ip:<16} {mac:<19} {hostname:<22} {vendor[:28]:<28} {tsstr}")
PY
