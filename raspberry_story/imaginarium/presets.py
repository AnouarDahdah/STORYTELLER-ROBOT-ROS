"""Configurazioni di generazione pronte da confrontare sul dispositivo.

Un preset è solo un insieme di override su :class:`~.config.StoryConfig`: non
introduce logica nuova, sposta soltanto le leve che il banco di prova
(``bench_story.py``) deve poter cambiare da riga di comando senza toccare
``config.yaml``.

Le leve, in ordine di impatto atteso su un Raspberry Pi 4 (dove il limite è
la banda di memoria, non il calcolo):

1. ``ollama_model`` — il tempo scala circa con il numero di parametri: un 1B
   è nell'ordine di 3-4 volte più veloce di un 4B.
2. ``two_pass`` — disattivarlo dimezza le chiamate al modello, al costo di
   una coerenza narrativa minore.
3. ``target_words`` / ``num_predict`` — i token generati dominano il tempo,
   quasi linearmente.
4. ``max_retries`` / ``accept_truncated`` — un ritentativo costa una
   generazione intera: evitarlo vale quanto accorciare la storia.
5. ``num_ctx``, ``num_thread``, ``keep_alive`` — margini minori ma gratuiti.

Nessun preset è "quello giusto" a priori: servono a misurare, non a
prescrivere. Quando uno vince sul campo, i suoi valori vanno ricopiati in
``config.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .config import StoryConfig
from .exceptions import ConfigError


@dataclass(frozen=True)
class Preset:
    """Un insieme nominato di override, con il motivo per cui esiste."""

    name: str
    description: str
    overrides: dict[str, Any]

    def apply(self, base: StoryConfig) -> StoryConfig:
        return apply_overrides(base, self.overrides)


# Modello piccolo usato dai preset "tiny": vedi README per l'installazione.
SMALL_MODEL = "gemma3:1b"

_PRESET_LIST: list[Preset] = [
    Preset(
        "baseline",
        "config.yaml così com'è — il metro di paragone, non toccarlo",
        {},
    ),
    Preset(
        "single_pass",
        "solo two_pass=false: isola il costo del piano JSON",
        {"two_pass": False},
    ),
    Preset(
        "short",
        "storia più corta (~130 parole): isola il costo dei token generati",
        {"target_words": 130, "min_words": 60, "num_predict": 320},
    ),
    Preset(
        "lenient",
        "nessun ritentativo e troncature accettate: isola il costo dei retry",
        {"max_retries": 0, "accept_truncated": True},
    ),
    Preset(
        "threads",
        "num_thread=4 (i core fisici del Pi4): Ollama non sempre li satura",
        {"num_thread": 4},
    ),
    Preset(
        "small_ctx",
        "num_ctx=1024: i prompt di questa pipeline stanno abbondantemente sotto",
        {"num_ctx": 1024},
    ),
    Preset(
        "fast",
        "tutte le leve a costo zero insieme, stesso modello",
        {
            "two_pass": False,
            "target_words": 120,
            "min_words": 55,
            "num_predict": 280,
            "num_ctx": 1024,
            "num_thread": 4,
            "max_retries": 0,
            "accept_truncated": True,
        },
    ),
    Preset(
        "plan_strict",
        "piano più deterministico: meno JSON invalidi, meno ripieghi sulla passata unica",
        {"plan_temperature": 0.4, "plan_num_predict": 200},
    ),
    Preset(
        "quality",
        "due passate, storia più lunga, un ritentativo sul piano: il limite superiore",
        {
            "two_pass": True,
            "target_words": 220,
            "num_predict": 700,
            "plan_max_retries": 1,
            "max_retries": 1,
        },
    ),
    Preset(
        f"tiny ({SMALL_MODEL})",
        "modello 1B con le leve di 'fast': il salto di velocità più grande",
        {
            "ollama_model": SMALL_MODEL,
            "two_pass": False,
            "target_words": 120,
            "min_words": 55,
            "num_predict": 280,
            "num_ctx": 1024,
            "num_thread": 4,
            "max_retries": 0,
            "accept_truncated": True,
        },
    ),
    Preset(
        f"tiny_two_pass ({SMALL_MODEL})",
        "modello 1B ma con il piano: verifica se le due passate compensano la taglia",
        {
            "ollama_model": SMALL_MODEL,
            "two_pass": True,
            "target_words": 140,
            "min_words": 60,
            "num_predict": 320,
            "num_ctx": 1024,
            "num_thread": 4,
            "plan_temperature": 0.5,
        },
    ),
]

# I preset che nominano un modello sono registrati anche con il nome corto
# ("tiny"), così da riga di comando non serve scrivere la parentesi.
PRESETS: dict[str, Preset] = {}
for _preset in _PRESET_LIST:
    PRESETS[_preset.name] = _preset
    _short = _preset.name.split(" (")[0]
    PRESETS.setdefault(_short, _preset)


def preset_names() -> list[str]:
    """I nomi canonici, nell'ordine in cui vale la pena provarli."""
    return [p.name for p in _PRESET_LIST]


def get_preset(name: str) -> Preset:
    """Preset per nome (accetta anche la forma corta senza modello).

    Raises:
        ConfigError: nome sconosciuto.
    """
    key = name.strip()
    if key in PRESETS:
        return PRESETS[key]
    raise ConfigError(
        f"Preset sconosciuto: '{name}'. Disponibili: {', '.join(preset_names())}"
    )


# ── Override arbitrari (--set chiave=valore) ──────────────────────────────


def _to_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in {"true", "1", "si", "sì", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    raise ConfigError(f"Valore booleano non riconosciuto: '{raw}'")


def _optional(convert: Callable[[str], Any]) -> Callable[[str], Any]:
    """Converte, ma lascia passare la stringa vuota / 'none' come ``None``."""

    def inner(raw: str) -> Any:
        if raw.strip().lower() in {"", "none", "null", "auto"}:
            return None
        return convert(raw)

    return inner


def _to_stop(raw: str) -> tuple[str, ...]:
    return tuple(part for part in (p.strip() for p in raw.split("|")) if part)


# Il tipo di ogni campo di StoryConfig, per convertire le stringhe che
# arrivano da riga di comando. Esplicito invece che dedotto dalle annotazioni
# perché con ``from __future__ import annotations`` quelle sono già stringhe,
# e i campi opzionali (``int | None``) non si distinguerebbero.
_COERCE: dict[str, Callable[[str], Any]] = {
    "ollama_url": str,
    "ollama_model": str,
    "timeout_s": int,
    "keep_alive": _optional(str),
    "num_ctx": int,
    "num_predict": int,
    "num_thread": _optional(int),
    "num_batch": _optional(int),
    "temperature": float,
    "top_p": float,
    "top_k": int,
    "repeat_penalty": float,
    "seed": _optional(int),
    "stop": _to_stop,
    "two_pass": _to_bool,
    "plan_num_predict": int,
    "plan_temperature": float,
    "plan_max_retries": int,
    "min_words": int,
    "target_words": _optional(int),
    "max_retries": int,
    "retry_growth": float,
    "accept_truncated": _to_bool,
    "min_main_confidence": float,
    "min_sub_confidence": float,
}


def coerce_value(key: str, raw: Any) -> Any:
    """Converte un valore testuale nel tipo atteso dal campo di StoryConfig.

    Raises:
        ConfigError: campo inesistente o valore non convertibile.
    """
    if key not in _COERCE:
        raise ConfigError(
            f"'{key}' non è un parametro di story. Disponibili: {', '.join(sorted(_COERCE))}"
        )
    if not isinstance(raw, str):
        return raw
    try:
        return _COERCE[key](raw)
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Valore non valido per '{key}': '{raw}' ({exc})") from exc


def parse_assignment(text: str) -> tuple[str, Any]:
    """``"num_predict=300"`` -> ``("num_predict", 300)``.

    Raises:
        ConfigError: sintassi errata o campo sconosciuto.
    """
    if "=" not in text:
        raise ConfigError(f"Atteso 'chiave=valore', trovato: '{text}'")
    key, _, raw = text.partition("=")
    key = key.strip()
    # Tollera la forma qualificata "story.num_predict=300".
    if key.startswith("story."):
        key = key[len("story.") :]
    return key, coerce_value(key, raw)


def apply_overrides(base: StoryConfig, overrides: Mapping[str, Any]) -> StoryConfig:
    """Nuova ``StoryConfig`` con i campi indicati sostituiti.

    Raises:
        ConfigError: campo sconosciuto o valore che viola la validazione.
    """
    if not overrides:
        return base
    clean = {key: coerce_value(key, value) for key, value in overrides.items()}
    try:
        return replace(base, **clean)
    except TypeError as exc:
        raise ConfigError(f"Override non applicabile: {exc}") from exc


def describe(config: StoryConfig, base: StoryConfig | None = None) -> str:
    """Riga compatta con i parametri che contano (e cosa differisce da ``base``)."""
    parts = [
        f"modello={config.ollama_model}",
        f"two_pass={'sì' if config.two_pass else 'no'}",
        f"parole~{config.word_target}",
        f"num_predict={config.num_predict}",
        f"num_ctx={config.num_ctx}",
        f"retry={config.max_retries}",
    ]
    if config.num_thread:
        parts.append(f"thread={config.num_thread}")
    if config.accept_truncated:
        parts.append("troncature=ok")
    line = "  ".join(parts)
    if base is not None:
        diff = diff_fields(base, config)
        if diff:
            line += "   [diff: " + ", ".join(f"{k}={v}" for k, v in diff.items()) + "]"
    return line


def diff_fields(base: StoryConfig, other: StoryConfig) -> dict[str, Any]:
    """I campi in cui ``other`` si discosta da ``base``."""
    return {
        key: getattr(other, key)
        for key in _COERCE
        if getattr(base, key, None) != getattr(other, key, None)
    }
