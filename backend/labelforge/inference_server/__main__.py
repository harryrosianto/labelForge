"""python -m labelforge.inference_server [--host 0.0.0.0] [--port 8100] [--preload grounding_dino,owlv2]"""

import argparse

import uvicorn

from labelforge.providers.registry import get_provider


def main() -> None:
    parser = argparse.ArgumentParser(description="LabelForge inference server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--preload", default="", help="Provider yang di-load saat start, dipisah koma")
    args = parser.parse_args()

    for name in filter(None, (n.strip() for n in args.preload.split(","))):
        print(f"Memuat model {name} ...", flush=True)
        get_provider(name).load()

    uvicorn.run("labelforge.inference_server.app:app", host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
