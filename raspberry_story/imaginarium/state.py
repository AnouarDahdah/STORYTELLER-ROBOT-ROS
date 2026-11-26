"""Stato "ultima storia": il ponte fra il comando 2 e il comando 3.

Il comando 3 deve tradurre "la storia che ha fatto il comando 2" nelle altre
due lingue — ma senza rigenerare né tradurre nulla a runtime, prendendo la
traduzione già presente nel pool allo stesso indice (vedi
``story_cache.MultiLanguageStoryCache``). Per farlo deve sapere *quale*
storia è stata raccontata: soggetto, indice nel pool, lingua. Questo modulo
salva quei tre valori su disco dopo il comando 2 e li rilegge nel comando 3.

File singolo, sovrascritto a ogni comando 2: non serve una cronologia, solo
"l'ultima" storia raccontata.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .exceptions import ImaginariumError

logger = logging.getLogger(__name__)


class StateError(ImaginariumError):
    """Stato mancante, illeggibile o incompleto."""


@dataclass(frozen=True)
class LastStory:
    """Cosa serve al comando 3 per ritrovare la storia del comando 2."""

    pool_key: str
    index: int
    lang: str
    main_class: str
    sub_class: str | None
    saved_at: str

    @classmethod
    def create(
        cls, pool_key: str, index: int, lang: str, main_class: str, sub_class: str | None
    ) -> "LastStory":
        return cls(
            pool_key=pool_key,
            index=index,
            lang=lang,
            main_class=main_class,
            sub_class=sub_class,
            saved_at=_dt.datetime.now().isoformat(timespec="seconds"),
        )

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Stato salvato: %s (%s)", path, self.pool_key)

    @classmethod
    def load(cls, path: Path | str) -> "LastStory":
        """Carica l'ultima storia salvata.

        Raises:
            StateError: nessun comando 2 è mai stato eseguito (file assente)
                o il file è corrotto/incompleto.
        """
        path = Path(path)
        if not path.is_file():
            raise StateError(
                f"Nessuna storia salvata ({path} non esiste). "
                "Esegui prima il comando 2 (racconta una storia in una lingua)."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StateError(f"Stato illeggibile ({path}): {exc}") from exc
        try:
            return cls(
                pool_key=str(data["pool_key"]),
                index=int(data["index"]),
                lang=str(data["lang"]),
                main_class=str(data["main_class"]),
                sub_class=data.get("sub_class"),
                saved_at=str(data.get("saved_at", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError(f"Stato incompleto ({path}): {exc}") from exc
