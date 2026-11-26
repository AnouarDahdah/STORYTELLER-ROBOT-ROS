"""Eccezioni specifiche del package ``imaginarium``.

Una gerarchia dedicata permette al chiamante (CLI, pipeline) di distinguere
gli errori attesi — hardware non collegato, modello mancante, Ollama non
raggiungibile — dai bug veri e propri.
"""

from __future__ import annotations


class ImaginariumError(Exception):
    """Base per tutti gli errori del package."""


class ConfigError(ImaginariumError):
    """Configurazione mancante o invalida (config.yaml)."""


class CameraError(ImaginariumError):
    """Fotocamera non raggiungibile o scatto fallito."""


class AudioError(ImaginariumError):
    """Registrazione o riproduzione audio fallita."""


class ModelNotFoundError(ImaginariumError):
    """Modello o metadati della gerarchia non trovati su disco.

    Il rimedio più comune è eseguire ``sync_to_production.py`` (nel repo
    ``toy_classifier``) per popolare la cartella ``models/``.
    """


class ClassificationError(ImaginariumError):
    """Errore durante l'inferenza (immagine illeggibile, modello corrotto, ...)."""


class StoryGenerationError(ImaginariumError):
    """Il modello generativo (Ollama) non è raggiungibile o non produce testo utile."""


class TTSError(ImaginariumError):
    """La sintesi vocale (Piper) è fallita."""
