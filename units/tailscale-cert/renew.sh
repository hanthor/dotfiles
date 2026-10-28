#!/usr/bin/env bash
# Run as root by the unit and timer. Never write directly to an existing pair.
set -u
if [ "$#" -ne 2 ]; then
  echo "usage: renew.sh CERT_DIRECTORY HOSTNAME" >&2
  exit 1
fi
dir=$1
host=$2
cert=$dir/cert.pem
key=$dir/key.pem
if [ ! -d "$dir" ] || [ -L "$dir" ]; then
  echo "certificate directory is not a real directory" >&2
  exit 1
fi
umask 077
if [ -L "$dir/.renew.lock" ] || { [ -e "$dir/.renew.lock" ] && [ ! -f "$dir/.renew.lock" ]; }; then
  echo "refusing non-regular renewal lock" >&2
  exit 1
fi
exec 9>>"$dir/.renew.lock" || exit 1
flock -x 9 || exit 1
for path in "$cert" "$key"; do
  if [ -L "$path" ] || { [ -e "$path" ] && [ ! -f "$path" ]; }; then
    echo "refusing to replace non-regular certificate path: $path" >&2
    exit 1
  fi
done
tmp=$(mktemp -d "$dir/.renew.XXXXXXXX") || exit 1
trap 'rm -rf -- "$tmp"' EXIT
if ! tailscale cert --cert-file "$tmp/cert.pem" --key-file "$tmp/key.pem" --min-validity 720h "$host"; then
  exit 1
fi
if [ ! -s "$tmp/cert.pem" ] || [ ! -s "$tmp/key.pem" ] || [ -L "$tmp/cert.pem" ] || [ -L "$tmp/key.pem" ]; then
  echo "Tailscale did not produce a certificate and private key" >&2
  exit 1
fi
host_check=$(LC_ALL=C openssl x509 -checkhost "$host" -noout -in "$tmp/cert.pem" 2>/dev/null) || exit 1
if [ "$host_check" != "Hostname $host does match certificate" ] ||
   ! openssl x509 -checkend 0 -noout -in "$tmp/cert.pem" >/dev/null 2>&1; then
  echo "Tailscale returned a certificate with the wrong hostname or expiry" >&2
  exit 1
fi
cert_pub=$(openssl x509 -pubkey -noout -in "$tmp/cert.pem" 2>/dev/null) || exit 1
key_pub=$(openssl pkey -pubout -passin pass: -in "$tmp/key.pem" 2>/dev/null) || exit 1
if [ -z "$cert_pub" ] || [ "$cert_pub" != "$key_pub" ]; then
  echo "Tailscale returned a certificate and private key that do not match" >&2
  exit 1
fi
chmod 0644 "$tmp/cert.pem" && chmod 0640 "$tmp/key.pem" || exit 1
had_key=0
if [ -e "$key" ]; then
  cp -p -- "$key" "$tmp/old-key.pem" || exit 1
  had_key=1
fi
mv -fT -- "$tmp/key.pem" "$key" || exit 1
if ! mv -fT -- "$tmp/cert.pem" "$cert"; then
  if [ "$had_key" = 1 ]; then
    if ! mv -fT -- "$tmp/old-key.pem" "$key"; then
      trap - EXIT
      echo "failed to restore previous private key; backup retained at $tmp/old-key.pem" >&2
    fi
  else
    rm -f -- "$key" || echo "failed to remove new private key" >&2
  fi
  exit 1
fi
