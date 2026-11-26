"""imaginarium — pipeline di produzione: foto -> classificazione -> storia -> audio.

Package pensato per girare sul Raspberry Pi 4 (webcam+microfono su USB,
cuffie/amplificatore in uscita). Non importa TensorFlow: l'inferenza usa
TFLite (``tflite-runtime`` o equivalente), molto più leggero da installare
ed eseguire su CPU ARM. La storia viene sempre da un pool pre-generato
multilingua (IT/EN/SL): nessuna inferenza testuale a runtime (Ollama resta
solo come percorso opzionale/dev, vedi ``story``/``pipeline``).

Sottopackage/moduli:
    config        config.yaml -> dataclass tipizzate (incluse le lingue)
    exceptions    gerarchia di errori del progetto
    camera        scatto foto (v4l2-ctl)
    audio_io      registrazione/riproduzione (arecord/aplay)
    inference/    classificazione gerarchica (TFLite)
    subjects      etichetta grezza + confidenza -> chiave del pool di storie
    story_cache   pool di storie pre-generate, anche multilingua sincronizzato
    state         stato "ultima storia" (ponte fra comando 2 e comando 3)
    commands      i 3 comandi (run_button.py)
    tts           sintesi vocale (Piper)
    sysmon        statistiche CPU/RAM/temperatura (monitor_stats.py)
    story         generazione storia via Ollama — percorso opzionale/dev
    pipeline      orchestrazione storica a singola lingua via Ollama (dev)
"""

from .config import AppConfig, load_config
from .exceptions import (
    AudioError,
    CameraError,
    ClassificationError,
    ConfigError,
    ImaginariumError,
    ModelNotFoundError,
    StoryGenerationError,
    TTSError,
)

__version__ = "0.1.0"

__all__ = [
    "AppConfig",
    "load_config",
    "ImaginariumError",
    "ConfigError",
    "CameraError",
    "AudioError",
    "ModelNotFoundError",
    "ClassificationError",
    "StoryGenerationError",
    "TTSError",
    "__version__",
]
