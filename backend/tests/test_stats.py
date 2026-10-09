import pytest

from labelforge.models import Annotation
from labelforge.stats.dataset_stats import StatImage, compute_stats
from tests.test_exporters import ds  # noqa: F401

NAMES = ["pallet", "person", "forklift"]


def stats_for(images):
    return compute_stats(NAMES, images)


def test_class_balance_and_sizes():
    images = [
        # 1000x1000: box 0.02 sisi → 20px (small), 0.05 → 50px (medium), 0.5 → 500px (large)
        StatImage(1000, 1000, [(0, 0.0, 0.0, 0.02, 0.02), (0, 0.1, 0.1, 0.15, 0.15), (1, 0.0, 0.0, 0.5, 0.5)]),
        StatImage(1000, 1000, [(0, 0.5, 0.5, 1.0, 1.0)]),
        StatImage(640, 480, []),
    ]
    s = stats_for(images)
    assert (s["images"], s["boxes"], s["empty_images"]) == (3, 4, 1)
    by = {c["name"]: c for c in s["classes"]}
    assert (by["pallet"]["boxes"], by["pallet"]["images"]) == (3, 2)
    assert (by["pallet"]["small"], by["pallet"]["medium"], by["pallet"]["large"]) == (1, 1, 1)
    assert (by["person"]["boxes"], by["forklift"]["boxes"]) == (1, 0)
    assert (s["box_size"]["small"], s["box_size"]["medium"], s["box_size"]["large"]) == (1, 1, 2)
    assert sum(b["count"] for b in s["box_size"]["relative_side_hist"]) == 4
    assert s["boxes_per_image"][0]["count"] == 1 and s["boxes_per_image"][3]["count"] == 1
    assert s["image_sizes"][0] == {"width": 1000, "height": 1000, "count": 2}


def test_heatmap_and_aspect():
    s = stats_for([StatImage(200, 100, [(0, 0.0, 0.0, 0.1, 0.1),      # pusat (0.05,0.05) → sel [1][1]
                                        (0, 0.9, 0.9, 1.0, 1.0),      # pojok kanan bawah → sel [19][19]
                                        (1, 0.0, 0.0, 1.0, 0.5)])])    # 200x50 px → rasio 4:1  # fmt: skip
    heat = s["heatmap"]["counts"]
    assert heat[1][1] == 1 and heat[19][19] == 1 and heat[5][10] == 1
    assert sum(map(sum, heat)) == 3
    # box 20x10 px (2:1) dua kali, box 200x50 px (4:1) sekali
    assert {a["label"]: a["count"] for a in s["aspect_ratio"]}["2:1 - 4:1"] == 2
    assert {a["label"]: a["count"] for a in s["aspect_ratio"]}["> 4:1"] == 1


def test_boxes_per_image_overflow_bin():
    s = stats_for([StatImage(100, 100, [(0, 0, 0, 0.1, 0.1)] * 15)])
    assert s["boxes_per_image"][-1] == {"label": "10+", "count": 1}


@pytest.mark.parametrize("boxes,kinds", [
    ({0: 500, 1: 20, 2: 0}, {"class_without_boxes", "few_boxes", "imbalance"}),
    ({0: 60, 1: 60, 2: 60}, set()),
])  # fmt: skip
def test_warnings(boxes, kinds):
    images = [StatImage(1000, 1000, [(c, 0, 0, 0.5, 0.5)] * n) for c, n in boxes.items() if n]
    assert {w["kind"] for w in stats_for(images)["warnings"]} == kinds


def test_many_small_warning():
    s = stats_for([StatImage(1000, 1000, [(0, 0, 0, 0.01, 0.01)] * 60 + [(1, 0, 0, 0.5, 0.5)] * 60
                                         + [(2, 0, 0, 0.01, 0.01)] * 60)])  # fmt: skip
    assert "many_small" in {w["kind"] for w in s["warnings"]}


def test_endpoints(client, ds, db):  # noqa: F811
    pid = ds["pid"]
    s = client.get(f"/api/projects/{pid}/stats/dataset").json()
    assert s["images"] == 4 and s["boxes"] == 3
    assert [c["name"] for c in s["classes"]] == ["pallet", "person"]
    reviewed = client.get(f"/api/projects/{pid}/stats/dataset", params={"status": "reviewed"}).json()
    assert reviewed["images"] == 2 and reviewed["boxes"] == 2

    v = client.post(f"/api/projects/{pid}/versions", json={"name": "v", "split": {"train": 1, "val": 0}}).json()
    db.add(Annotation(image_id=ds["ids"][0], class_id=ds["pallet"], x_min=0, y_min=0, x_max=0.1,
                      y_max=0.1, source="manual", is_approved=True))  # fmt: skip
    db.commit()
    vs = client.get(f"/api/versions/{v['id']}/stats").json()
    assert vs["images"] == 2 and vs["boxes"] == 2  # anotasi baru tidak masuk versi lama
    assert client.get("/api/versions/9999/stats").status_code == 404
