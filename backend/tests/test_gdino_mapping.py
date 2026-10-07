import pytest

from labelforge.providers.base import ClassDef
from labelforge.providers.gdino_mapping import (
    build_prompt,
    map_label_to_class,
    normalize,
    split_batches,
)

PALLET = ClassDef(1, "pallet", "Wooden Pallet")
PERSON = ClassDef(2, "person", "person wearing safety vest")
FORKLIFT = ClassDef(3, "forklift")
BOX = ClassDef(4, "box", "cardboard boxes")
CLASSES = [PALLET, PERSON, FORKLIFT, BOX]


def test_normalize():
    assert normalize("  Wooden-Pallet. ") == "wooden pallet"


def test_build_prompt_lowercase_dot_separated():
    assert build_prompt(CLASSES) == (
        "wooden pallet. person wearing safety vest. forklift. cardboard boxes."
    )


def test_build_prompt_strips_dots_inside_phrase():
    assert build_prompt([ClassDef(1, "x", "a. b")]) == "a b."


@pytest.mark.parametrize(
    "label,expected",
    [
        ("wooden pallet", 1),          # exact frasa
        ("pallet", 1),                 # nama class
        ("wooden", 1),                 # potongan frasa
        ("pallets", 1),                # plural
        ("Pallet.", 1),                # huruf besar & tanda baca
        ("safety vest", 2),            # potongan tengah frasa
        ("person wearing", 2),
        ("fork", 3),                   # sub-kata WordPiece
        ("##lift", 3),
        ("cardboard box", 4),          # plural di prompt, singular di label
        ("boxes", 4),
    ],
)  # fmt: skip
def test_map_label(label, expected):
    assert map_label_to_class(label, CLASSES) == expected


@pytest.mark.parametrize("label", ["", "  ", "truck", "##", "."])
def test_map_label_no_match(label):
    assert map_label_to_class(label, CLASSES) is None


def test_merged_label_prefers_better_coverage():
    # Gabungan dua frasa: "wooden pallet forklift" lebih banyak menjelaskan pallet (2 token).
    assert map_label_to_class("wooden pallet forklift", CLASSES) == 1
    # Kata yang sama di dua class: frasa yang tercakup penuh menang.
    classes = [ClassDef(1, "pallet", "empty pallet"), ClassDef(2, "pallet stack", "pallet")]
    assert map_label_to_class("pallet", classes) == 2


def test_split_batches_by_token_count():
    count = lambda text: len(text.split())  # noqa: E731
    batches = split_batches(CLASSES, count, max_tokens=6)
    assert [[c.id for c in b] for b in batches] == [[1, 2], [3, 4]]
    assert all(count(build_prompt(b)) <= 6 for b in batches)


def test_split_batches_single_batch_when_fits():
    assert len(split_batches(CLASSES, lambda t: len(t.split()), max_tokens=256)) == 1


def test_split_batches_class_too_long():
    with pytest.raises(ValueError):
        split_batches([PERSON], lambda t: len(t.split()), max_tokens=2)


SYN = ClassDef(1, "pallet", "wooden pallet, plastic pallet; skid")
CLS_SYN = [SYN, ClassDef(2, "box", "cardboard box")]


def test_prompts_split_synonyms():
    assert SYN.prompts == ["wooden pallet", "plastic pallet", "skid"]
    assert ClassDef(1, "pallet", " , ").prompts == ["pallet"]
    assert ClassDef(1, "pallet").prompts == ["pallet"]


def test_build_prompt_with_synonyms():
    assert build_prompt(CLS_SYN) == "wooden pallet. plastic pallet. skid. cardboard box."


@pytest.mark.parametrize("label", ["plastic pallet", "plastic", "skid", "wooden", "pallet"])
def test_map_label_synonyms(label):
    assert map_label_to_class(label, CLS_SYN) == 1


def test_split_batches_keeps_synonyms_together():
    count = lambda text: len(text.split())  # noqa: E731
    batches = split_batches(CLS_SYN, count, max_tokens=6)
    assert [[c.id for c in b] for b in batches] == [[1], [2]]
