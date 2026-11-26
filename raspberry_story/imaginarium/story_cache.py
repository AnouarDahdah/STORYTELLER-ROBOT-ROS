"""Pool di storie pre-generate: aggira la latenza invece di ridurla.

Le classi riconosciute dal classificatore sono un insieme **chiuso e piccolo**
(9 macro-classi più le sottoclassi note). Niente obbliga a generare la storia
mentre il bambino aspetta davanti al giocattolo: si può generare in anticipo,
su una macchina più potente, un pool di storie per ciascun soggetto, copiarlo
sul Pi e a runtime limitarsi a pescarne una.

È l'unica leva che elimina il problema alla radice invece di ridurlo: il
tempo di "generazione" scende da decine di secondi a millisecondi, perché non
c'è più nessuna inferenza. Il prezzo non è tecnico ma **di prodotto**: le
storie non sono più diverse a ogni scatto, e questo è un giocattolo su cui un
bambino tornerà più volte. Il pool va quindi dimensionato di conseguenza
(``pregenerate_stories.py --per-subject``), e la personalizzazione del nome
del protagonista serve a far sembrare meno identiche due estrazioni dello
stesso testo.

Il modulo non parla con Ollama: legge un file JSON e sceglie. La generazione
del pool sta in ``pregenerate_stories.py``, che invece usa ``story.py``.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .config import CacheConfig
from .exceptions import ImaginariumError
from .story import StoryPlan, StoryResult, word_count

logger = logging.getLogger(__name__)

# Nomi usati per personalizzare il protagonista quando si ripesca una storia
# già vista: variare il nome è il cambiamento più economico che rende due
# estrazioni dello stesso testo percepibilmente diverse.
_NAMES_M = ("Nino", "Bubo", "Rullo", "Pippo", "Tobia", "Gigi", "Pico", "Momo")
_NAMES_F = ("Nina", "Bea", "Lilla", "Stella", "Gigia", "Pina", "Momo", "Tilly")


class StoryCacheError(ImaginariumError):
    """Il pool non esiste, non è leggibile o non contiene nulla di utile."""


@dataclass(frozen=True)
class CachedStory:
    """Una storia del pool, con il piano che l'ha prodotta."""

    text: str
    subject: str
    plan: StoryPlan | None = None
    model: str = ""

    @classmethod
    def from_dict(cls, subject: str, data: dict[str, Any]) -> "CachedStory":
        plan_data = data.get("plan")
        return cls(
            text=str(data["text"]),
            subject=subject,
            plan=StoryPlan(**plan_data) if plan_data else None,
            model=str(data.get("model", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "plan": self.plan.to_dict() if self.plan else None,
            "model": self.model,
            "words": word_count(self.text),
        }

    def personalized(self, rng: random.Random) -> "CachedStory":
        """La stessa storia con un nome di protagonista diverso.

        Sostituisce solo occorrenze di parola intera del nome originale: senza
        il piano non si saprebbe *quale* parola è il nome, quindi le storie
        prive di piano tornano immutate.
        """
        if self.plan is None or not self.plan.nome:
            return self
        pool = _NAMES_F if self.plan.genere.lower().startswith("f") else _NAMES_M
        candidates = [n for n in pool if n.lower() != self.plan.nome.lower()]
        if not candidates:
            return self
        new_name = rng.choice(candidates)
        text = _replace_word(self.text, self.plan.nome, new_name)
        return CachedStory(
            text=text,
            subject=self.subject,
            plan=StoryPlan(**{**self.plan.to_dict(), "nome": new_name}),
            model=self.model,
        )

    def as_result(self) -> StoryResult:
        """La stessa forma che restituisce ``generate_story``.

        La pipeline non deve sapere se la storia arriva dal modello o dal
        pool: ``metrics`` resta vuota, ed è proprio quello il segnale che
        nessuna chiamata al modello è stata fatta.
        """
        return StoryResult(text=self.text, subject=self.subject, plan=self.plan, attempts=0)


def _replace_word(text: str, old: str, new: str) -> str:
    """Sostituzione di parola intera, senza regex sui caratteri del nome."""
    import re

    return re.sub(rf"\b{re.escape(old)}\b", new, text)


def _renamed(story: CachedStory, new_name: str) -> CachedStory:
    """La stessa storia con il protagonista rinominato in ``new_name``.

    A differenza di :meth:`CachedStory.personalized`, il nome non è scelto
    qui: viene passato da fuori, perché la traduzione non tocca ``plan.nome``
    (vedi ``Traduzione storie/translate_stories.py``) e quindi è identico in
    ogni lingua — serve un solo nome scelto una volta, applicato alle 3
    versioni, altrimenti il protagonista cambierebbe nome a ogni lingua.
    """
    if story.plan is None or not story.plan.nome or new_name.lower() == story.plan.nome.lower():
        return story
    text = _replace_word(story.text, story.plan.nome, new_name)
    return CachedStory(
        text=text,
        subject=story.subject,
        plan=StoryPlan(**{**story.plan.to_dict(), "nome": new_name}),
        model=story.model,
    )


@dataclass
class StoryCache:
    """Il pool caricato in memoria, indicizzato per soggetto."""

    stories: dict[str, list[CachedStory]]
    model: str = ""
    generated_at: str = ""
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "StoryCache":
        """Carica il pool da disco.

        Raises:
            StoryCacheError: file assente o formato non riconosciuto.
        """
        if not path.is_file():
            raise StoryCacheError(
                f"Pool di storie non trovato: {path}. "
                "Generalo con `python pregenerate_stories.py` (meglio su una "
                "macchina più potente del Pi) oppure disattiva cache.enabled."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StoryCacheError(f"Pool illeggibile ({path}): {exc}") from exc

        raw = data.get("storie")
        if not isinstance(raw, dict) or not raw:
            raise StoryCacheError(f"Il pool {path} non contiene storie")

        stories = {
            subject: [CachedStory.from_dict(subject, item) for item in items]
            for subject, items in raw.items()
            if items
        }
        return cls(
            stories=stories,
            model=str(data.get("modello", "")),
            generated_at=str(data.get("generato", "")),
            path=path,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generato": self.generated_at,
            "modello": self.model,
            "storie": {
                subject: [item.to_dict() for item in items]
                for subject, items in self.stories.items()
            },
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def total(self) -> int:
        return sum(len(items) for items in self.stories.values())

    def pick(
        self,
        subject: str,
        config: CacheConfig,
        *,
        rng: random.Random | None = None,
    ) -> CachedStory | None:
        """Una storia per ``subject``, o ``None`` se il pool non la copre.

        Cerca prima il soggetto esatto (es. "super mario"), poi il fallback
        indicato dal chiamante tramite ``config.fallback_subject``: un pool
        costruito sulle 9 macro-classi copre così anche le sottoclassi mai
        pre-generate.
        """
        rng = rng or random.Random()
        for key in (subject, config.fallback_subject):
            items = self.stories.get(key)
            if items and len(items) >= config.min_pool:
                chosen = rng.choice(items)
                logger.info(
                    "Storia presa dal pool ('%s', %d disponibili): nessuna chiamata al modello",
                    key,
                    len(items),
                )
                return chosen.personalized(rng) if config.personalize_name else chosen
            if items:
                logger.warning(
                    "Pool per '%s' troppo piccolo (%d < cache.min_pool=%d): lo ignoro",
                    key,
                    len(items),
                    config.min_pool,
                )
        logger.info("Nessuna storia nel pool per '%s'", subject)
        return None


# ── Pool multilingua (IT/EN/SL allineati per indice) ────────────────────────


@dataclass(frozen=True)
class SyncedPick:
    """Una storia pescata, nelle lingue richieste, tutte con lo stesso indice.

    Lo stesso indice in ogni lingua è ciò che rende possibile raccontare la
    "stessa" storia in più lingue (comando 1) e ritrovarla in un'altra lingua
    più tardi senza tradurre nulla a runtime (comando 3): la traduzione è
    già stata fatta offline, preservando l'ordine per soggetto (vedi
    ``Traduzione storie/translate_stories.py``).
    """

    pool_key: str  # soggetto realmente usato (può essere il fallback)
    index: int
    stories: dict[str, CachedStory]  # lingua -> storia


@dataclass
class MultiLanguageStoryCache:
    """I pool di più lingue, caricati insieme e pescati in sincronia."""

    caches: dict[str, StoryCache]  # codice lingua ("it"/"en"/"sl") -> pool

    @classmethod
    def load(cls, paths: dict[str, Path]) -> "MultiLanguageStoryCache":
        """Carica un pool per lingua.

        Raises:
            StoryCacheError: un qualunque pool è mancante o illeggibile.
        """
        return cls(caches={lang: StoryCache.load(path) for lang, path in paths.items()})

    def _common_indices(self, pool_key: str, languages: Sequence[str]) -> list[int]:
        """Indici presenti in ``pool_key`` per **tutte** le lingue richieste.

        Se i pool sono allineati (il caso normale, prodotto da
        ``translate_stories.py``) la lunghezza coincide in ogni lingua; si
        prende comunque il minimo per tollerare un pool parzialmente esteso
        in una sola lingua senza rompere le altre.
        """
        lengths = []
        for lang in languages:
            cache = self.caches.get(lang)
            if cache is None:
                raise StoryCacheError(f"Nessun pool caricato per la lingua '{lang}'")
            items = cache.stories.get(pool_key)
            if not items:
                return []
            lengths.append(len(items))
        return list(range(min(lengths)))

    def pick_synced(
        self,
        pool_key: str,
        config: CacheConfig,
        *,
        languages: Sequence[str],
        fallback_pool_key: str | None = None,
        rng: random.Random | None = None,
    ) -> SyncedPick | None:
        """Una storia con lo stesso indice in ogni lingua richiesta.

        Prova prima ``pool_key`` (il soggetto risolto da
        ``subjects.resolve_subject``); se il pool ha troppe poche storie
        allineate (sotto ``config.min_pool``) prova ``fallback_pool_key``
        (tipicamente il bucket della classe principale). Ritorna ``None``
        solo se nessuno dei due copre tutte le lingue richieste — non
        dovrebbe succedere con la mappa validata da
        ``tools/build_subject_map.py``, ma il chiamante decide come
        reagire (tipicamente: errore esplicito, non richiesta al modello).
        """
        rng = rng or random.Random()
        for key in (pool_key, fallback_pool_key):
            if not key:
                continue
            indices = self._common_indices(key, languages)
            if len(indices) >= config.min_pool:
                index = rng.choice(indices)
                stories = {lang: self.caches[lang].stories[key][index] for lang in languages}
                if config.personalize_name:
                    stories = _personalize_together(stories, rng)
                logger.info(
                    "Storia pescata dal pool ('%s', indice %d, lingue %s)",
                    key,
                    index,
                    ",".join(languages),
                )
                return SyncedPick(pool_key=key, index=index, stories=stories)
            if indices:
                logger.warning(
                    "Pool sincronizzato per '%s' troppo piccolo (%d < cache.min_pool=%d)",
                    key,
                    len(indices),
                    config.min_pool,
                )
        return None

    def get_at(self, pool_key: str, lang: str, index: int) -> CachedStory | None:
        """La storia a un indice esatto (comando 3: stessa storia, altra lingua)."""
        cache = self.caches.get(lang)
        if cache is None:
            return None
        items = cache.stories.get(pool_key)
        if not items or index >= len(items):
            return None
        return items[index]


def _personalize_together(
    stories: dict[str, CachedStory], rng: random.Random
) -> dict[str, CachedStory]:
    """Rinomina il protagonista con lo stesso nome in tutte le lingue.

    Sceglie un nome una sola volta (dal piano della prima lingua disponibile:
    ``nome``/``genere`` non vengono tradotti, sono identici ovunque) e lo
    applica a ogni versione, così IT/EN/SL restano coerenti fra loro.
    """
    reference = next(iter(stories.values()))
    if reference.plan is None or not reference.plan.nome:
        return stories
    pool = _NAMES_F if reference.plan.genere.lower().startswith("f") else _NAMES_M
    candidates = [n for n in pool if n.lower() != reference.plan.nome.lower()]
    if not candidates:
        return stories
    new_name = rng.choice(candidates)
    return {lang: _renamed(story, new_name) for lang, story in stories.items()}
