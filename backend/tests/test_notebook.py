import ast
import json

from tests.test_exporters import ds  # noqa: F401
from tests.test_versions import create


def _code_cells(nb: dict) -> list[str]:
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def test_colab_notebook_matches_export(client, ds):  # noqa: F811
    v = create(client, ds["pid"], name="V1 Gudang", split_mode="segment", segment_size=10,
               preprocessing={"resize": "fit", "width": 960, "height": 544}).json()  # fmt: skip
    r = client.get(f"/api/versions/{v['id']}/colab-notebook")
    assert r.status_code == 200
    assert 'filename="warehouse-v1-gudang_colab.ipynb"' in r.headers["content-disposition"]
    nb = json.loads(r.content)
    assert nb["nbformat"] == 4 and nb["metadata"]["accelerator"] == "GPU"

    job = client.post(f"/api/versions/{v['id']}/export-jobs", json={"format": "yolo"}).json()
    zip_name = job["result"]["filename"]
    code = "\n".join(_code_cells(nb))
    assert f"/content/drive/MyDrive/labelforge/{zip_name}" in code
    assert "IMGSZ = 960" in code and "yolo11n.pt" in code and "format='onnx'" in code
    intro = "".join(nb["cells"][0]["source"])
    assert "per segmen 10 frame per sumber" in intro and "pallet, person" in intro

    for cell in _code_cells(nb):  # sel kode harus Python valid (perintah shell `!` dilewati)
        ast.parse("\n".join(line for line in cell.splitlines() if not line.lstrip().startswith("!")))


def test_colab_notebook_default_size_and_404(client, ds):  # noqa: F811
    v = create(client, ds["pid"]).json()
    nb = client.get(f"/api/versions/{v['id']}/colab-notebook").json()
    assert "IMGSZ = 640" in "\n".join(_code_cells(nb))
    assert "acak per gambar" in "".join(nb["cells"][0]["source"])
    assert client.get("/api/versions/999/colab-notebook").status_code == 404
