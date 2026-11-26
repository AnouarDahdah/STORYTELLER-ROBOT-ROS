"""Caricamento e validazione della configurazione centrale (config.yaml).

Stesso pattern di ``toyclf/config.py`` nel repo di sviluppo: un unico YAML,
convertito in dataclass tipizzate e immutabili, con i path relativi risolti
rispetto alla posizione del file di configurazione. Nessun altro modulo
legge YAML o hardcoda path/device.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from .exceptions import ConfigError


# ── Sezioni ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PathsConfig:
    """Cartelle usate a runtime (modelli e file temporanei della pipeline)."""

    models_root: Path
    photos_dir: Path
    audio_dir: Path
    # Mappa etichetta-grezza -> chiave del pool di storie, prodotta da
    # tools/build_subject_map.py. Vedi imaginarium/subjects.py.
    subject_map: Path
    # Dove il comando 2 salva quale storia ha raccontato, perché il comando 3
    # possa ritrovarla nelle altre lingue. Vedi imaginarium/state.py.
    last_story: Path


@dataclass(frozen=True)
class CameraConfig:
    """Parametri di scatto, identici a quelli validati con v4l2-ctl a mano."""

    device: str = "/dev/video0"
    width: int = 1920
    height: int = 1080
    pixelformat: str = "MJPG"
    timeout_s: int = 15


@dataclass(frozen=True)
class AudioConfig:
    """Device ALSA di ingresso/uscita, identici a quelli validati con arecord/aplay."""

    record_device: str = "hw:3,0"
    playback_device: str = "hw:2,0"
    channels: int = 1
    rate: int = 48000
    format: str = "S16_LE"
    record_seconds: float = 5.0


@dataclass(frozen=True)
class StoryConfig:
    """Parametri per la generazione della storia via Ollama.

    Valori pensati per un modello piccolo eseguito su CPU (Raspberry Pi 4):
    contesto e budget di token bassi, timeout alto perche' l'inferenza CPU e'
    lenta. Su un Pi4 il collo di bottiglia e' la banda di memoria, quindi il
    tempo scala quasi linearmente con i token generati e con la taglia del
    modello: le leve piu' efficaci sono ``two_pass``, ``target_words`` /
    ``num_predict`` e ``ollama_model``.

    Usa ``bench_story.py`` per misurare l'effetto di ogni leva prima di
    fissarla qui (vedi README, "Banco di prova della generazione").
    """

    # ── Trasporto ────────────────────────────────────────────────────────
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "gemma3:4b"
    timeout_s: int = 300
    # Quanto Ollama tiene il modello in RAM dopo la risposta. Su un Pi4
    # ricaricare un 4B da disco costa secondi: se la pipeline viene lanciata
    # piu' volte di seguito conviene tenerlo caldo ("10m", "1h", "-1" = sempre).
    keep_alive: str | None = "10m"

    # ── Sampling / risorse ───────────────────────────────────────────────
    num_ctx: int = 2048
    num_predict: int = 500
    # Thread di inferenza: Ollama non sempre satura i core disponibili di
    # default. Il Pi4 ha 4 core fisici. None = lascia decidere a Ollama.
    num_thread: int | None = None
    # Dimensione del batch di prompt eval. None = default di Ollama.
    num_batch: int | None = None
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    seed: int | None = None
    # Sequenze di stop opzionali (utili per tagliare code tipo "Fine." o
    # commenti del modello dopo la storia).
    stop: tuple[str, ...] = ()

    # ── Strategia di generazione ─────────────────────────────────────────
    # Due passate (piano JSON + prosa) = due generazioni complete, quindi
    # circa il doppio del tempo. E' la leva singola con il rapporto
    # guadagno/sforzo piu' alto: disattivarla dimezza le chiamate al modello
    # a costo di una coerenza narrativa minore.
    two_pass: bool = True
    plan_num_predict: int = 250
    plan_temperature: float = 0.8
    # Quante volte ritentare il piano JSON prima di ripiegare sulla passata
    # unica. 0 = un solo tentativo (comportamento storico).
    plan_max_retries: int = 0

    # ── Controllo qualita' dell'output ───────────────────────────────────
    min_words: int = 80
    # Lunghezza chiesta nel prompt. None = derivata da min_words
    # (``max(min_words + 60, 180)``), il comportamento storico.
    target_words: int | None = None
    max_retries: int = 1
    # Di quanto cresce num_predict a ogni ritentativo: budget del tentativo
    # n = num_predict * retry_growth**(n-1). 1.0 = budget costante (piu'
    # veloce), 2.0 = raddoppia ogni volta (comportamento storico su 2 tentativi).
    retry_growth: float = 2.0
    # Se True un testo troncato a meta' frase non fa scattare un ritentativo:
    # evita di pagare una rigenerazione intera per un testo "quasi buono".
    accept_truncated: bool = False

    # Sotto queste soglie la storia parla della categoria generica invece
    # che di una sottoclasse probabilmente sbagliata.
    min_main_confidence: float = 0.55
    min_sub_confidence: float = 0.50

    def __post_init__(self) -> None:
        if self.num_predict < 1:
            raise ConfigError("story.num_predict deve essere >= 1")
        if self.num_ctx < 256:
            raise ConfigError("story.num_ctx deve essere >= 256")
        if not 0.0 <= self.temperature <= 2.0:
            raise ConfigError("story.temperature deve essere tra 0 e 2")
        if not 0.0 <= self.plan_temperature <= 2.0:
            raise ConfigError("story.plan_temperature deve essere tra 0 e 2")
        if self.max_retries < 0:
            raise ConfigError("story.max_retries non puo' essere negativo")
        if self.plan_max_retries < 0:
            raise ConfigError("story.plan_max_retries non puo' essere negativo")
        if self.retry_growth < 1.0:
            raise ConfigError("story.retry_growth deve essere >= 1.0")
        if self.num_thread is not None and self.num_thread < 1:
            raise ConfigError("story.num_thread deve essere >= 1 (oppure assente)")
        if self.target_words is not None and self.target_words < 20:
            raise ConfigError("story.target_words deve essere >= 20 (oppure assente)")

    @property
    def word_target(self) -> int:
        """Lunghezza da chiedere al modello nel prompt della prosa."""
        if self.target_words is not None:
            return self.target_words
        return max(self.min_words + 60, 180)


@dataclass(frozen=True)
class CacheConfig:
    """Pool di storie pre-generate (vedi ``imaginarium/story_cache.py``).

    Attivandolo la pipeline non chiama piu' il modello a runtime: pesca una
    storia gia' pronta. E' l'unica leva che elimina la latenza invece di
    ridurla, al prezzo di storie non piu' diverse a ogni scatto — un
    compromesso di prodotto, non tecnico.
    """

    enabled: bool = False
    path: Path = Path("runtime/stories.json")
    # Sotto questa soglia il pool per un soggetto e' considerato troppo
    # povero per essere usato (si ripeterebbe subito) e si torna al modello.
    min_pool: int = 3
    # Soggetto di ripiego quando il pool non copre la sottoclasse predetta.
    # Usato solo dal percorso storico a singola lingua (StoryCache.pick,
    # pipeline.py); i comandi 1/2/3 risolvono il fallback da
    # models/subject_map.json (vedi imaginarium/subjects.py), non da qui.
    fallback_subject: str = "gioco di imitazione"
    # Cambia il nome del protagonista a ogni estrazione: due estrazioni dello
    # stesso testo sembrano meno identiche.
    personalize_name: bool = True
    # Se il pool non ha nulla di adatto, genera comunque con il modello.
    # False = errore esplicito, utile per verificare la copertura del pool.
    fallback_to_model: bool = True

    def __post_init__(self) -> None:
        if self.min_pool < 1:
            raise ConfigError("cache.min_pool deve essere >= 1")


@dataclass(frozen=True)
class TTSConfig:
    """Parametri per la sintesi vocale con Piper."""

    engine: str = "piper"
    piper_binary: str = "piper"
    voice_model: Path = Path("voices/it_IT-paola-medium.onnx")
    voice_config: Path | None = Path("voices/it_IT-paola-medium.onnx.json")
    sample_rate: int = 22050
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    timeout_s: int = 120


@dataclass(frozen=True)
class LanguageConfig:
    """Una lingua supportata dai comandi 1/2/3: pool di storie + voce Piper.

    ``tts`` è una normale :class:`TTSConfig`: eredita motore/timeout/prosodia
    dalla sezione ``tts:`` globale e sovrascrive solo ``voice_model`` /
    ``voice_config`` con la voce di questa lingua.
    """

    story_pool: Path
    tts: TTSConfig


@dataclass(frozen=True)
class AppConfig:
    """Configurazione completa della pipeline."""

    paths: PathsConfig
    camera: CameraConfig
    audio: AudioConfig
    story: StoryConfig
    cache: CacheConfig
    tts: TTSConfig
    languages: dict[str, LanguageConfig] = field(default_factory=dict)
    # Ordine di lingue del comando 1 ("racconta in tutte le lingue").
    command1_languages: tuple[str, ...] = ("it", "en", "sl")
    log_level: str = "INFO"

    def language(self, code: str) -> LanguageConfig:
        """La configurazione di una lingua, con un errore chiaro se manca.

        Raises:
            ConfigError: nessuna lingua ``code`` in ``languages:``.
        """
        try:
            return self.languages[code]
        except KeyError:
            raise ConfigError(
                f"Lingua sconosciuta: '{code}'. Configurate in config.yaml -> languages: "
                f"{', '.join(sorted(self.languages)) or '(nessuna)'}"
            ) from None


# ── Parsing ──────────────────────────────────────────────────────────────


def default_config_path() -> Path:
    """Path di default: ``config.yaml`` nella root del progetto (accanto a run_pipeline.py)."""
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"File di configurazione non trovato: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML non valido in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Il file di configurazione {path} deve contenere un mapping YAML")
    return data


def _section(data: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"La sezione '{key}' deve essere un mapping, trovato {type(value).__name__}")
    return dict(value)


def _resolve_path(raw: Any, base: Path) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else (base / path).resolve()


def _build_paths(section: dict[str, Any], base: Path) -> PathsConfig:
    return PathsConfig(
        models_root=_resolve_path(section.get("models_root", "models"), base),
        photos_dir=_resolve_path(section.get("photos_dir", "runtime/photos"), base),
        audio_dir=_resolve_path(section.get("audio_dir", "runtime/audio"), base),
        subject_map=_resolve_path(section.get("subject_map", "models/subject_map.json"), base),
        last_story=_resolve_path(section.get("last_story", "runtime/last_story.json"), base),
    )


def _build_camera(section: dict[str, Any]) -> CameraConfig:
    try:
        return CameraConfig(**section)
    except TypeError as exc:
        raise ConfigError(f"Parametro sconosciuto nella sezione 'camera': {exc}") from exc


def _build_audio(section: dict[str, Any]) -> AudioConfig:
    try:
        return AudioConfig(**section)
    except TypeError as exc:
        raise ConfigError(f"Parametro sconosciuto nella sezione 'audio': {exc}") from exc


def _build_story(section: dict[str, Any]) -> StoryConfig:
    section = dict(section)
    if "stop" in section:
        raw = section["stop"] or []
        if isinstance(raw, str):
            raw = [raw]
        section["stop"] = tuple(str(item) for item in raw)
    try:
        return StoryConfig(**section)
    except TypeError as exc:
        raise ConfigError(f"Parametro sconosciuto nella sezione 'story': {exc}") from exc


def _build_cache(section: dict[str, Any], base: Path) -> CacheConfig:
    section = dict(section)
    if "path" in section:
        section["path"] = _resolve_path(section["path"], base)
    try:
        return CacheConfig(**section)
    except TypeError as exc:
        raise ConfigError(f"Parametro sconosciuto nella sezione 'cache': {exc}") from exc


def _build_tts(section: dict[str, Any], base: Path) -> TTSConfig:
    section = dict(section)
    if "voice_model" in section:
        section["voice_model"] = _resolve_path(section["voice_model"], base)
    if section.get("voice_config"):
        section["voice_config"] = _resolve_path(section["voice_config"], base)
    elif "voice_config" in section:
        section["voice_config"] = None
    try:
        return TTSConfig(**section)
    except TypeError as exc:
        raise ConfigError(f"Parametro sconosciuto nella sezione 'tts': {exc}") from exc


def _build_language(code: str, section: dict[str, Any], base: Path, global_tts: TTSConfig) -> LanguageConfig:
    if "voice_model" not in section:
        raise ConfigError(f"languages.{code} deve indicare 'voice_model'")
    voice_model = _resolve_path(section["voice_model"], base)
    voice_config = (
        _resolve_path(section["voice_config"], base) if section.get("voice_config") else None
    )
    tts = replace(global_tts, voice_model=voice_model, voice_config=voice_config)
    story_pool = _resolve_path(section.get("story_pool", f"runtime/stories_{code}.json"), base)
    return LanguageConfig(story_pool=story_pool, tts=tts)


def _build_languages(
    data: Mapping[str, Any], base: Path, global_tts: TTSConfig
) -> dict[str, LanguageConfig]:
    raw = data.get("languages") or {}
    if not isinstance(raw, dict):
        raise ConfigError("La sezione 'languages' deve essere un mapping codice -> configurazione")
    return {
        code: _build_language(code, _section(raw, code), base, global_tts) for code in raw
    }


def load_config(path: Path | str | None = None) -> AppConfig:
    """Carica ``config.yaml`` e restituisce la configurazione tipizzata.

    Args:
        path: path esplicito al file YAML; se ``None`` usa quello di default
            nella root del progetto.

    Raises:
        ConfigError: file mancante, YAML invalido o valori incoerenti.
    """
    config_path = Path(path) if path is not None else default_config_path()
    data = _read_yaml(config_path)
    base = config_path.resolve().parent

    tts = _build_tts(_section(data, "tts"), base)
    return AppConfig(
        paths=_build_paths(_section(data, "paths"), base),
        camera=_build_camera(_section(data, "camera")),
        audio=_build_audio(_section(data, "audio")),
        story=_build_story(_section(data, "story")),
        cache=_build_cache(_section(data, "cache"), base),
        tts=tts,
        languages=_build_languages(data, base, tts),
        command1_languages=tuple(data.get("command1_languages") or ("it", "en", "sl")),
        log_level=str(data.get("log_level", "INFO")),
    )
