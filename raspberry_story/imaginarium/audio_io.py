"""Registrazione e riproduzione audio via ALSA (``arecord``/``aplay``).

Stessi device validati a mano nei test manuali::

    arecord -D hw:3,0 -c 1 -f S16_LE -r 48000 -d 5 test.wav   # microfono
    aplay   -D hw:2,0 test.wav                                # cuffie

Come per la fotocamera, si orchestrano i comandi di sistema invece di usare
binding audio (pyaudio/sounddevice): meno dipendenze da compilare su ARM,
e gli stessi comandi già verificati sull'hardware restano la fonte di verità.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .config import AudioConfig
from .exceptions import AudioError

logger = logging.getLogger(__name__)


def record_audio(
    config: AudioConfig,
    output_path: Path | str,
    duration_s: float | None = None,
) -> Path:
    """Registra dal microfono e salva un WAV.

    Args:
        config: device/canali/formato/sample rate.
        output_path: dove salvare il WAV.
        duration_s: durata in secondi; se ``None`` usa ``config.record_seconds``.

    Raises:
        AudioError: ``arecord`` non installato, comando fallito o timeout.
    """
    if shutil.which("arecord") is None:
        raise AudioError(
            "'arecord' non trovato nel PATH. Installa alsa-utils: sudo apt install alsa-utils"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = duration_s if duration_s is not None else config.record_seconds

    cmd = [
        "arecord",
        "-D", config.record_device,
        "-c", str(config.channels),
        "-f", config.format,
        "-r", str(config.rate),
        "-d", str(duration),
        str(output_path),
    ]
    logger.info("Registrazione audio (%ss, device %s): %s", duration, config.record_device, " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
    except subprocess.TimeoutExpired as exc:
        raise AudioError(
            f"arecord non ha risposto entro {duration + 10}s (device {config.record_device})."
        ) from exc

    if result.returncode != 0:
        raise AudioError(f"arecord fallito (device {config.record_device}): {result.stderr.strip()}")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise AudioError(f"Nessun file audio valido prodotto in {output_path}")

    logger.info("Audio registrato: %s", output_path)
    return output_path


def play_audio(config: AudioConfig, input_path: Path | str) -> None:
    """Riproduce un file audio sulle cuffie/altoparlante configurati.

    Raises:
        AudioError: ``aplay`` non installato, file mancante o riproduzione fallita.
    """
    if shutil.which("aplay") is None:
        raise AudioError(
            "'aplay' non trovato nel PATH. Installa alsa-utils: sudo apt install alsa-utils"
        )

    input_path = Path(input_path)
    if not input_path.is_file():
        raise AudioError(f"File audio non trovato: {input_path}")

    cmd = ["aplay", "-D", config.playback_device, str(input_path)]
    logger.info("Riproduzione (device %s): %s", config.playback_device, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioError(f"aplay fallito (device {config.playback_device}): {result.stderr.strip()}")
