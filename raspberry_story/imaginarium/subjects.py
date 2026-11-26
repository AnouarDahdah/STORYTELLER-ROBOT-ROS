"""Risoluzione soggetto: da una classificazione a una chiave del pool di storie.

Fa da ponte fra due tassonomie diverse (vedi ``tools/build_subject_map.py``
per il perché): le etichette grezze del classificatore (cartelle del
dataset, es. ``tartarughe_ninja``) e le chiavi del pool di storie
pre-generate (es. ``"ninja turtle"``). La mappa è precalcolata in
``models/subject_map.json``; questo modulo si limita ad applicarla con la
stessa logica di soglie già validata in ``story.py.choose_subject`` — non la
duplica per caso, la soglia sottoclasse 50% / classe principale 55% è
esattamente quella richiesta per il comportamento dei comandi 1 e 2.

Nessuna dipendenza da Ollama: questo è il percorso usato a runtime dai
comandi (``commands.py``), che pescano sempre dal pool.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .exceptions import ImaginariumError

logger = logging.getLogger(__name__)

Tier = Literal["sottoclasse", "classe_principale", "generico"]


class SubjectMapError(ImaginariumError):
    """``subject_map.json`` mancante, illeggibile o incompleto."""


@dataclass(frozen=True)
class SubjectMap:
    """La mappa precalcolata da ``tools/build_subject_map.py``."""

    subclass_to_pool_key: dict[str, str]  # "classe_principale/sottoclasse_grezza" -> chiave pool
    main_class_to_bucket: dict[str, str]  # classe_principale -> chiave pool generica
    final_fallback_subject: str

    @classmethod
    def load(cls, path: Path | str) -> "SubjectMap":
        path = Path(path)
        if not path.is_file():
            raise SubjectMapError(
                f"Mappa soggetti non trovata: {path}. "
                "Generala con 'python tools/build_subject_map.py'."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SubjectMapError(f"Mappa soggetti illeggibile ({path}): {exc}") from exc

        try:
            subclass_to_pool_key = {
                key: entry["pool_key"]
                for key, entry in data["subclass_to_story"].items()
                if entry.get("pool_key")
            }
            main_class_to_bucket = dict(data["main_class_to_legacy_bucket"])
            final_fallback_subject = str(data["final_fallback_subject"])
        except KeyError as exc:
            raise SubjectMapError(f"Mappa soggetti incompleta ({path}): manca {exc}") from exc

        return cls(
            subclass_to_pool_key=subclass_to_pool_key,
            main_class_to_bucket=main_class_to_bucket,
            final_fallback_subject=final_fallback_subject,
        )

    def pool_key_for_subclass(self, main_class: str, sub_class: str) -> str | None:
        return self.subclass_to_pool_key.get(f"{main_class}/{sub_class}")

    def pool_key_for_main_class(self, main_class: str) -> str | None:
        return self.main_class_to_bucket.get(main_class)


@dataclass(frozen=True)
class SubjectResolution:
    """Il soggetto scelto per una classificazione, con la motivazione."""

    pool_key: str
    tier: Tier
    reason: str


def resolve_subject(
    *,
    main_class: str,
    main_confidence: float,
    sub_class: str | None,
    sub_confidence: float | None,
    subject_map: SubjectMap,
    min_main_confidence: float,
    min_sub_confidence: float,
) -> SubjectResolution:
    """Sceglie la chiave del pool da cui pescare la storia.

    Stessa gerarchia di decisione di ``story.choose_subject``:

    1. Classe principale incerta (``main_confidence < min_main_confidence``):
       soggetto completamente generico.
    2. Sottoclasse nota e sufficientemente sicura
       (``sub_confidence >= min_sub_confidence``): storia specifica se il
       pool la copre, altrimenti si scende comunque al bucket della classe
       principale (sottoclasse riconosciuta ma senza storia dedicata).
    3. Altrimenti: bucket della classe principale.

    Il bucket di una classe principale copre sempre (vedi
    ``build_subject_map.MAIN_CLASS_TO_LEGACY_BUCKET``, validato contro il
    pool alla generazione della mappa): non può fallire silenziosamente come
    accadeva con il vecchio fallback ``"giocattolo"``.
    """
    if main_confidence < min_main_confidence:
        return SubjectResolution(
            pool_key=subject_map.final_fallback_subject,
            tier="generico",
            reason=f"confidenza classe principale bassa ({main_confidence:.2f})",
        )

    if sub_class and (sub_confidence is None or sub_confidence >= min_sub_confidence):
        pool_key = subject_map.pool_key_for_subclass(main_class, sub_class)
        if pool_key is not None:
            return SubjectResolution(
                pool_key=pool_key,
                tier="sottoclasse",
                reason=f"sottoclasse '{sub_class}' riconosciuta con {sub_confidence or 1.0:.2f}",
            )
        logger.info(
            "Sottoclasse '%s' riconosciuta ma senza storia dedicata nel pool: uso la classe principale",
            sub_class,
        )

    bucket = subject_map.pool_key_for_main_class(main_class)
    if bucket is None:
        logger.warning(
            "Nessun bucket per la classe principale '%s': uso il fallback finale", main_class
        )
        bucket = subject_map.final_fallback_subject
        tier: Tier = "generico"
    else:
        tier = "classe_principale"

    return SubjectResolution(
        pool_key=bucket,
        tier=tier,
        reason=f"classe principale '{main_class}' (sottoclasse incerta o non coperta)",
    )
