#!/bin/sh
# Pasang/perbarui service perekam dan perintah `lfc` milik user di perangkat. Jalankan sebagai
# user perekam (mis. sysedge), dari folder ~/lfcapture/src:   sh deploy/install-service.sh
set -eu

BASE="$HOME/lfcapture"
UNIT_DIR="$HOME/.config/systemd/user"
BIN="$HOME/.local/bin"

for f in "$BASE/venv/bin/python" "$BASE/capture.env"; do
    [ -e "$f" ] || { echo "Belum ada: $f (lihat README, bagian Menjalankan)"; exit 1; }
done
if [ "$(stat -c %a "$BASE/capture.env")" != "600" ]; then
    echo "capture.env harus chmod 600"; exit 1
fi

mkdir -p "$BIN"
cp "$BASE/src/deploy/lfc" "$BIN/lfc"
chmod 755 "$BIN/lfc"

mkdir -p "$UNIT_DIR" "$BASE/logs"
# Flashdisk (CAPTURE_USB_UUID) dipasang dulu supaya `lfc check` memeriksa disk yang benar.
if grep -q '^CAPTURE_USB_UUID=..*' "$BASE/capture.env"; then
    cp "$BASE/src/deploy/lfcapture-usb.service" "$UNIT_DIR/lfcapture-usb.service"
    systemctl --user daemon-reload
    systemctl --user enable lfcapture-usb.service
    "$BIN/lfc" usb pasang --tanpa-start || echo "flashdisk belum terpasang; perekam menunggu (lfc usb pasang)"
else
    systemctl --user disable lfcapture-usb.service 2>/dev/null || true
    rm -f "$UNIT_DIR/lfcapture-usb.service"
fi

# IP port LAN pengganti alamat recovery firmware, hanya bila lan.env ada (lihat README).
if [ -f "$BASE/lan.env" ]; then
    cp "$BASE/src/deploy/lfcapture-lan.service" "$BASE/src/deploy/lfcapture-lan.timer" "$UNIT_DIR/"
    systemctl --user daemon-reload
    systemctl --user enable --now lfcapture-lan.timer
    "$BIN/lfc" lan terapkan || echo "PERHATIAN: IP LAN belum diterapkan (lfc lan)"
else
    systemctl --user disable --now lfcapture-lan.timer 2>/dev/null || true
    rm -f "$UNIT_DIR/lfcapture-lan.service" "$UNIT_DIR/lfcapture-lan.timer"
fi

"$BIN/lfc" check || { echo "check gagal; service tidak dipasang"; exit 1; }

cp "$BASE/src/deploy/lfcapture.service" "$UNIT_DIR/lfcapture.service"
systemctl --user daemon-reload
systemctl --user enable lfcapture.service
systemctl --user restart lfcapture.service
sleep 3
"$BIN/lfc" status || true

if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != "yes" ]; then
    echo
    echo "PERHATIAN: linger belum aktif, service berhenti saat logout dan tidak jalan saat boot."
    echo "Aktifkan sekali dengan:  sudo loginctl enable-linger $(id -un)"
fi
# Sesi SSH biasa (login) sudah memuat ~/.local/bin lewat ~/.profile. Perintah SSH satu baris
# (`ssh perangkat ...`) tidak, jadi pakai path lengkap: ssh perangkat .local/bin/lfc status
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo; echo "Catatan: untuk perintah SSH satu baris pakai path lengkap: $BIN/lfc" ;;
esac
