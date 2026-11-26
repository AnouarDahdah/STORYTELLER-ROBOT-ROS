"""I 3 comandi (in futuro: 3 pulsanti fisici).

Ogni funzione qui è pensata per essere il *callback* di un pulsante: prende
solo ``config`` (più i parametri specifici del comando) e non ha stato
implicito — l'unico stato che attraversa una chiamata è il file scritto da
:mod:`imaginarium.state`. Quando i pulsanti GPIO saranno collegati, ogni
handler chiamerà direttamente ``run_command_1(config)`` /
``run_command_2(config, lang)`` / ``run_command_3(config)``, senza passare
da ``run_button.py`` — vedi ``docs/06_comandi_e_workflow.md``.

Nessuno dei tre chiama Ollama: la storia viene sempre dal pool
pre-generato (:mod:`imaginarium.story_cache`), risolto tramite
:mod:`imaginarium.subjects`.

    Comando 1 — scatta, classifica, racconta la stessa storia in IT, EN, SL.
    Comando 2 — scatta, classifica, racconta in UNA lingua; salva lo stato.
    Comando 3 — legge lo stato del comando 2, recupera dal pool la
                traduzione della stessa storia nelle altre due lingue
                (nessuna traduzione a runtime) e la racconta.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from .audio_io import play_audio
from .camera import capture_photo
from .config import AppConfig
from .exceptions import ImaginariumError
from .inference import HierarchicalClassifier, HierarchicalPrediction
from .state import LastStory, StateError
from .story_cache import CachedStory, MultiLanguageStoryCache, StoryCacheError
from .subjects import SubjectMap, SubjectResolution, resolve_subject
from .tts import synthesize

logger = logging.getLogger(__name__)


class CommandError(ImaginariumError):
    """Un comando non può essere completato (pool insufficiente, stato assente, ...)."""


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


@contextmanager
def _timed(timings: dict[str, float], phase: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[phase] = time.perf_counter() - started


def _capture_and_classify(
    config: AppConfig, image_path: Path | str | None, timings: dict[str, float]
) -> tuple[Path, HierarchicalPrediction]:
    if image_path is not None:
        photo_path = Path(image_path)
        logger.info("Uso immagine esistente: %s", photo_path)
    else:
        photo_path = config.paths.photos_dir / f"toy_{_timestamp()}.jpg"
        with _timed(timings, "scatto"):
            capture_photo(config.camera, photo_path)

    with _timed(timings, "classificazione"):
        classifier = HierarchicalClassifier.from_config(config)
        prediction = classifier.classify(photo_path)
    logger.info(
        "Classificato: %s / %s (main %.1f%%, sub %s)",
        prediction.main_class,
        prediction.sub_class,
        prediction.main_confidence * 100,
        f"{prediction.sub_confidence * 100:.1f}%" if prediction.sub_confidence is not None else "n/d",
    )
    return photo_path, prediction


def _resolve(config: AppConfig, prediction: HierarchicalPrediction) -> SubjectResolution:
    subject_map = SubjectMap.load(config.paths.subject_map)
    return resolve_subject(
        main_class=prediction.main_class,
        main_confidence=prediction.main_confidence,
        sub_class=prediction.sub_class,
        sub_confidence=prediction.sub_confidence,
        subject_map=subject_map,
        min_main_confidence=config.story.min_main_confidence,
        min_sub_confidence=config.story.min_sub_confidence,
    )


def _fallback_pool_key(
    resolution: SubjectResolution, main_class: str, subject_map: SubjectMap
) -> str | None:
    """Il secondo tentativo per ``MultiLanguageStoryCache.pick_synced``.

    Se il livello scelto era "sottoclasse", il ripiego è il bucket della
    classe principale; se era già "classe principale" o "generico" il
    ripiego è il fallback finale (a meno che non coincida già col soggetto
    scelto, nel qual caso non c'è un livello più generico a cui scendere).
    """
    if resolution.tier == "sottoclasse":
        bucket = subject_map.pool_key_for_main_class(main_class)
        if bucket and bucket != resolution.pool_key:
            return bucket
    if subject_map.final_fallback_subject != resolution.pool_key:
        return subject_map.final_fallback_subject
    return None


def _load_multi_cache(config: AppConfig, languages: Sequence[str]) -> MultiLanguageStoryCache:
    paths = {lang: config.language(lang).story_pool for lang in languages}
    return MultiLanguageStoryCache.load(paths)


def _synthesize_and_play(
    config: AppConfig, lang: str, text: str, stamp: str, *, play: bool, timings: dict[str, float]
) -> Path:
    audio_path = config.paths.audio_dir / f"story_{stamp}_{lang}.wav"
    with _timed(timings, f"sintesi_{lang}"):
        synthesize(text, audio_path, config.language(lang).tts)
    if play:
        with _timed(timings, f"riproduzione_{lang}"):
            play_audio(config.audio, audio_path)
    return audio_path


# ── Risultati ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Command1Result:
    photo_path: Path
    classification: HierarchicalPrediction
    resolution: SubjectResolution
    index: int
    stories: dict[str, CachedStory]
    audio_paths: dict[str, Path]
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Command2Result:
    photo_path: Path
    classification: HierarchicalPrediction
    resolution: SubjectResolution
    lang: str
    index: int
    story: CachedStory
    audio_path: Path
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Command3Result:
    last_story: LastStory
    stories: dict[str, CachedStory]  # solo le lingue diverse da last_story.lang
    audio_paths: dict[str, Path]
    timings: dict[str, float] = field(default_factory=dict)


# ── Comando 1 ────────────────────────────────────────────────────────────


def run_command_1(
    config: AppConfig,
    *,
    image_path: Path | str | None = None,
    play: bool = True,
) -> Command1Result:
    """Scatta, classifica, racconta la stessa storia in tutte le lingue configurate.

    Raises:
        CommandError: il pool non copre nemmeno il fallback finale per
            nessuna delle lingue richieste (dataset di storie incompleto).
    """
    timings: dict[str, float] = {}
    languages = list(config.command1_languages)

    photo_path, prediction = _capture_and_classify(config, image_path, timings)
    resolution = _resolve(config, prediction)

    subject_map = SubjectMap.load(config.paths.subject_map)
    fallback_key = _fallback_pool_key(resolution, prediction.main_class, subject_map)

    with _timed(timings, "scelta_storia"):
        cache = _load_multi_cache(config, languages)
        pick = cache.pick_synced(
            resolution.pool_key,
            config.cache,
            languages=languages,
            fallback_pool_key=fallback_key,
        )
    if pick is None:
        raise CommandError(
            f"Nessuna storia disponibile per '{resolution.pool_key}' "
            f"(né per il fallback '{fallback_key}') in tutte le lingue {languages}. "
            "Il pool di storie è incompleto: vedi docs/05_modelli_e_storie.md."
        )

    stamp = _timestamp()
    audio_paths: dict[str, Path] = {}
    for lang in languages:
        audio_paths[lang] = _synthesize_and_play(
            config, lang, pick.stories[lang].text, stamp, play=play, timings=timings
        )

    return Command1Result(
        photo_path=photo_path,
        classification=prediction,
        resolution=resolution,
        index=pick.index,
        stories=pick.stories,
        audio_paths=audio_paths,
        timings=timings,
    )


# ── Comando 2 ────────────────────────────────────────────────────────────


def run_command_2(
    config: AppConfig,
    lang: str,
    *,
    image_path: Path | str | None = None,
    play: bool = True,
) -> Command2Result:
    """Scatta, classifica, racconta in una sola lingua; salva lo stato per il comando 3."""
    timings: dict[str, float] = {}

    photo_path, prediction = _capture_and_classify(config, image_path, timings)
    resolution = _resolve(config, prediction)

    subject_map = SubjectMap.load(config.paths.subject_map)
    fallback_key = _fallback_pool_key(resolution, prediction.main_class, subject_map)

    with _timed(timings, "scelta_storia"):
        cache = _load_multi_cache(config, [lang])
        pick = cache.pick_synced(
            resolution.pool_key,
            config.cache,
            languages=[lang],
            fallback_pool_key=fallback_key,
        )
    if pick is None:
        raise CommandError(
            f"Nessuna storia disponibile per '{resolution.pool_key}' (lingua '{lang}')."
        )

    stamp = _timestamp()
    audio_path = _synthesize_and_play(
        config, lang, pick.stories[lang].text, stamp, play=play, timings=timings
    )

    LastStory.create(
        pool_key=pick.pool_key,
        index=pick.index,
        lang=lang,
        main_class=prediction.main_class,
        sub_class=prediction.sub_class,
    ).save(config.paths.last_story)

    return Command2Result(
        photo_path=photo_path,
        classification=prediction,
        resolution=resolution,
        lang=lang,
        index=pick.index,
        story=pick.stories[lang],
        audio_path=audio_path,
        timings=timings,
    )


# ── Comando 3 ────────────────────────────────────────────────────────────


def run_command_3(config: AppConfig, *, play: bool = True) -> Command3Result:
    """Traduce la storia dell'ultimo comando 2 nelle altre due lingue, dal dataset.

    Nessuna chiamata a un modello: la traduzione esiste già nel pool, allo
    stesso indice (vedi ``Traduzione storie/translate_stories.py``, che
    preserva l'ordine per soggetto).

    Raises:
        CommandError: nessun comando 2 eseguito prima, oppure la traduzione
            non è presente nel pool per una delle altre lingue.
    """
    timings: dict[str, float] = {}
    try:
        with _timed(timings, "lettura_stato"):
            last = LastStory.load(config.paths.last_story)
    except StateError as exc:
        raise CommandError(str(exc)) from exc

    other_languages = [lang for lang in config.languages if lang != last.lang]

    with _timed(timings, "recupero_traduzioni"):
        cache = _load_multi_cache(config, other_languages)
        stories: dict[str, CachedStory] = {}
        missing: list[str] = []
        for lang in other_languages:
            story = cache.get_at(last.pool_key, lang, last.index)
            if story is None:
                missing.append(lang)
            else:
                stories[lang] = story
    if missing:
        raise CommandError(
            f"Traduzione mancante nel pool per {missing} "
            f"(soggetto '{last.pool_key}', indice {last.index}). "
            "Il pool non è allineato fra le lingue: vedi docs/05_modelli_e_storie.md."
        )

    stamp = _timestamp()
    audio_paths: dict[str, Path] = {}
    for lang in other_languages:
        audio_paths[lang] = _synthesize_and_play(
            config, lang, stories[lang].text, stamp, play=play, timings=timings
        )

    return Command3Result(
        last_story=last, stories=stories, audio_paths=audio_paths, timings=timings
    )
