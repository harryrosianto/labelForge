"""CLI untuk menguji model auto-label di foto asli, tanpa DB/Redis/web.

Contoh:
  python -m labelforge.cli detect --provider grounding_dino \\
      --classes "pallet,person,forklift" --prompt "pallet=wooden pallet" \\
      --input ./samples --output ./out
  python -m labelforge.cli detect --provider owlv2 --mode image_guided \\
      --exemplar-dir ./exemplars --input ./samples --output ./out_owl
  python -m labelforge.cli providers
"""

import argparse
import json
import sys
import time
from pathlib import Path

from labelforge.config import get_settings
from labelforge.core.visualize import PALETTE, draw_boxes
from labelforge.providers.base import ClassDef, ProviderError, load_image
from labelforge.providers.registry import describe_providers, get_provider

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def _key_values(items: list[str], flag: str) -> dict[str, str]:
    out = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"{flag} harus berformat key=value, didapat: {item!r}")
        key, value = item.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _list_images(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def _build_classes(args) -> list[ClassDef]:
    names = [n.strip() for n in (args.classes or "").split(",") if n.strip()]
    exemplar_dir = Path(args.exemplar_dir) if args.exemplar_dir else None
    if not names and exemplar_dir:
        names = sorted(p.name for p in exemplar_dir.iterdir() if p.is_dir())
    if not names:
        raise SystemExit("Isi --classes (atau --exemplar-dir dengan subfolder per class)")

    prompts = _key_values(args.prompt, "--prompt")
    unknown = set(prompts) - set(names)
    if unknown:
        raise SystemExit(f"--prompt untuk class yang tidak ada di --classes: {sorted(unknown)}")

    classes = []
    for i, name in enumerate(names):
        exemplars: tuple[Path, ...] = ()
        if exemplar_dir and (exemplar_dir / name).is_dir():
            exemplars = tuple(_list_images(exemplar_dir / name))
        classes.append(ClassDef(i, name, prompts.get(name), exemplars))
    return classes


def cmd_detect(args) -> int:
    settings = get_settings()
    if args.device:
        settings.device = args.device
    if args.fp16:
        settings.use_fp16 = True

    classes = _build_classes(args)
    if args.provider is None:
        args.provider = settings.default_provider
        if args.mode is None:
            args.mode = settings.default_mode
    params = _key_values(args.param, "--param")
    for flag in ("mode", "box_threshold", "text_threshold", "score_threshold"):
        if getattr(args, flag) is not None:
            params[flag] = getattr(args, flag)

    images = _list_images(Path(args.input))[: args.limit or None]
    if not images:
        raise SystemExit(f"Tidak ada gambar di {args.input}")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    provider = get_provider(args.provider)
    resolved = provider.resolve_params(params)
    for w in provider.class_warnings(resolved["mode"], classes):
        print(f"[peringatan] {w}", file=sys.stderr)

    print(f"Provider : {args.provider} (mode={resolved['mode']})")
    print(f"Classes  : " + ", ".join(f"{c.name} → '{c.prompt}'" for c in classes))
    print(f"Params   : {resolved}")
    t0 = time.perf_counter()
    provider.load()
    print(f"Model    : siap di {provider.device} dalam {time.perf_counter() - t0:.1f} dtk\n")

    names = {c.id: c.name for c in classes}
    per_class = {c.name: 0 for c in classes}
    summary_images = []
    for idx, path in enumerate(images, 1):
        entry = {"image": path.name}
        try:
            result = provider.detect_with_info(path, classes, resolved)
        except Exception as e:  # satu gambar gagal tidak menghentikan seluruh run
            entry["error"] = f"{type(e).__name__}: {e}"
            print(f"[{idx}/{len(images)}] {path.name}: ERROR {entry['error']}")
            summary_images.append(entry)
            continue

        image = load_image(path)
        dets = [
            {
                "class_id": d.class_id,
                "class_name": names[d.class_id],
                "bbox": [round(v, 2) for v in d.bbox],
                "confidence": round(d.confidence, 4),
            }
            for d in result.detections
        ]
        for d in dets:
            per_class[d["class_name"]] += 1
        (out_dir / f"{path.stem}.json").write_text(
            json.dumps(
                {
                    "image": path.name,
                    "width": image.width,
                    "height": image.height,
                    "provider": args.provider,
                    "source": provider.source_tag(resolved["mode"]),
                    "params": resolved,
                    "duration_ms": result.duration_ms,
                    "detections": dets,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        drawn = draw_boxes(
            image,
            [(d["bbox"], f"{d['class_name']} {d['confidence']:.2f}",
              PALETTE[d["class_id"] % len(PALETTE)]) for d in dets],
        )  # fmt: skip
        drawn.save(out_dir / f"{path.stem}.jpg", quality=90)

        entry.update(detections=len(dets), duration_ms=result.duration_ms)
        summary_images.append(entry)
        counts = ", ".join(
            f"{n}={sum(d['class_name'] == n for d in dets)}" for n in per_class
        )
        print(f"[{idx}/{len(images)}] {path.name}: {len(dets)} box ({counts}) {result.duration_ms} ms")

    ok = [e for e in summary_images if "error" not in e]
    summary = {
        "provider": args.provider,
        "params": resolved,
        "device": provider.device,
        "classes": [{"id": c.id, "name": c.name, "prompt": c.prompt,
                     "exemplars": len(c.exemplar_paths)} for c in classes],  # fmt: skip
        "images": len(images),
        "failed": len(images) - len(ok),
        "detections_per_class": per_class,
        "avg_duration_ms": round(sum(e["duration_ms"] for e in ok) / len(ok)) if ok else None,
        "per_image": summary_images,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSelesai: {len(ok)}/{len(images)} gambar, deteksi per class {per_class}, "
          f"rata-rata {summary['avg_duration_ms']} ms/gambar → {out_dir.resolve()}")  # fmt: skip
    return 0 if ok else 1


def cmd_import_images(args) -> int:
    from labelforge.db import get_session_factory
    from labelforge.models import Project
    from labelforge.services.images import InvalidImageError, ingest_image
    from labelforge.storage import get_storage

    storage = get_storage()
    added = duplicates = failed = 0
    with get_session_factory()() as db:
        if db.get(Project, args.project_id) is None:
            raise SystemExit(f"Project {args.project_id} tidak ditemukan")
        for path in _list_images(Path(args.input)):
            try:
                res = ingest_image(db, storage, args.project_id, path.name, path.read_bytes())
            except InvalidImageError as e:
                failed += 1
                print(f"[gagal] {e}")
                continue
            db.commit()
            duplicates += res.duplicate
            added += not res.duplicate
    print(f"Ditambahkan {added}, duplikat {duplicates}, gagal {failed}")
    return 0


def cmd_providers(_args) -> int:
    for p in describe_providers():
        status = "tersedia" if p["available"] else f"TIDAK tersedia: {p['unavailable_reason']}"
        default = f" [DEFAULT, mode {p['default_mode']}]" if p["is_default"] else ""
        print(f"{p['name']} ({p['label']}){default} — {status}")
        for mode, specs in p["params"].items():
            params = ", ".join(f"{s['name']}={s['default']}" for s in specs)
            print(f"  mode {mode}: {params}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m labelforge.cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("detect", help="Jalankan auto-label pada folder gambar")
    d.add_argument("--provider", help="Default dari DEFAULT_PROVIDER di .env (owlv2)")
    d.add_argument("--mode", help="text | image_guided (OWLv2)")
    d.add_argument("--classes", help='Daftar class dipisah koma, mis. "pallet,person,forklift"')
    d.add_argument("--prompt", action="append", default=[], metavar="CLASS=TEKS",
                   help='Text prompt per class, boleh diulang: --prompt "pallet=wooden pallet"')
    d.add_argument("--exemplar-dir", help="Folder berisi subfolder per class berisi crop exemplar")
    d.add_argument("--input", required=True, help="File gambar atau folder")
    d.add_argument("--output", required=True)
    d.add_argument("--box-threshold", type=float)
    d.add_argument("--text-threshold", type=float)
    d.add_argument("--score-threshold", type=float)
    d.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                   help="Parameter provider lain, mis. --param class_agnostic_nms=true")
    d.add_argument("--device", help="auto | cpu | cuda")
    d.add_argument("--fp16", action="store_true", help="fp16 (hanya berlaku di CUDA)")
    d.add_argument("--limit", type=int, help="Proses N gambar pertama saja")
    d.set_defaults(func=cmd_detect)

    i = sub.add_parser("import-images", help="Impor folder gambar ke project (pakai DB & storage)")
    i.add_argument("--project-id", type=int, required=True)
    i.add_argument("--input", required=True)
    i.set_defaults(func=cmd_import_images)

    p = sub.add_parser("providers", help="Daftar provider dan parameternya")
    p.set_defaults(func=cmd_providers)

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # konsol Windows default cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.func(args)
    except ProviderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
