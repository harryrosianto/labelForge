"""ARP probe (RFC 5227): apakah sebuah IP sudah dipakai di jaringan, tanpa mengaku memilikinya.

Probe dikirim dengan alamat pengirim 0.0.0.0, jadi tidak mengganggu tabel ARP perangkat lain.
Butuh root (AF_PACKET); dijalankan lewat `sudo -n <python> -I arpprobe.py <iface> <ip> [detik]`
oleh `lfc lan terapkan`. Sengaja tanpa import dari paket lfcapture agar bisa jalan dengan -I.

Exit 0 + "BEBAS" bila tidak ada jawaban, exit 1 + "DIPAKAI <mac>" bila ada perangkat menjawab.
"""

import socket
import struct
import sys
import time


def probe(iface: str, target: str, wait: float = 3.0) -> str | None:
    """MAC perangkat yang memakai `target`, atau None bila tidak ada yang menjawab."""
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
    try:
        s.bind((iface, 0))
        mac = s.getsockname()[4]
        tip = socket.inet_aton(target)
        arp = struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1, mac, b"\0" * 4, b"\0" * 6, tip)
        frame = b"\xff" * 6 + mac + b"\x08\x06" + arp
        s.settimeout(0.2)
        end, next_send = time.monotonic() + wait, 0.0
        while time.monotonic() < end:
            if time.monotonic() >= next_send:  # satu probe per detik
                s.send(frame)
                next_send = time.monotonic() + 1.0
            try:
                pkt = s.recv(128)
            except TimeoutError:
                continue
            if len(pkt) < 42 or pkt[12:14] != b"\x08\x06":
                continue
            op = struct.unpack("!H", pkt[20:22])[0]
            sha, spa = pkt[22:28], pkt[28:32]
            if spa == tip and sha != mac and op in (1, 2):
                return ":".join(f"{b:02x}" for b in sha)
        return None
    finally:
        s.close()


if __name__ == "__main__":
    used_by = probe(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 3.0)
    print(f"DIPAKAI {used_by}" if used_by else "BEBAS")
    sys.exit(1 if used_by else 0)
