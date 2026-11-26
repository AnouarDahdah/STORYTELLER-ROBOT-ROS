"""CLI — banco di prova della sola generazione del testo.

Misura e confronta configurazioni di generazione **senza** fotocamera,
classificatore o sintesi vocale: parte da un soggetto testuale e si ferma
alla storia. È il modo per rispondere alla domanda che sta a monte di ogni
ottimizzazione — *dove va il tempo* — prima di decidere quale leva tirare.

Uso tipico, nell'ordine in cui conviene procedere:

    # 0. cosa c'è da provare
    python bench_story.py --list-presets

    # 1. vedere i prompt senza chiamare il modello (istantaneo)
    python bench_story.py --dry-run --show-prompt

    # 2. una misura di riferimento, com'è oggi
    python bench_story.py --preset baseline --repeat 3

    # 3. confronto fra configurazioni (stessa sessione, stesso soggetto)
    python bench_story.py --preset baseline --preset single_pass --preset fast --repeat 3

    # 4. una leva singola, senza preset
    python bench_story.py --set num_predict=300 --set two_pass=false

    # 5. un modello diverso
    python bench_story.py --model gemma3:1b --preset fast

    # 6. tutte le 9 macro-classi, esito salvato su file
    python bench_story.py --all-classes --preset fast --json runtime/bench/fast.json

Note sulla misura:

- il **warmup** è attivo di default: la prima chiamata a un modello appena
  caricato paga il tempo di lettura dei pesi da disco, che non c'entra con
  la velocità di generazione. ``--no-warmup`` se vuoi misurare anche quello
  (è il caso reale del primo scatto della giornata).
- con ``--repeat > 1`` conta la **mediana**, non la media: su un Pi4 basta
  un processo di sistema per produrre un valore anomalo.
- per confrontare la *qualità* a parità di caso, fissa ``--seed``: rende le
  generazioni riproducibili e isola l'effetto della configurazione dal
  rumore del campionamento.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.config import StoryConfig
from imaginarium.exceptions import ConfigError, ImaginariumError
from imaginarium.presets import (
    apply_overrides,
    describe,
    diff_fields,
    get_preset,
    parse_assignment,
    preset_names,
)
from imaginarium.story import (
    EXAMPLE_PLAN,
    PLAN_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    StoryResult,
    aggregate,
    build_options,
    build_plan_prompt,
    build_story_prompt,
    generate_story,
    main_class_subjects,
    warmup,
)

DEFAULT_SUBJECT = "trenino di legno"


# ── Formattazione ─────────────────────────────────────────────────────────


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def print_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """Tabella a colonne allineate, senza dipendenze esterne."""
    if not rows:
        return
    cells = [[str(c) for c in row] for row in rows]
    widths = [
        max(len(headers[i]), max(len(row[i]) for row in cells)) for i in range(len(headers))
    ]
    # La prima colonna resta a sinistra (nomi), le altre a destra (numeri).
    def line(values: Sequence[str]) -> str:
        out = [values[0].ljust(widths[0])]
        out += [values[i].rjust(widths[i]) for i in range(1, len(values))]
        return "  ".join(out)

    print("  " + line(list(headers)))
    print("  " + "-" * (sum(widths) + 2 * (len(widths) - 1)))
    for row in cells:
        print("  " + line(row))


def print_block(title: str, body: str) -> None:
    print(f"\n┌── {title} " + "─" * max(0, 66 - len(title)))
    for raw_line in body.splitlines() or [""]:
        print(f"│ {raw_line}")
    print("└" + "─" * 70)


# ── Un'esecuzione ─────────────────────────────────────────────────────────


@dataclass
class BenchRun:
    """Esito di una singola generazione sotto una configurazione."""

    preset: str
    subject: str
    iteration: int
    config: StoryConfig
    result: StoryResult | None = None
    error: str | None = None
    wall_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.result is not None

    def to_dict(self, *, include_prompt: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "preset": self.preset,
            "subject": self.subject,
            "iterazione": self.iteration,
            "modello": self.config.ollama_model,
            "wall_s": round(self.wall_s, 3),
            "ok": self.ok,
            "errore": self.error,
        }
        if self.result is not None:
            data["parole"] = self.result.words
            data["tentativi"] = self.result.attempts
            data["piano"] = self.result.plan.to_dict() if self.result.plan else None
            data["metriche"] = self.result.metrics.summary()
            data["chiamate"] = [
                c.to_dict(include_prompt=include_prompt) for c in self.result.metrics.calls
            ]
            if include_prompt:
                data["prompt_prosa"] = self.result.prompt
                data["storia"] = self.result.text
        return data


@dataclass
class PresetOutcome:
    """Tutte le esecuzioni di un preset, pronte da aggregare."""

    name: str
    config: StoryConfig
    runs: list[BenchRun] = field(default_factory=list)

    @property
    def ok_runs(self) -> list[BenchRun]:
        return [r for r in self.runs if r.ok]

    def summary_row(self) -> list[Any]:
        ok = self.ok_runs
        if not ok:
            return [self.name, self.config.ollama_model, f"0/{len(self.runs)}", *["-"] * 7]
        walls = [r.wall_s for r in ok]
        stats = aggregate(walls)
        words = aggregate([float(r.result.words) for r in ok])  # type: ignore[union-attr]
        speeds = [
            r.result.metrics.eval_tokens_per_s  # type: ignore[union-attr]
            for r in ok
            if r.result and r.result.metrics.eval_tokens_per_s
        ]
        total_wall = sum(walls) or 1.0
        plan_share = sum(r.result.metrics.plan_wall_s for r in ok) / total_wall * 100  # type: ignore[union-attr]
        calls = sum(len(r.result.metrics.calls) for r in ok)  # type: ignore[union-attr]
        discarded = sum(r.result.metrics.discarded for r in ok)  # type: ignore[union-attr]
        return [
            self.name,
            self.config.ollama_model,
            f"{len(ok)}/{len(self.runs)}",
            _fmt(stats["mediana"]),
            f"{_fmt(stats['min'])}-{_fmt(stats['max'])}",
            _fmt(plan_share, 0) + "%",
            _fmt(words["mediana"], 0),
            _fmt(aggregate(speeds)["mediana"] if speeds else None, 1),
            f"{calls / len(ok):.1f}",
            str(discarded),
        ]


def run_once(
    preset_name: str,
    subject: str,
    iteration: int,
    config: StoryConfig,
) -> BenchRun:
    """Una generazione, cronometrata; gli errori attesi non fermano il banco."""
    run = BenchRun(preset=preset_name, subject=subject, iteration=iteration, config=config)
    started = time.perf_counter()
    try:
        run.result = generate_story(subject, config)
    except ImaginariumError as exc:
        run.error = str(exc)
    finally:
        run.wall_s = time.perf_counter() - started
    return run


# ── Stampa dei dettagli ───────────────────────────────────────────────────


def show_prompts(config: StoryConfig, subject: str) -> None:
    """I prompt che *sarebbero* inviati con questa configurazione."""
    if config.two_pass:
        print_block("SYSTEM (passata 1: piano)", PLAN_SYSTEM_PROMPT)
        print_block("PROMPT (passata 1: piano)", build_plan_prompt(subject))
        print_block(
            "OPTIONS (passata 1)",
            json.dumps(
                build_options(
                    config,
                    num_predict=config.plan_num_predict,
                    temperature=config.plan_temperature,
                ),
                indent=2,
                ensure_ascii=False,
            ),
        )
        plan_for_preview = EXAMPLE_PLAN
        label = "PROMPT (passata 2: prosa — piano di esempio)"
    else:
        plan_for_preview = None
        label = "PROMPT (passata unica)"

    print_block("SYSTEM (prosa)", SYSTEM_PROMPT)
    print_block(label, build_story_prompt(subject, plan_for_preview, config))
    print_block(
        "OPTIONS (prosa)",
        json.dumps(build_options(config), indent=2, ensure_ascii=False),
    )


def show_run(run: BenchRun, *, show_prompt: bool, story_chars: int) -> None:
    """Il dettaglio fase per fase di una singola esecuzione."""
    head = f"{run.preset} · '{run.subject}' · run {run.iteration}"
    print(f"\n=== {head} " + "=" * max(0, 68 - len(head)))

    if run.error:
        print(f"  ERRORE dopo {run.wall_s:.1f}s: {run.error}")
        return

    assert run.result is not None
    metrics = run.result.metrics
    rows = []
    for call in metrics.calls:
        rows.append(
            [
                call.label,
                _fmt(call.wall_s),
                _fmt(call.load_duration_s, 2) if call.load_duration_s else "-",
                _fmt(call.prompt_eval_count),
                _fmt(call.eval_count),
                _fmt(call.eval_tokens_per_s, 1),
                call.done_reason or "-",
                call.outcome,
            ]
        )
    print_table(
        ["fase", "sec", "load", "tok.in", "tok.out", "tok/s", "stop", "esito"], rows
    )

    print(
        f"\n  totale {run.wall_s:.1f}s"
        f"  (piano {metrics.plan_wall_s:.1f}s · prosa {metrics.prose_wall_s:.1f}s)"
        f"  ·  {run.result.words} parole"
        f"  ·  {len(metrics.calls)} chiamate, {metrics.discarded} scartate"
        f"  ·  tentativi prosa: {run.result.attempts}"
    )

    if run.result.plan is not None:
        print_block("Piano narrativo", run.result.plan.as_briefing(run.subject))

    if show_prompt:
        print_block("PROMPT effettivo (prosa)", run.result.prompt)

    text = run.result.text
    if story_chars and len(text) > story_chars:
        text = text[:story_chars].rstrip() + " […]"
    print_block("Storia", text)


def show_comparison(outcomes: list[PresetOutcome], base: StoryConfig) -> None:
    """La tabella che serve davvero: una riga per configurazione."""
    print("\n\n" + "=" * 76)
    print("  CONFRONTO  (sec = tempo totale di generazione; mediana su tutte le run)")
    print("=" * 76)
    print_table(
        [
            "preset",
            "modello",
            "ok",
            "sec",
            "min-max",
            "piano%",
            "parole",
            "tok/s",
            "chiam.",
            "scarti",
        ],
        [o.summary_row() for o in outcomes],
    )

    print("\n  Configurazioni a confronto:")
    for outcome in outcomes:
        print(f"    {outcome.name}")
        print(f"      {describe(outcome.config, base)}")

    ranked = [o for o in outcomes if o.ok_runs]
    if len(ranked) > 1:
        ranked.sort(key=lambda o: aggregate([r.wall_s for r in o.ok_runs])["mediana"])
        fastest, slowest = ranked[0], ranked[-1]
        fast_s = aggregate([r.wall_s for r in fastest.ok_runs])["mediana"]
        slow_s = aggregate([r.wall_s for r in slowest.ok_runs])["mediana"]
        print(
            f"\n  Più veloce: {fastest.name} ({fast_s:.1f}s) — "
            f"{slow_s / fast_s:.1f}x rispetto a {slowest.name} ({slow_s:.1f}s)."
        )
        print(
            "  Il tempo non dice nulla sulla qualità: rileggi le storie prima di "
            "scegliere.\n  Quando una configurazione convince, ricopia i suoi valori in config.yaml."
        )


# ── Esportazione ──────────────────────────────────────────────────────────


def write_json(path: Path, outcomes: list[PresetOutcome], base: StoryConfig) -> None:
    payload = {
        "generato": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base": {"modello": base.ollama_model, "two_pass": base.two_pass},
        "preset": [
            {
                "nome": o.name,
                "diff_da_base": diff_fields(base, o.config),
                "run": [r.to_dict() for r in o.runs],
            }
            for o in outcomes
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  JSON completo (prompt inclusi) -> {path}")


def write_csv(path: Path, outcomes: list[PresetOutcome]) -> None:
    columns = [
        "preset",
        "modello",
        "subject",
        "iterazione",
        "ok",
        "wall_s",
        "plan_wall_s",
        "prose_wall_s",
        "chiamate",
        "scarti",
        "parole",
        "tentativi",
        "tok_in",
        "tok_out",
        "tok_s",
        "two_pass",
        "num_predict",
        "num_ctx",
        "target_words",
        "errore",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for outcome in outcomes:
            for run in outcome.runs:
                metrics = run.result.metrics if run.result else None
                writer.writerow(
                    {
                        "preset": outcome.name,
                        "modello": run.config.ollama_model,
                        "subject": run.subject,
                        "iterazione": run.iteration,
                        "ok": int(run.ok),
                        "wall_s": round(run.wall_s, 3),
                        "plan_wall_s": round(metrics.plan_wall_s, 3) if metrics else "",
                        "prose_wall_s": round(metrics.prose_wall_s, 3) if metrics else "",
                        "chiamate": len(metrics.calls) if metrics else "",
                        "scarti": metrics.discarded if metrics else "",
                        "parole": run.result.words if run.result else "",
                        "tentativi": run.result.attempts if run.result else "",
                        "tok_in": metrics.total_prompt_tokens if metrics else "",
                        "tok_out": metrics.total_eval_tokens if metrics else "",
                        "tok_s": (
                            round(metrics.eval_tokens_per_s, 2)
                            if metrics and metrics.eval_tokens_per_s
                            else ""
                        ),
                        "two_pass": int(run.config.two_pass),
                        "num_predict": run.config.num_predict,
                        "num_ctx": run.config.num_ctx,
                        "target_words": run.config.word_target,
                        "errore": run.error or "",
                    }
                )
    print(f"  CSV riassuntivo -> {path}")


# ── CLI ───────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Banco di prova della generazione del testo (nessun hardware richiesto)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Esempi:\n"
        "  python bench_story.py --list-presets\n"
        "  python bench_story.py --dry-run --show-prompt\n"
        "  python bench_story.py --preset baseline --preset fast --repeat 3\n"
        "  python bench_story.py --set two_pass=false --set num_predict=300\n"
        "  python bench_story.py --model gemma3:1b --all-classes --csv runtime/bench/1b.csv\n",
    )
    add_config_argument(parser)
    parser.add_argument(
        "--list-presets", action="store_true", help="Elenca i preset disponibili ed esce"
    )
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        metavar="NOME",
        help="Preset da provare; ripetibile per confrontarne più di uno (default: baseline)",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="CHIAVE=VALORE",
        help="Override su ogni preset, es. --set num_predict=300 --set two_pass=false",
    )
    parser.add_argument("--model", help="Scorciatoia per --set ollama_model=...")
    parser.add_argument(
        "--seed",
        type=int,
        help="Fissa il seed: generazioni riproducibili, confronto di qualità più pulito",
    )
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        metavar="TESTO",
        help=f"Soggetto della storia; ripetibile (default: '{DEFAULT_SUBJECT}')",
    )
    parser.add_argument(
        "--all-classes",
        action="store_true",
        help="Usa le 9 macro-classi del classificatore come soggetti",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, metavar="N", help="Esecuzioni per preset/soggetto"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra prompt e opzioni senza chiamare il modello (istantaneo)",
    )
    parser.add_argument(
        "--show-prompt", action="store_true", help="Stampa i prompt inviati al modello"
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Non pre-carica il modello: la prima run includerà il tempo di caricamento",
    )
    parser.add_argument(
        "--story-chars",
        type=int,
        default=600,
        metavar="N",
        help="Caratteri di storia da stampare (0 = tutta)",
    )
    parser.add_argument("--json", metavar="FILE", help="Salva l'esito completo in JSON")
    parser.add_argument("--csv", metavar="FILE", help="Salva il riassunto per run in CSV")
    return parser.parse_args()


def resolve_subjects(args: argparse.Namespace) -> list[str]:
    subjects = list(args.subject)
    if args.all_classes:
        subjects.extend(main_class_subjects())
    return subjects or [DEFAULT_SUBJECT]


def resolve_configs(args: argparse.Namespace, base: StoryConfig) -> list[tuple[str, StoryConfig]]:
    """(nome, configurazione) per ogni preset richiesto, con gli override applicati."""
    extra: dict[str, Any] = dict(parse_assignment(item) for item in args.set)
    if args.model:
        extra["ollama_model"] = args.model
    if args.seed is not None:
        extra["seed"] = args.seed

    names = args.preset or ["baseline"]
    configs: list[tuple[str, StoryConfig]] = []
    for name in names:
        preset = get_preset(name)
        config = apply_overrides(preset.apply(base), extra)
        label = preset.name
        if extra:
            label += " +override"
        configs.append((label, config))
    return configs


def main() -> None:
    args = parse_args()

    if args.list_presets:
        print("\nPreset disponibili (--preset NOME, ripetibile):\n")
        for name in preset_names():
            preset = get_preset(name)
            print(f"  {name}")
            print(f"      {preset.description}")
            if preset.overrides:
                shown = ", ".join(f"{k}={v}" for k, v in preset.overrides.items())
                print(f"      -> {shown}")
        print(
            "\nOgni preset parte da config.yaml e ne cambia solo i campi indicati.\n"
            "Con --set puoi sovrascrivere qualunque campo di story, es. --set num_ctx=1024\n"
        )
        return

    config = bootstrap(args.config)
    base = config.story

    try:
        configs = resolve_configs(args, base)
    except ConfigError as exc:
        print(f"\nConfigurazione non valida: {exc}\n", file=sys.stderr)
        raise SystemExit(2)

    subjects = resolve_subjects(args)

    if args.dry_run:
        for label, story_config in configs:
            print("\n" + "=" * 76)
            print(f"  {label}   [nessuna chiamata al modello]")
            print(f"  {describe(story_config, base)}")
            print("=" * 76)
            show_prompts(story_config, subjects[0])
        print(
            "\n  Dry-run: nessuna chiamata a Ollama. Togli --dry-run per misurare i tempi.\n"
        )
        return

    total = len(configs) * len(subjects) * args.repeat
    print(
        f"\n  {len(configs)} configurazione/i × {len(subjects)} soggetto/i × "
        f"{args.repeat} run = {total} generazioni."
    )
    if args.repeat == 1 and len(configs) > 1:
        print("  Suggerimento: con --repeat 3 la mediana diventa molto più affidabile.")

    outcomes: list[PresetOutcome] = []
    for label, story_config in configs:
        print("\n" + "=" * 76)
        print(f"  {label}")
        print(f"  {describe(story_config, base)}")
        print("=" * 76)

        if not args.no_warmup:
            print(f"  Warmup di {story_config.ollama_model}...", end=" ", flush=True)
            try:
                stats = warmup(story_config)
                loaded = stats.load_duration_s or 0.0
                print(f"pronto in {stats.wall_s:.1f}s (caricamento {loaded:.1f}s)")
            except ImaginariumError as exc:
                print(f"fallito: {exc}")

        outcome = PresetOutcome(name=label, config=story_config)
        for subject in subjects:
            for iteration in range(1, args.repeat + 1):
                run = run_once(label, subject, iteration, story_config)
                outcome.runs.append(run)
                show_run(run, show_prompt=args.show_prompt, story_chars=args.story_chars)
        outcomes.append(outcome)

    show_comparison(outcomes, base)

    if args.json:
        write_json(Path(args.json), outcomes, base)
    if args.csv:
        write_csv(Path(args.csv), outcomes)
    print()


if __name__ == "__main__":
    main()
