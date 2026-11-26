"""CLI — i 3 comandi, oggi a tastiera, domani a pulsante fisico.

Uso:
    python run_button.py 1                        # scatta, racconta in IT+EN+SL
    python run_button.py 2 --lang it               # scatta, racconta solo in italiano
    python run_button.py 2 --lang en               # ... solo in inglese
    python run_button.py 3                         # traduce (dal pool) l'ultima storia del comando 2
    python run_button.py 1 --image foto.jpg         # salta lo scatto, usa un'immagine esistente
    python run_button.py 2 --lang sl --no-play      # sintetizza ma non riproduce
    python run_button.py 1 --stats --json           # tempi per fase, riepilogo JSON

Ogni comando qui chiama una sola funzione pura di ``imaginarium.commands``
(``run_command_1/2/3``): è il punto in cui, quando saranno collegati i
pulsanti fisici, ogni callback GPIO chiamerà direttamente quella funzione —
vedi docs/06_comandi_e_workflow.md.

Nessuna di queste chiamate parla con Ollama: la storia viene sempre dal pool
pre-generato. Prerequisiti: modelli sincronizzati in models/ (vedi
docs/05_modelli_e_storie.md), voci Piper in voices/ (docs/04_tts_setup.md),
mappa soggetti generata (tools/build_subject_map.py).
"""

from __future__ import annotations

import argparse
import json
import sys

from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.commands import (
    Command1Result,
    Command2Result,
    Command3Result,
    CommandError,
    run_command_1,
    run_command_2,
    run_command_3,
)
from imaginarium.exceptions import ImaginariumError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="I 3 comandi della pipeline (foto -> storia -> audio)")
    add_config_argument(parser)
    parser.add_argument("button", type=int, choices=(1, 2, 3), help="Quale comando eseguire")
    parser.add_argument(
        "--lang",
        choices=("it", "en", "sl"),
        help="Lingua per il comando 2 (obbligatoria per quel comando)",
    )
    parser.add_argument("--image", help="Usa questa immagine invece di scattarne una nuova")
    parser.add_argument("--no-play", action="store_true", help="Non riprodurre l'audio generato")
    parser.add_argument("--stats", action="store_true", help="Tempi per fase")
    parser.add_argument("--json", action="store_true", help="Riepilogo finale in JSON")
    return parser.parse_args()


def _print_stats(timings: dict[str, float]) -> None:
    total = sum(timings.values())
    print("\n--- Tempi per fase ---")
    for phase, seconds in timings.items():
        share = seconds / total * 100 if total else 0.0
        print(f"  {phase:<20} {seconds:7.2f}s  ({share:4.1f}%)")
    print(f"  {'TOTALE':<20} {total:7.2f}s")


def _print_command1(result: Command1Result) -> None:
    print(
        f"\n[{result.resolution.tier}] soggetto: '{result.resolution.pool_key}' "
        f"({result.resolution.reason})"
    )
    for lang, story in result.stories.items():
        print(f"\n--- {lang.upper()} ---")
        print(story.text)
        print(f"(audio: {result.audio_paths[lang]})")


def _print_command2(result: Command2Result) -> None:
    print(
        f"\n[{result.resolution.tier}] soggetto: '{result.resolution.pool_key}' "
        f"({result.resolution.reason})"
    )
    print(f"\n--- {result.lang.upper()} ---")
    print(result.story.text)
    print(f"(audio: {result.audio_path})")


def _print_command3(result: Command3Result) -> None:
    print(
        f"\nTraduzione di '{result.last_story.pool_key}' "
        f"(raccontata in {result.last_story.lang.upper()} il {result.last_story.saved_at})"
    )
    for lang, story in result.stories.items():
        print(f"\n--- {lang.upper()} ---")
        print(story.text)
        print(f"(audio: {result.audio_paths[lang]})")


def main() -> None:
    args = parse_args()
    if args.button == 2 and not args.lang:
        print("\nIl comando 2 richiede --lang it|en|sl\n", file=sys.stderr)
        raise SystemExit(2)

    config = bootstrap(args.config)
    play = not args.no_play

    try:
        if args.button == 1:
            result = run_command_1(config, image_path=args.image, play=play)
            payload = {
                "subject": result.resolution.pool_key,
                "tier": result.resolution.tier,
                "classification": result.classification.to_dict(),
                "stories": {lang: story.text for lang, story in result.stories.items()},
                "audio": {lang: str(path) for lang, path in result.audio_paths.items()},
            }
            timings = result.timings
            printer = lambda: _print_command1(result)  # noqa: E731
        elif args.button == 2:
            result = run_command_2(config, args.lang, image_path=args.image, play=play)
            payload = {
                "subject": result.resolution.pool_key,
                "tier": result.resolution.tier,
                "lang": result.lang,
                "classification": result.classification.to_dict(),
                "story": result.story.text,
                "audio": str(result.audio_path),
            }
            timings = result.timings
            printer = lambda: _print_command2(result)  # noqa: E731
        else:
            result = run_command_3(config, play=play)
            payload = {
                "subject": result.last_story.pool_key,
                "original_lang": result.last_story.lang,
                "stories": {lang: story.text for lang, story in result.stories.items()},
                "audio": {lang: str(path) for lang, path in result.audio_paths.items()},
            }
            timings = result.timings
            printer = lambda: _print_command3(result)  # noqa: E731
    except (ImaginariumError, CommandError) as exc:
        print(f"\nErrore nel comando {args.button}: {exc}\n", file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        payload["timings"] = {phase: round(s, 3) for phase, s in timings.items()}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        printer()

    if args.stats:
        _print_stats(timings)


if __name__ == "__main__":
    main()
