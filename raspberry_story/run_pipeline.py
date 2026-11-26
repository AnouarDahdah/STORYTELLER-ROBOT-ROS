"""CLI — pipeline completa: foto -> classificazione -> storia -> audio.

Uso:
    python run_pipeline.py                       # scatta, classifica, racconta, riproduce
    python run_pipeline.py --image foto.jpg       # salta lo scatto, usa un'immagine esistente
    python run_pipeline.py --show-plan            # stampa anche lo scheletro narrativo
    python run_pipeline.py --show-prompt          # stampa il prompt inviato al modello
    python run_pipeline.py --stats                # tempi per fase e statistiche di generazione
    python run_pipeline.py --use-cache            # pesca dal pool pre-generato (nessuna inferenza)
    python run_pipeline.py --no-cache             # forza la generazione con il modello
    python run_pipeline.py --no-play              # sintetizza ma non riproduce l'audio
    python run_pipeline.py --json                 # riepilogo finale in JSON

Per confrontare *configurazioni* di generazione senza toccare l'hardware usa
``bench_story.py``: misura la sola parte testuale, è molto più rapido da
iterare e mostra i prompt di ogni variante.

Prerequisiti: webcam/microfono/cuffie configurati in config.yaml, Ollama
attivo con il modello configurato (default gemma3:4b), voce Piper scaricata.
Vedi README.md per i dettagli di setup.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.exceptions import ImaginariumError
from imaginarium.pipeline import PipelineResult, run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Foto -> classificazione -> storia -> audio")
    add_config_argument(parser)
    parser.add_argument("--image", help="Usa questa immagine invece di scattarne una nuova")
    parser.add_argument("--show-plan", action="store_true", help="Stampa lo scheletro narrativo")
    parser.add_argument(
        "--show-prompt", action="store_true", help="Stampa il prompt inviato al modello"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Tempi per fase e statistiche di generazione"
    )
    parser.add_argument("--no-play", action="store_true", help="Non riprodurre l'audio generato")
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignora il pool pre-generato e genera con il modello",
    )
    cache_group.add_argument(
        "--use-cache",
        action="store_true",
        help="Usa il pool pre-generato anche se disattivato in config.yaml",
    )
    parser.add_argument("--top-k", type=int, default=3, help="Alternative da registrare per livello")
    parser.add_argument("--json", action="store_true", help="Riepilogo finale come JSON")
    return parser.parse_args()


def print_stats(result: PipelineResult) -> None:
    """Dove è andato il tempo, fase per fase e chiamata per chiamata.

    È la stessa lettura che offre ``bench_story.py``, ma sulla corsa reale:
    serve a verificare che la configurazione scelta al banco regga anche con
    scatto, classificazione e sintesi nel mezzo.
    """
    print("\n--- Tempi per fase ---")
    total = result.total_s
    for phase, seconds in result.timings.items():
        share = seconds / total * 100 if total else 0.0
        print(f"  {phase:<16} {seconds:7.1f}s  ({share:4.1f}%)")
    print(f"  {'TOTALE':<16} {total:7.1f}s")

    metrics = result.story.metrics
    if not metrics.calls:
        print(
            "\n  Nessuna chiamata al modello: la storia viene dal pool pre-generato"
            " (cache.enabled).\n  Confronta con --no-cache per vedere quanto costa generarla."
        )
    else:
        print("\n--- Chiamate al modello ---")
        for call in metrics.calls:
            speed = f"{call.eval_tokens_per_s:.1f} tok/s" if call.eval_tokens_per_s else "n/d"
            print(
                f"  {call.label:<10} {call.wall_s:6.1f}s  "
                f"in {call.prompt_eval_count or 0:>4} tok  "
                f"out {call.eval_count or 0:>4} tok  "
                f"{speed:>12}  stop={call.done_reason or '-'}  {call.outcome}"
            )
        summary = metrics.summary()
        print(
            f"  -> {summary['calls']} chiamate ({summary['discarded']} scartate), "
            f"{summary['eval_tokens']} token generati, {result.story.words} parole"
        )
        if summary["discarded"]:
            print(
                "     Ogni scarto costa una generazione intera: se si ripete, rivedi "
                "story.min_words / story.accept_truncated (vedi bench_story.py --preset lenient)."
            )


def main() -> None:
    args = parse_args()
    config = bootstrap(args.config)

    # Il pool e' la leva piu' drastica sulla latenza: poterlo accendere e
    # spegnere da riga di comando rende il confronto immediato, senza
    # riscrivere config.yaml fra una prova e l'altra.
    if args.no_cache or args.use_cache:
        config = replace(config, cache=replace(config.cache, enabled=args.use_cache))

    try:
        result = run_pipeline(
            config,
            image_path=args.image,
            play=not args.no_play,
            top_k=args.top_k,
        )
    except ImaginariumError as exc:
        print(f"\nErrore nella pipeline: {exc}\n", file=sys.stderr)
        raise SystemExit(1)

    if args.show_prompt:
        print("\n--- Prompt inviato (prosa) ---")
        print(result.story.prompt)
        print("------------------------------")

    if args.show_plan and result.story.plan is not None:
        print("\n--- Piano narrativo ---")
        print(result.story.plan.as_briefing(result.subject))
        print("-----------------------")

    if args.json:
        payload = {
            "photo": str(result.photo_path),
            "classification": result.classification.to_dict(),
            "subject": result.subject,
            "story": result.story.text,
            "audio": str(result.audio_path),
            "timings": {phase: round(s, 3) for phase, s in result.timings.items()},
            "story_metrics": result.story.metrics.summary(),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"\n{result.story.text}\n")
        print(f"(audio salvato in {result.audio_path})")

    if args.stats:
        print_stats(result)


if __name__ == "__main__":
    main()
