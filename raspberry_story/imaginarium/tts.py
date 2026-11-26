"""Sintesi vocale della storia con Piper TTS.

Piper gira bene su CPU ARM (Raspberry Pi 4), funziona offline e ha voci
italiane pronte all'uso. Si usa via CLI (pacchetto pip ``piper-tts``, che
installa l'eseguibile ``piper``) invece che via libreria Python, per
restare disaccoppiati dalla sua API interna:

    echo "testo" | piper --model it_IT-paola-medium.onnx --output_file out.wav

I file del modello voce (``.onnx`` + ``.onnx.json``) NON sono inclusi in
questo repo (sono alcune decine di MB): vanno scaricati una volta sola sul
Raspberry Pi (vedi README, sezione "Voce Piper") e il loro path va indicato
in ``config.yaml`` -> ``tts.voice_model`` / ``tts.voice_config``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .config import TTSConfig
from .exceptions import TTSError

logger = logging.getLogger(__name__)


def _resolve_binary(piper_binary: str) -> str:
    if shutil.which(piper_binary):
        return piper_binary
    if Path(piper_binary).is_file():
        return piper_binary
    raise TTSError(
        f"Eseguibile Piper non trovato: '{piper_binary}'. Installa con "
        "'pip install piper-tts' oppure indica il path assoluto in config.yaml (tts.piper_binary)."
    )


def synthesize(text: str, output_path: Path | str, config: TTSConfig) -> Path:
    """Sintetizza ``text`` e salva un WAV in ``output_path``.

    Args:
        text: testo da leggere (tipicamente la storia generata).
        output_path: dove salvare il WAV.
        config: engine/voce/parametri prosodici.

    Raises:
        TTSError: motore non supportato, voce mancante, Piper fallito o
            timeout.
    """
    if config.engine != "piper":
        raise TTSError(f"Motore TTS non supportato: '{config.engine}' (solo 'piper' per ora)")

    if not text.strip():
        raise TTSError("Testo vuoto: niente da sintetizzare")

    if not Path(config.voice_model).is_file():
        raise TTSError(
            f"Voce Piper non trovata: {config.voice_model}. "
            "Scaricala (vedi README, sezione 'Voce Piper') e verifica il path in config.yaml."
        )

    binary = _resolve_binary(config.piper_binary)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [binary, "--model", str(config.voice_model), "--output_file", str(output_path)]
    if config.voice_config and Path(config.voice_config).is_file():
        cmd += ["--config", str(config.voice_config)]
    if config.length_scale != 1.0:
        cmd += ["--length_scale", str(config.length_scale)]
    if config.noise_scale != 0.667:
        cmd += ["--noise_scale", str(config.noise_scale)]
    if config.noise_w != 0.8:
        cmd += ["--noise_w", str(config.noise_w)]

    logger.info("Sintesi vocale (%d caratteri) -> %s", len(text), output_path)
    try:
        result = subprocess.run(
            cmd, input=text, capture_output=True, text=True, timeout=config.timeout_s
        )
    except subprocess.TimeoutExpired as exc:
        raise TTSError(f"Piper non ha risposto entro {config.timeout_s}s") from exc

    if result.returncode != 0:
        raise TTSError(f"Piper fallito: {result.stderr.strip() or result.stdout.strip()}")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise TTSError(f"Piper non ha prodotto un file audio valido: {output_path}")

    logger.info("Audio sintetizzato: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path
