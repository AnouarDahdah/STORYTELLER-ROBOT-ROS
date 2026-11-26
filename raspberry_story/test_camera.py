"""CLI — test isolato della fotocamera (equivalente Python del comando v4l2-ctl manuale).

Uso:
    python test_camera.py                  # salva in runtime/photos/test_camera.jpg
    python test_camera.py -o mia_foto.jpg
"""

from __future__ import annotations

import argparse
import sys

from imaginarium.camera import capture_photo
from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.exceptions import ImaginariumError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test di scatto dalla webcam")
    add_config_argument(parser)
    parser.add_argument("-o", "--output", default=None, help="Path del JPEG di output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = bootstrap(args.config)
    output = args.output or (config.paths.photos_dir / "test_camera.jpg")

    try:
        path = capture_photo(config.camera, output)
    except ImaginariumError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(f"OK — foto salvata in {path}")


if __name__ == "__main__":
    main()
