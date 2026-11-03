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

"$BIN/lfc" check || { echo "check gagal; service tidak dipasang"; exit 1; }

mkdir -p "$UNIT_DIR" "$BASE/logs"
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
