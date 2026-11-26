"""CLI — monitor di CPU/RAM/temperatura, da tenere aperto mentre si testano i comandi.

Uso:
    python monitor_stats.py                          # refresh ogni 1s, a schermo
    python monitor_stats.py --interval 0.5            # più reattivo
    python monitor_stats.py --csv runtime/bench/stats.csv   # logga anche su file
    python monitor_stats.py --count 30                # si ferma dopo 30 letture

Pensato per un secondo terminale SSH, aperto mentre nel primo si lancia
``python run_button.py 1|2|3``: correla i tempi per fase che stampa
``run_button.py --stats`` con quello che succede a CPU/RAM/temperatura nello
stesso momento — utile per capire se un comando va lento per il classificatore
(picco CPU breve) o perché il sistema sta andando in swap (RAM piena, disco).

Per un uso puramente interattivo, senza log su file, ``htop``/``btop``
(``sudo apt install btop``) danno la stessa informazione senza scrivere
nulla — vedi docs/07_monitoraggio_risorse.md.
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from imaginarium.sysmon import Sampler, SystemSample

_HEADER = f"{'ora':<10} {'CPU%':>6} {'per-core':<28} {'RAM':<24} {'SWAP%':>6} {'temp°C':>7}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor CPU/RAM/temperatura per i test dei comandi")
    parser.add_argument("--interval", type=float, default=1.0, help="Secondi fra una lettura e l'altra (default: 1.0)")
    parser.add_argument("--count", type=int, default=None, help="Numero di letture (default: infinito, Ctrl+C per fermare)")
    parser.add_argument("--csv", type=Path, default=None, help="Logga anche su questo file CSV")
    return parser.parse_args()


def _format_row(sample: SystemSample) -> str:
    now = time.strftime("%H:%M:%S")
    per_core = " ".join(f"{v:4.0f}" for v in sample.cpu_per_core)
    temp = f"{sample.cpu_temp_c:5.1f}" if sample.cpu_temp_c is not None else "  n/d"
    return (
        f"{now:<10} {sample.cpu_percent:5.1f}% {per_core:<28} "
        f"{sample.mem_line:<24} {sample.swap_percent:5.1f}% {temp:>7}"
    )


def main() -> None:
    args = parse_args()
    sampler = Sampler(interval=args.interval)

    csv_writer = None
    csv_file = None
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        is_new = not args.csv.exists()
        csv_file = args.csv.open("a", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(
            csv_file,
            fieldnames=["timestamp", "cpu_percent", "mem_used_mb", "mem_percent", "swap_used_mb", "swap_percent", "cpu_temp_c"],
        )
        if is_new:
            csv_writer.writeheader()

    print(_HEADER)
    print("-" * len(_HEADER))

    count = 0
    try:
        while args.count is None or count < args.count:
            sample = sampler.sample()
            print(_format_row(sample))
            if csv_writer:
                row = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **sample.to_row()}
                csv_writer.writerow(row)
                csv_file.flush()
            count += 1
    except KeyboardInterrupt:
        print("\nFermato.")
    finally:
        if csv_file:
            csv_file.close()


if __name__ == "__main__":
    main()
