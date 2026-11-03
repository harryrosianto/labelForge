#!/bin/sh
# Pasang tailscaled (userspace) sebagai service user. Binari tailscale & tailscaled dari paket
# resmi arm64 (checksum dicek di laptop) harus sudah ada di ~/tailscale/bin.
#   sh deploy/install-tailscale.sh
# Lalu daftarkan perangkat: simpan auth key ke ~/tailscale/authkey (chmod 600), jalankan
#   lfc vpn up
set -eu

TS="$HOME/tailscale"
UNIT_DIR="$HOME/.config/systemd/user"
for f in "$TS/bin/tailscale" "$TS/bin/tailscaled"; do
    [ -x "$f" ] || { echo "Belum ada: $f"; exit 1; }
done
mkdir -p "$TS/state" "$UNIT_DIR"
chmod 700 "$TS" "$TS/state"
cp "$HOME/lfcapture/src/deploy/tailscaled.service" "$UNIT_DIR/tailscaled.service"
systemctl --user daemon-reload
systemctl --user enable tailscaled.service
systemctl --user restart tailscaled.service
sleep 3
systemctl --user --no-pager status tailscaled.service | head -n 5
"$TS/bin/tailscale" --socket="$TS/tailscaled.sock" version | head -n 1
