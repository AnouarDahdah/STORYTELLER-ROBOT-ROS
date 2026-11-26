"""CLI — costruisce il pool di storie pre-generate.

Le classi riconosciute sono un insieme chiuso e piccolo: le storie si possono
generare **in anticipo**, su una macchina più potente del Pi (o sul Pi stesso,
lasciandolo lavorare la notte), e a runtime la pipeline si limita a pescarne
una. È l'unica leva che azzera la latenza invece di ridurla — vedi
``imaginarium/story_cache.py`` per il compromesso di prodotto che comporta.

Siccome il tempo di generazione qui non è più un vincolo, conviene generare
con la configurazione **migliore**, non con la più veloce: modello grande,
due passate, storie lunghe.

    # pool sulle 9 macro-classi, 5 storie ciascuna, in qualità massima
    python pregenerate_stories.py --preset quality --per-subject 5

    # con un modello più capace di quello che gira sul Pi
    python pregenerate_stories.py --model qwen3:8b --preset quality --per-subject 8

    # aggiungere soggetti specifici a un pool già esistente
    python pregenerate_stories.py --subject "super mario" --per-subject 5 --append

    # includere anche tutte le sottoclassi presenti in models/hierarchy.json
    python pregenerate_stories.py --from-hierarchy --per-subject 3

Il file prodotto (default ``runtime/stories.json``) va copiato sul Pi insieme
al resto, e attivato in ``config.yaml``:

    cache:
      enabled: true
      path: runtime/stories.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.exceptions import ConfigError, ImaginariumError
from imaginarium.presets import apply_overrides, describe, get_preset, parse_assignment
from imaginarium.story import generate_story, main_class_subjects, warmup
from imaginarium.story_cache import CachedStory, StoryCache, StoryCacheError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera in anticipo un pool di storie, una per soggetto ripetuta N volte",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Esempi:\n"
        "  python pregenerate_stories.py --preset quality --per-subject 5\n"
        "  python pregenerate_stories.py --model qwen3:8b --per-subject 8\n"
        "  python pregenerate_stories.py --subject 'super mario' --per-subject 5 --append\n",
    )
    add_config_argument(parser)
    parser.add_argument(
        "--out", help="File del pool (default: quello in config.yaml, cache.path)"
    )
    parser.add_argument(
        "--per-subject",
        type=int,
        default=5,
        metavar="N",
        help="Storie da generare per ciascun soggetto (default: 5)",
    )
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        metavar="TESTO",
        help="Soggetto da coprire; ripetibile (default: le 9 macro-classi)",
    )
    parser.add_argument(
        "--from-hierarchy",
        action="store_true",
        help="Includi anche tutte le sottoclassi di models/hierarchy.json",
    )
    parser.add_argument(
        "--preset",
        default="quality",
        help="Preset di generazione (default: quality — qui il tempo non è un vincolo)",
    )
    parser.add_argument("--model", help="Scorciatoia per --set ollama_model=...")
    parser.add_argument(
        "--set", action="append", default=[], metavar="CHIAVE=VALORE", help="Override puntuali"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Aggiungi al pool esistente invece di sovrascriverlo",
    )
    return parser.parse_args()


def subjects_from_hierarchy(models_root: Path) -> list[str]:
    """Tutti i soggetti nominati in ``hierarchy.json`` (macro-classi + sottoclassi)."""
    from imaginarium.story import humanize_label

    path = models_root / "hierarchy.json"
    if not path.is_file():
        print(f"  hierarchy.json non trovato in {models_root}: uso solo le macro-classi")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  hierarchy.json illeggibile ({exc}): uso solo le macro-classi")
        return []

    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"classes", "labels", "subclasses", "children"} and isinstance(
                    value, list
                ):
                    found.extend(str(item) for item in value if isinstance(item, str))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return [humanize_label(label) for label in dict.fromkeys(found)]


def main() -> None:
    args = parse_args()
    config = bootstrap(args.config)

    try:
        overrides = dict(parse_assignment(item) for item in args.set)
        if args.model:
            overrides["ollama_model"] = args.model
        story_config = apply_overrides(get_preset(args.preset).apply(config.story), overrides)
    except ConfigError as exc:
        print(f"\nConfigurazione non valida: {exc}\n", file=sys.stderr)
        raise SystemExit(2)

    subjects = list(args.subject) or main_class_subjects()
    if args.from_hierarchy:
        subjects.extend(subjects_from_hierarchy(config.paths.models_root))
    subjects = list(dict.fromkeys(subjects))

    out_path = Path(args.out) if args.out else config.cache.path

    cache = StoryCache(stories={}, model=story_config.ollama_model)
    if args.append:
        try:
            cache = StoryCache.load(out_path)
            print(f"  Pool esistente: {cache.total} storie in {out_path}")
        except StoryCacheError as exc:
            print(f"  Nessun pool da estendere ({exc.__class__.__name__}): ne creo uno nuovo")

    total = len(subjects) * args.per_subject
    print(f"\n  {len(subjects)} soggetti × {args.per_subject} storie = {total} generazioni.")
    print(f"  {describe(story_config, config.story)}")
    print(
        "  Questo passo è lento di proposito: gira una volta sola, su una macchina\n"
        "  potente, e in cambio a runtime il Pi non chiama piu' il modello.\n"
    )

    try:
        warmup(story_config)
    except ImaginariumError as exc:
        print(f"\nModello non raggiungibile: {exc}\n", file=sys.stderr)
        raise SystemExit(1)

    started = time.perf_counter()
    produced = 0
    failed = 0
    for index, subject in enumerate(subjects, start=1):
        items = cache.stories.setdefault(subject, [])
        for repeat in range(1, args.per_subject + 1):
            tag = f"[{index}/{len(subjects)}] {subject} ({repeat}/{args.per_subject})"
            print(f"  {tag} ...", end=" ", flush=True)
            try:
                result = generate_story(subject, story_config)
            except ImaginariumError as exc:
                failed += 1
                print(f"FALLITA: {exc}")
                continue
            items.append(
                CachedStory(
                    text=result.text,
                    subject=subject,
                    plan=result.plan,
                    model=story_config.ollama_model,
                )
            )
            produced += 1
            print(f"{result.words} parole in {result.metrics.wall_s:.1f}s")

    cache.model = story_config.ollama_model
    cache.generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    cache.save(out_path)

    elapsed = time.perf_counter() - started
    print(
        f"\n  {produced} storie generate ({failed} fallite) in {elapsed / 60:.1f} min."
        f"\n  Pool salvato in {out_path} — {cache.total} storie su {len(cache.stories)} soggetti."
    )
    thin = [s for s, items in cache.stories.items() if len(items) < config.cache.min_pool]
    if thin:
        print(
            f"  Attenzione: {len(thin)} soggetti sotto cache.min_pool={config.cache.min_pool} "
            f"({', '.join(thin[:5])}{'...' if len(thin) > 5 else ''}):\n"
            "  per questi la pipeline tornera' a generare con il modello."
        )
    print(
        "\n  Per usarlo, in config.yaml:\n"
        "      cache:\n"
        "        enabled: true\n"
        f"        path: {out_path.name if not args.out else args.out}\n"
    )


if __name__ == "__main__":
    main()
