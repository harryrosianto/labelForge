import pytest

from labelforge.exporters.split import split_ids


def test_split_counts_and_coverage():
    ids = list(range(1, 101))
    out = split_ids(ids, {"train": 0.7, "val": 0.2, "test": 0.1}, seed=1)
    assert [len(out[s]) for s in ("train", "val", "test")] == [70, 20, 10]
    all_ids = out["train"] + out["val"] + out["test"]
    assert sorted(all_ids) == ids  # tiap gambar tepat satu split


def test_split_deterministic_and_order_independent():
    a = split_ids([5, 3, 9, 1, 7], {"train": 0.6, "val": 0.4}, seed=7)
    b = split_ids([1, 3, 5, 7, 9], {"train": 0.6, "val": 0.4}, seed=7)
    assert a == b
    c = split_ids(list(range(50)), {"train": 0.8, "val": 0.2}, seed=8)
    assert c != split_ids(list(range(50)), {"train": 0.8, "val": 0.2}, seed=9)


def test_small_dataset_keeps_val():
    out = split_ids([1, 2, 3], {"train": 0.9, "val": 0.1, "test": 0.0})
    assert len(out["val"]) == 1 and len(out["train"]) == 2 and out["test"] == []


def test_unnormalized_ratios_and_edge_cases():
    out = split_ids(list(range(10)), {"train": 8, "val": 2})
    assert [len(out["train"]), len(out["val"])] == [8, 2]
    assert split_ids([], {"train": 1}) == {"train": [], "val": [], "test": []}
    assert split_ids([4], {"train": 0.5, "val": 0.5})["train"] + split_ids([4], {"train": 0.5, "val": 0.5})["val"] == [4]
    with pytest.raises(ValueError):
        split_ids([1], {"train": 0, "val": 0})
