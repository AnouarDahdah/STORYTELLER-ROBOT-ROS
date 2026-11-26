"""Cattura foto dalla webcam via ``v4l2-ctl``.

Stessi parametri validati a mano nei test manuali::

    v4l2-ctl -d /dev/video0 \\
        --set-fmt-video=width=1920,height=1080,pixelformat=MJPG \\
        --stream-mmap \\
        --stream-count=1 \\
        --stream-to=test.jpg

Il modulo si limita a orchestrare il comando: nessuna libreria di visione
extra, per restare leggero sul Raspberry Pi 4.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .config import CameraConfig
from .exceptions import CameraError

logger = logging.getLogger(__name__)


def capture_photo(config: CameraConfig, output_path: Path | str) -> Path:
    """Scatta una foto e la salva in ``output_path``.

    Args:
        config: parametri di device/risoluzione/formato.
        output_path: dove salvare il JPEG (le cartelle intermedie vengono create).

    Raises:
        CameraError: ``v4l2-ctl`` non installato, comando fallito, timeout,
            o nessun file prodotto (device non collegato/occupato).
    """
    if shutil.which("v4l2-ctl") is None:
        raise CameraError(
            "'v4l2-ctl' non trovato nel PATH. Installa v4l-utils: sudo apt install v4l-utils"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = f"width={config.width},height={config.height},pixelformat={config.pixelformat}"
    cmd = [
        "v4l2-ctl",
        "-d", config.device,
        f"--set-fmt-video={fmt}",
        "--stream-mmap",
        "--stream-count=1",
        f"--stream-to={output_path}",
    ]
    logger.info("Scatto foto (%s): %s", config.device, " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=config.timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise CameraError(
            f"v4l2-ctl non ha risposto entro {config.timeout_s}s. "
            f"Verifica che {config.device} sia collegato e non occupato da un altro processo."
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CameraError(f"v4l2-ctl fallito (device {config.device}): {detail}")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise CameraError(
            f"Nessuna immagine valida prodotta in {output_path}. "
            f"Controlla che {config.device} esista (ls /dev/video*) e supporti MJPG "
            f"alla risoluzione {config.width}x{config.height} (v4l2-ctl --list-formats-ext -d {config.device})."
        )

    logger.info("Foto salvata: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path
