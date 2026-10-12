import re


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "dataset"


def version_zip_name(project_name: str, version_name: str, fmt: str) -> str:
    """Nama file ZIP export versi; juga dirujuk template notebook Colab."""
    return f"{slug(project_name)}-{slug(version_name)}_{fmt}.zip"
