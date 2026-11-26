"""Bootstrap condiviso dagli entry point CLI (run_pipeline.py, test_*.py)."""

from __future__ import annotations

import argparse

from .config import AppConfig, load_config
from .logging_utils import setup_logging


def add_config_argument(parser: argparse.ArgumentParser) -> None:
    """Aggiunge l'opzione ``--config`` comune a tutti gli script."""
    parser.add_argument(
        "--config",
        default=None,
        help="Path a un config.yaml alternativo (default: quello nella root del progetto)",
    )


def bootstrap(config_path: str | None) -> AppConfig:
    """Carica la configurazione e inizializza il logging."""
    config = load_config(config_path)
    setup_logging(config.log_level)
    config.paths.photos_dir.mkdir(parents=True, exist_ok=True)
    config.paths.audio_dir.mkdir(parents=True, exist_ok=True)
    return config
