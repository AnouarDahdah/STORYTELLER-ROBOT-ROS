"""CLI — test isolato della sintesi vocale (Piper) + riproduzione.

Uso:
    python test_tts.py "Ciao, sono un orsacchiotto di peluche!"
    python test_tts.py "Testo di prova" --no-play
"""

from __future__ import annotations

import argparse
import sys

from imaginarium.audio_io import play_audio
from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.exceptions import ImaginariumError
from imaginarium.tts import synthesize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test di sintesi vocale (Piper)")
    add_config_argument(parser)
    parser.add_argument("text", nargs="?", default="Ciao! Questo è un test della voce.", help="Testo da sintetizzare")
    parser.add_argument("--no-play", action="store_true", help="Non riprodurre dopo la sintesi")
    parser.add_argument("-o", "--output", default=None, help="Path del WAV di output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = bootstrap(args.config)
    output = args.output or (config.paths.audio_dir / "test_tts.wav")

    try:
        print(f"Sintesi ({config.tts.voice_model.name})...")
        path = synthesize(args.text, output, config.tts)
        print(f"OK — audio salvato in {path}")
        if not args.no_play:
            play_audio(config.audio, path)
    except ImaginariumError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
