"""Orchestrazione end-to-end: foto -> classificazione -> storia -> audio.

Sequenza (tutta sincrona, pensata per l'esecuzione manuale da CLI —
vedi ``run_pipeline.py``):

    1. capture_photo()      scatto (o immagine già esistente, per i test)
    2. HierarchicalClassifier.classify()   classe + sottoclasse + confidenze
    3. choose_subject()     decide di cosa parlerà la storia
    4. _story_for()         pool pre-generato, oppure Ollama (una o due passate)
    5. synthesize()         testo -> WAV (Piper)
    6. play_audio()         riproduzione sulle cuffie

Ogni passo può fallire in modo atteso (hardware non collegato, Ollama giù,
voce Piper mancante, ...): le eccezioni sono quelle già tipizzate nei
singoli moduli, il chiamante (CLI) decide come presentarle.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .audio_io import play_audio, record_audio
from .camera import capture_photo
from .config import AppConfig
from .inference import HierarchicalClassifier, HierarchicalPrediction
from .story import StoryResult, choose_subject, generate_story
from .story_cache import StoryCache, StoryCacheError
from .tts import synthesize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    """Tutti gli artefatti prodotti da una corsa della pipeline."""

    photo_path: Path
    classification: HierarchicalPrediction
    subject: str
    story: StoryResult
    audio_path: Path
    # Secondi per fase ("scatto", "classificazione", "storia", "sintesi",
    # "riproduzione"). Serve a sapere dove va davvero il tempo senza dedurlo
    # dai log: su un Pi4 la fase "storia" domina di ordini di grandezza, e il
    # suo dettaglio interno sta in ``story.metrics``.
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def total_s(self) -> float:
        return sum(self.timings.values())


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


@contextmanager
def _timed(timings: dict[str, float], phase: str) -> Iterator[None]:
    """Cronometra una fase, anche se solleva."""
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[phase] = time.perf_counter() - started


def _story_for(config: AppConfig, subject: str) -> StoryResult:
    """La storia: dal pool pre-generato se configurato, altrimenti dal modello.

    Il pool (``cache.enabled``) elimina la latenza invece di ridurla, perche'
    non c'e' nessuna inferenza a runtime. Un risultato con ``attempts == 0``
    e ``metrics`` vuota e' il segnale che la storia viene da li'.
    """
    if not config.cache.enabled:
        return generate_story(subject, config.story)

    try:
        cache = StoryCache.load(config.cache.path)
        cached = cache.pick(subject, config.cache)
    except StoryCacheError as exc:
        if not config.cache.fallback_to_model:
            raise
        logger.warning("Pool inutilizzabile (%s): genero con il modello", exc)
        cached = None

    if cached is not None:
        return cached.as_result()
    if not config.cache.fallback_to_model:
        raise StoryCacheError(
            f"Nessuna storia nel pool per '{subject}' e cache.fallback_to_model e' false"
        )
    logger.info("Pool senza storie per '%s': genero con il modello", subject)
    return generate_story(subject, config.story)


def run_pipeline(
    config: AppConfig,
    *,
    image_path: Path | str | None = None,
    play: bool = True,
    top_k: int = 3,
) -> PipelineResult:
    """Esegue l'intera pipeline e restituisce tutti gli artefatti prodotti.

    Args:
        config: configurazione completa (camera/audio/story/tts/paths).
        image_path: se indicato, salta lo scatto e classifica questa
            immagine (utile per testare classificazione/storia/audio da
            scrivania, senza dover fotografare nulla).
        play: se ``False`` sintetizza l'audio ma non lo riproduce (utile
            per testare a tavolino senza disturbare, o per riprodurlo dopo).
        top_k: quante classi alternative registrare nel risultato.
    """
    stamp = _timestamp()
    timings: dict[str, float] = {}

    if image_path is not None:
        photo_path = Path(image_path)
        logger.info("Uso immagine esistente: %s", photo_path)
    else:
        photo_path = config.paths.photos_dir / f"toy_{stamp}.jpg"
        print("[1/4] Scatto la foto...")
        with _timed(timings, "scatto"):
            capture_photo(config.camera, photo_path)

    print("[2/4] Riconoscimento del giocattolo...")
    with _timed(timings, "classificazione"):
        classifier = HierarchicalClassifier.from_config(config)
        result = classifier.classify(photo_path, top_k=top_k)
    print(
        f"      -> {result.main_class} / {result.sub_class}  "
        f"(main {result.main_confidence * 100:.1f}%)"
    )

    subject = choose_subject(
        main_class=result.main_class,
        sub_class=result.sub_class,
        main_confidence=result.main_confidence,
        sub_confidence=result.sub_confidence,
        config=config.story,
    )

    source = "pool pre-generato" if config.cache.enabled else config.story.ollama_model
    print(f"[3/4] Storia su '{subject}' ({source})...")
    with _timed(timings, "storia"):
        story = _story_for(config, subject)
    print(
        f"      -> {story.words} parole in {timings['storia']:.1f}s "
        f"({len(story.metrics.calls)} chiamate al modello)"
    )

    audio_path = config.paths.audio_dir / f"story_{stamp}.wav"
    print("[4/4] Sintesi vocale...")
    with _timed(timings, "sintesi"):
        synthesize(story.text, audio_path, config.tts)

    if play:
        print("      Riproduzione...")
        with _timed(timings, "riproduzione"):
            play_audio(config.audio, audio_path)

    return PipelineResult(
        photo_path=photo_path,
        classification=result,
        subject=subject,
        story=story,
        audio_path=audio_path,
        timings=timings,
    )
