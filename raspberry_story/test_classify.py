"""CLI — test isolato della classificazione TFLite (equivalente di infer.py nel dev repo).

Uso:
    python test_classify.py --image foto.jpg
    python test_classify.py --image foto.jpg --json
"""

from __future__ import annotations

import argparse
import json
import sys

from imaginarium.cli import add_config_argument, bootstrap
from imaginarium.exceptions import ImaginariumError
from imaginarium.inference import HierarchicalClassifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classificazione gerarchica (TFLite) su un'immagine")
    add_config_argument(parser)
    parser.add_argument("--image", required=True, help="Path dell'immagine")
    parser.add_argument("--top-k", type=int, default=3, help="Quante classi mostrare per livello")
    parser.add_argument("--json", action="store_true", help="Stampa il risultato come JSON")
    return parser.parse_args()


def format_top(entries: list[dict]) -> str:
    if not entries:
        return "-"
    return " | ".join(f"{e['class']} {e['confidence'] * 100:.1f}%" for e in entries)


def main() -> None:
    args = parse_args()
    config = bootstrap(args.config)

    try:
        classifier = HierarchicalClassifier.from_config(config)
        result = classifier.classify(args.image, top_k=args.top_k)
    except ImaginariumError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        raise SystemExit(1)

    data = result.to_dict()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    sub = data["sub_class"] or "(nessuna sottoclasse)"
    sub_conf = data["confidence"]["sub"]
    sub_pct = f"{sub_conf * 100:.1f}%" if sub_conf is not None else "-"
    print(f"\n{args.image}")
    print(f"  classe principale : {data['main_class']}  ({data['confidence']['main'] * 100:.1f}%)")
    print(f"  sottoclasse       : {sub}  ({sub_pct})")
    print(f"  top classi        : {format_top(data['top_main'])}")
    print(f"  top sottoclassi   : {format_top(data['top_sub'])}")


if __name__ == "__main__":
    main()
