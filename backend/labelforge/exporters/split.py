import random
from collections.abc import Sequence

SPLITS = ("train", "val", "test")


def split_ids(
    ids: Sequence[int], ratios: dict[str, float], seed: int = 42
) -> dict[str, list[int]]:
    """Bagi id ke train/val/test secara deterministik (seed sama + id sama → hasil sama).

    Split dengan rasio > 0 dijamin mendapat minimal satu gambar jika jumlah gambar cukup,
    supaya dataset kecil tetap punya data validasi.
    """
    total_ratio = sum(max(0.0, ratios.get(s, 0.0)) for s in SPLITS)
    if total_ratio <= 0:
        raise ValueError("Total rasio split harus > 0")
    shuffled = sorted(ids)
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)

    wanted = [s for s in SPLITS if ratios.get(s, 0) > 0]
    counts = {s: int(round(n * max(0.0, ratios.get(s, 0.0)) / total_ratio)) for s in SPLITS}
    if n >= len(wanted):
        for s in wanted:
            if counts[s] == 0:
                counts[s] = 1
    # Sesuaikan agar total tepat n; selisih diambil/ditambahkan ke split terbesar.
    while sum(counts.values()) != n:
        largest = max(wanted, key=lambda s: counts[s])
        counts[largest] += 1 if sum(counts.values()) < n else -1

    out, start = {}, 0
    for s in SPLITS:
        out[s] = sorted(shuffled[start : start + counts[s]])
        start += counts[s]
    return out
