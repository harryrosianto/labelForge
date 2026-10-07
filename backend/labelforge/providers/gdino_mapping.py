"""Logika teks Grounding DINO yang tidak butuh torch: prompt, batching, dan mapping label → class.

Grounding DINO mengembalikan label berupa potongan teks prompt (token yang skornya di atas
text_threshold), mis. "pallet", "wooden", "fork", atau gabungan dua frasa yang bersebelahan.
Karena itu label dicocokkan secara fuzzy, bukan exact match. Satu class boleh punya beberapa
frasa sinonim (lihat `ClassDef.prompts`); semuanya dipetakan ke class yang sama.
"""

import re
from collections.abc import Callable, Sequence

from labelforge.providers.base import ClassDef

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def _stem(token: str) -> str:
    # Plural sederhana: pallets → pallet, boxes → box. Cukup untuk nama objek berbahasa Inggris.
    if len(token) > 4 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in normalize(text).split()]


def phrases_for(cls: ClassDef) -> list[str]:
    """Frasa class di prompt: huruf kecil, tanpa titik (titik adalah pemisah antar frasa)."""
    phrases = [normalize(p) for p in cls.prompts]
    return [p for p in phrases if p] or [normalize(cls.name)]


def build_prompt(classes: Sequence[ClassDef]) -> str:
    return ". ".join(p for c in classes for p in phrases_for(c)) + "."


def split_batches(
    classes: Sequence[ClassDef], count_tokens: Callable[[str], int], max_tokens: int = 256
) -> list[list[ClassDef]]:
    """Bagi class ke beberapa batch agar tiap prompt gabungan muat dalam batas token model.
    Semua sinonim satu class selalu berada di batch yang sama."""
    batches: list[list[ClassDef]] = []
    current: list[ClassDef] = []
    for cls in classes:
        candidate = current + [cls]
        if current and count_tokens(build_prompt(candidate)) > max_tokens:
            batches.append(current)
            candidate = [cls]
        if count_tokens(build_prompt(candidate)) > max_tokens:
            raise ValueError(f"Prompt class '{cls.name}' sendiri melebihi {max_tokens} token")
        current = candidate
    if current:
        batches.append(current)
    return batches


def _token_score(label_tok: str, phrase_toks: list[str]) -> float:
    if label_tok in phrase_toks:
        return 1.0
    # Sub-kata dari tokenizer WordPiece, mis. "fork" / "##lift" dari "forklift".
    if len(label_tok) >= 3 and any(
        p.startswith(label_tok) or p.endswith(label_tok) or label_tok.startswith(p)
        for p in phrase_toks
        if len(p) >= 3
    ):
        return 0.5
    return 0.0


def map_label_to_class(label: str, classes: Sequence[ClassDef]) -> int | None:
    """Cari class yang paling cocok untuk label hasil model; None jika tidak ada yang cocok."""
    norm_label = normalize(label)
    if not norm_label:
        return None

    # 1. Exact match: frasa prompt dulu (itu yang dilihat model), baru nama class.
    for cls in classes:
        if norm_label in phrases_for(cls):
            return cls.id
    for cls in classes:
        if norm_label == normalize(cls.name):
            return cls.id

    label_toks = _tokens(norm_label)
    best_id, best_score = None, 0.0
    for cls in classes:
        for phrase in phrases_for(cls):
            own = _tokens(phrase)
            matched = sum(_token_score(t, own + _tokens(cls.name)) for t in label_toks)
            if matched == 0:
                continue
            # Proporsi label yang dijelaskan frasa ini, ditambah proporsi frasa yang tercakup
            # (memecah seri ketika satu kata muncul di beberapa class).
            coverage = sum(_token_score(t, label_toks) for t in own) / max(len(own), 1)
            score = matched / len(label_toks) + 0.5 * coverage
            if score > best_score:
                best_id, best_score = cls.id, score
    return best_id
