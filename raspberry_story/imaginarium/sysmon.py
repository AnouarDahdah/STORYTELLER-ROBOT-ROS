"""Statistiche di sistema (CPU/RAM/temperatura) durante un test dei comandi.

Pensato per girare in un secondo terminale SSH mentre su un altro si lancia
``run_button.py``: risponde alla domanda "quanto costa questo comando al Pi",
la stessa cosa che ``bench_story.py``/``--stats`` misurano per i tempi di
fase, ma per le risorse. Nessuna dipendenza dall'hardware della pipeline
(camera/audio/TFLite): solo ``psutil`` più, quando disponibile, ``vcgencmd``
(temperatura della SoC, specifico Raspberry Pi).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


@dataclass(frozen=True)
class SystemSample:
    """Una lettura istantanea delle risorse di sistema."""

    cpu_percent: float  # media su tutti i core, vedi Sampler
    cpu_per_core: tuple[float, ...]
    mem_used_mb: float
    mem_total_mb: float
    mem_percent: float
    swap_used_mb: float
    swap_percent: float
    cpu_temp_c: float | None

    @property
    def mem_line(self) -> str:
        return f"{self.mem_used_mb:6.0f}/{self.mem_total_mb:.0f} MB ({self.mem_percent:4.1f}%)"

    def to_row(self) -> dict[str, float | str]:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "mem_used_mb": round(self.mem_used_mb, 1),
            "mem_percent": round(self.mem_percent, 1),
            "swap_used_mb": round(self.swap_used_mb, 1),
            "swap_percent": round(self.swap_percent, 1),
            "cpu_temp_c": round(self.cpu_temp_c, 1) if self.cpu_temp_c is not None else "",
        }


def read_cpu_temp() -> float | None:
    """Temperatura della SoC in °C, o ``None`` se non disponibile (non-Pi)."""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and "=" in result.stdout:
            # "temp=48.3'C\n"
            value = result.stdout.split("=", 1)[1].split("'")[0]
            return float(value)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    try:
        raw = _THERMAL_ZONE.read_text().strip()
        return float(raw) / 1000.0
    except (OSError, ValueError):
        return None


class Sampler:
    """Wrapper sottile su ``psutil`` per una singola lettura comparabile.

    ``psutil.cpu_percent`` richiede un intervallo di misura per essere
    significativo (la prima chiamata senza attesa ritorna sempre 0.0): lo
    stesso ``interval`` è quindi l'unico argomento, ed è anche l'intervallo
    di refresh del monitor.
    """

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval

    def sample(self) -> SystemSample:
        cpu_per_core = tuple(psutil.cpu_percent(interval=self.interval, percpu=True))
        cpu_percent = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0.0
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return SystemSample(
            cpu_percent=cpu_percent,
            cpu_per_core=cpu_per_core,
            mem_used_mb=vm.used / 1_048_576,
            mem_total_mb=vm.total / 1_048_576,
            mem_percent=vm.percent,
            swap_used_mb=swap.used / 1_048_576,
            swap_percent=swap.percent,
            cpu_temp_c=read_cpu_temp(),
        )
