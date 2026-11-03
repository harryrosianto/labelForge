#!/bin/sh
# Pasang/perbarui service perekam milik user di perangkat. Jalankan sebagai user perekam
# (mis. sysedge), dari folder ~/lfcapture/src:   sh deploy/install-service.sh
set -eu

BASE="$HOME/lfcapture"
UNIT_DIR="$HOME/.config/systemd/user"

for f in "$BASE/venv/bin/python" "$BASE/capture.env"; do
    [ -e "$f" ] || { echo "Belum ada: $f (lihat README, bagian Menjalankan)"; exit 1; }
done
if [ "$(stat -c %a "$BASE/capture.env")" != "600" ]; then
    echo "capture.env harus chmod 600"; exit 1
fi

PYTHONPATH="$BASE/src" "$BASE/venv/bin/python" -m lfcapture check --env-file "$BASE/capture.env" || {
    echo "check gagal; service tidak dipasang"; exit 1; }

mkdir -p "$UNIT_DIR"
cp "$BASE/src/deploy/lfcapture.service" "$UNIT_DIR/lfcapture.service"
systemctl --user daemon-reload
systemctl --user enable lfcapture.service
systemctl --user restart lfcapture.service
sleep 3
systemctl --user --no-pager status lfcapture.service | head -n 8

if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != "yes" ]; then
    echo
    echo "PERHATIAN: linger belum aktif, service berhenti saat logout dan tidak jalan saat boot."
    echo "Aktifkan sekali dengan:  sudo loginctl enable-linger $(id -un)"
fi
