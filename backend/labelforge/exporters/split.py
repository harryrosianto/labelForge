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


def split_groups(
    groups: Sequence[Sequence[int]],
    strata: Sequence[str],
    ratios: dict[str, float],
    seed: int = 42,
) -> dict[str, list[int]]:
    """Bagi grup gambar ke train/val/test tanpa memecah grup (mencegah kebocoran antar split).

    `strata[i]` = sumber grup ke-i (mis. kamera). Pembagian dilakukan per sumber agar setiap
    sumber terwakili di setiap split bila grupnya cukup. Deterministik untuk seed yang sama.
    """
    total_ratio = sum(max(0.0, ratios.get(s, 0.0)) for s in SPLITS)
    if total_ratio <= 0:
        raise ValueError("Total rasio split harus > 0")
    wanted = [s for s in SPLITS if ratios.get(s, 0) > 0]
    share = {s: max(0.0, ratios.get(s, 0.0)) / total_ratio for s in SPLITS}
    rng = random.Random(seed)

    by_stratum: dict[str, list[list[int]]] = {}
    for stratum, group in sorted(zip(strata, groups), key=lambda x: (x[0], min(x[1]))):
        by_stratum.setdefault(stratum, []).append(sorted(group))

    out: dict[str, list[int]] = {s: [] for s in SPLITS}
    assigned: list[tuple[str, list[int]]] = []
    for stratum in sorted(by_stratum):
        blocks = by_stratum[stratum]
        rng.shuffle(blocks)
        target = sum(len(b) for b in blocks)
        filled = dict.fromkeys(SPLITS, 0)
        for block in blocks:
            # Split dengan kekurangan relatif terbesar terhadap targetnya mendapat blok ini.
            split = max(wanted, key=lambda s: (share[s] * target - filled[s]) / share[s])
            filled[split] += len(block)
            out[split].extend(block)
            assigned.append((split, block))

    # Dataset kecil: pastikan setiap split yang diminta punya minimal satu grup.
    for s in wanted:
        if out[s]:
            continue
        donors = [(sp, b) for sp, b in assigned if sp != s and len(out[sp]) > len(b)]
        if not donors:
            continue
        sp, block = min(donors, key=lambda x: len(x[1]))
        assigned.remove((sp, block))
        assigned.append((s, block))
        moved = set(block)
        out[sp] = [i for i in out[sp] if i not in moved]
        out[s].extend(block)
    return {s: sorted(ids) for s, ids in out.items()}
