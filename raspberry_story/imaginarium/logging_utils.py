"""Setup centralizzato del logging.

Tutti i moduli usano ``logging.getLogger(__name__)``; ogni CLI chiama
:func:`setup_logging` una volta sola all'avvio.
"""

from __future__ import annotations

import logging


def setup_logging(level: str = "INFO") -> None:
    """Configura il root logger con un formato uniforme.

    Args:
        level: nome del livello (``DEBUG``, ``INFO``, ``WARNING``, ...).
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
