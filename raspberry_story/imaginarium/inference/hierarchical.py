"""Classificazione gerarchica a due livelli (porting da ``toyclf.inference.hierarchical``).

Flusso::

    immagine -> classificatore principale -> classe principale
             -> sottoclassificatore della classe -> sottoclasse

I sottoclassificatori vengono caricati pigramente (solo quando la loro
classe principale viene effettivamente predetta) e poi tenuti in cache.
Le classi con una sola sottoclasse non hanno modello: la sottoclasse è
implicita, con confidenza 1.0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from ..config import AppConfig
from .predictor import ImagePredictor
from .registry import HierarchySpec, ModelRegistry, SubclassifierSpec

logger = logging.getLogger(__name__)


class SupportsPredict(Protocol):
    """Interfaccia minima richiesta a un predictor (consente fake nei test)."""

    def predict(self, image_path: Path | str) -> tuple[str, float]: ...

    def top_k(self, image_path: Path | str, k: int = 3) -> list[tuple[str, float]]: ...


PredictorFactory = Callable[[Path, Sequence[str], tuple[int, int]], SupportsPredict]


@dataclass(frozen=True)
class HierarchicalPrediction:
    """Risultato della classificazione a due livelli.

    ``main_top``/``sub_top`` contengono le classi più probabili di ogni
    livello in ordine decrescente; il primo elemento coincide con
    ``main_class``/``sub_class``.
    """

    main_class: str
    main_confidence: float
    sub_class: str | None
    sub_confidence: float | None
    main_top: tuple[tuple[str, float], ...] = ()
    sub_top: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_class": self.main_class,
            "sub_class": self.sub_class,
            "confidence": {
                "main": round(self.main_confidence, 4),
                "sub": round(self.sub_confidence, 4) if self.sub_confidence is not None else None,
            },
            "top_main": [
                {"class": label, "confidence": round(conf, 4)} for label, conf in self.main_top
            ],
            "top_sub": [
                {"class": label, "confidence": round(conf, 4)} for label, conf in self.sub_top
            ],
        }


class HierarchicalClassifier:
    """Instrada un'immagine attraverso i due livelli di classificazione."""

    def __init__(
        self,
        hierarchy: HierarchySpec,
        registry: ModelRegistry,
        predictor_factory: PredictorFactory = ImagePredictor,
    ) -> None:
        self._hierarchy = hierarchy
        self._registry = registry
        self._factory = predictor_factory
        self._main_predictor: SupportsPredict | None = None
        self._sub_predictors: dict[str, SupportsPredict] = {}

    @classmethod
    def from_config(cls, config: AppConfig) -> "HierarchicalClassifier":
        """Costruisce il classificatore leggendo ``hierarchy.json`` dai modelli."""
        registry = ModelRegistry(config.paths.models_root)
        return cls(hierarchy=registry.load_hierarchy(), registry=registry)

    # ── Accesso ai predictor (lazy, con cache) ────────────────────────────

    @property
    def main_predictor(self) -> SupportsPredict:
        if self._main_predictor is None:
            self._main_predictor = self._factory(
                self._registry.resolve(self._hierarchy.main_model_relpath),
                self._hierarchy.main_labels,
                self._hierarchy.img_size,
            )
        return self._main_predictor

    def subclass_predictor(self, main_class: str) -> SupportsPredict | None:
        """Predictor delle sottoclassi di ``main_class``; None se non c'è modello."""
        spec = self._spec_for(main_class)
        if spec is None or not spec.has_model:
            return None
        if main_class not in self._sub_predictors:
            self._sub_predictors[main_class] = self._factory(
                self._registry.resolve(spec.model_relpath),
                spec.labels,
                self._hierarchy.img_size,
            )
        return self._sub_predictors[main_class]

    def _spec_for(self, main_class: str) -> SubclassifierSpec | None:
        spec = self._hierarchy.subclassifiers.get(main_class)
        if spec is None:
            logger.warning("Nessun sottoclassificatore registrato per '%s'", main_class)
        return spec

    # ── API principale ────────────────────────────────────────────────────

    def classify(self, image_path: Path | str, top_k: int = 3) -> HierarchicalPrediction:
        """Classifica un'immagine restituendo classe principale e sottoclasse.

        Args:
            image_path: immagine da classificare.
            top_k: quante classi riportare in ``main_top``/``sub_top``.
        """
        main_top = tuple(self.main_predictor.top_k(image_path, top_k))
        main_class, main_confidence = main_top[0]

        sub_top: tuple[tuple[str, float], ...] = ()
        spec = self._spec_for(main_class)
        if spec is not None and spec.labels:
            if spec.is_trivial:
                # Unica sottoclasse possibile: implicita, nessun modello da interrogare.
                sub_top = ((spec.labels[0], 1.0),)
            elif spec.has_model:
                sub_top = tuple(self.subclass_predictor(main_class).top_k(image_path, top_k))
            else:
                logger.warning(
                    "Sottoclassificatore di '%s' non addestrato: sub_class assente", main_class
                )

        result = HierarchicalPrediction(
            main_class=main_class,
            main_confidence=main_confidence,
            sub_class=sub_top[0][0] if sub_top else None,
            sub_confidence=sub_top[0][1] if sub_top else None,
            main_top=main_top,
            sub_top=sub_top,
        )
        logger.debug("Predizione %s: %s", image_path, result.to_dict())
        return result
