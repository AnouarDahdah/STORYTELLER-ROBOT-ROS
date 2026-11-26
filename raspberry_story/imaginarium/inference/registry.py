"""Lettura della gerarchia dei modelli (``models/hierarchy.json``).

Stesso contratto usato in fase di training/sviluppo (repo ``toy_classifier``,
``toyclf/models/registry.py``): l'inferenza legge **solo** questo file, mai
il dataset, quindi ``models/`` è autosufficiente e deployabile da sola.

La differenza rispetto al repo di sviluppo è che qui i path dei modelli
puntano a ``model.tflite`` invece che a ``model.keras`` — la riscrittura
avviene una volta sola, sul dev PC, con ``sync_to_production.py``. Questo
modulo è quindi puramente di lettura (nessun ``write_hierarchy``/training).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..exceptions import ModelNotFoundError

logger = logging.getLogger(__name__)

LABELS_FILENAME = "labels.json"
HIERARCHY_FILENAME = "hierarchy.json"


@dataclass(frozen=True)
class SubclassifierSpec:
    """Metadati del classificatore di sottoclassi di una classe principale."""

    labels: tuple[str, ...]
    model_relpath: str | None  # relativo alla root dei modelli; None = nessun modello

    @property
    def is_trivial(self) -> bool:
        """True se non serve un modello (0 o 1 sottoclasse: risposta implicita)."""
        return len(self.labels) <= 1

    @property
    def has_model(self) -> bool:
        return self.model_relpath is not None


@dataclass(frozen=True)
class HierarchySpec:
    """Descrizione completa della gerarchia di modelli."""

    main_labels: tuple[str, ...]
    main_model_relpath: str
    img_size: tuple[int, int]
    subclassifiers: Mapping[str, SubclassifierSpec]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HierarchySpec":
        return cls(
            main_labels=tuple(data["main_labels"]),
            main_model_relpath=data["main_model"],
            img_size=tuple(data["img_size"]),
            subclassifiers={
                name: SubclassifierSpec(labels=tuple(entry["labels"]), model_relpath=entry["model"])
                for name, entry in data["subclassifiers"].items()
            },
        )


class ModelRegistry:
    """Unico punto che conosce dove vivono modelli e metadati su disco."""

    def __init__(self, models_root: Path) -> None:
        self._root = models_root

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, relpath: str) -> Path:
        """Path assoluto a partire da un path relativo alla root dei modelli."""
        return self._root / relpath

    @staticmethod
    def read_labels(directory: Path) -> tuple[str, ...]:
        path = directory / LABELS_FILENAME
        if not path.is_file():
            raise ModelNotFoundError(f"File labels non trovato: {path}")
        return tuple(json.loads(path.read_text(encoding="utf-8")))

    @property
    def hierarchy_path(self) -> Path:
        return self._root / HIERARCHY_FILENAME

    def load_hierarchy(self) -> HierarchySpec:
        if not self.hierarchy_path.is_file():
            raise ModelNotFoundError(
                f"Gerarchia non trovata: {self.hierarchy_path}. "
                "Esegui prima 'sync_to_production.py' nel repo toy_classifier per popolare 'models/'."
            )
        return HierarchySpec.from_dict(json.loads(self.hierarchy_path.read_text(encoding="utf-8")))
