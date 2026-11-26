"""CLI — test isolato di registrazione + riproduzione (equivalente Python di arecord/aplay).

Uso:
    python test_audio.py                    # registra 5s dal microfono e li riproduce
    python test_audio.py --duration 3
    python test_audio.py --record-only       # solo registrazione, nessuna riproduzione
"""

from __future__ import annotations

import argparse
import sys

from imaginarium.audio_io import play_audio, record_audio
from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.exceptions import ImaginariumError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test di registrazione/riproduzione audio")
    add_config_argument(parser)
    parser.add_argument("--duration", type=float, default=None, help="Secondi di registrazione")
    parser.add_argument("--record-only", action="store_true", help="Non riprodurre dopo la registrazione")
    parser.add_argument("-o", "--output", default=None, help="Path del WAV di output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = bootstrap(args.config)
    output = args.output or (config.paths.audio_dir / "test_audio.wav")

    try:
        print(f"Registrazione ({args.duration or config.audio.record_seconds}s, device {config.audio.record_device})...")
        path = record_audio(config.audio, output, duration_s=args.duration)
        print(f"OK — audio salvato in {path}")
        if not args.record_only:
            print(f"Riproduzione (device {config.audio.playback_device})...")
            play_audio(config.audio, path)
            print("OK — riproduzione completata")
    except ImaginariumError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
