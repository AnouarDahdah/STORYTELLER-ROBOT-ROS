"""Predictor per un singolo modello TFLite + le sue label.

Incapsula caricamento modello, preprocessing e predizione: l'unico punto
del layer di inferenza che tocca un runtime TFLite.

I modelli sono esportati da ``export.py`` (repo ``toy_classifier``) con
quantizzazione INT8 completa e I/O ``uint8`` (vedi ``toyclf/export.py``).
La calibrazione usa immagini normalizzate in [0, 1]: per un modello con
input ``uint8``, TFLite deriva scale/zero-point in modo che i pixel grezzi
0-255 corrispondano già al range calibrato, quindi qui **non** si divide
per 255 come si farebbe con un modello float — si passa il pixel così
com'è e si lascia fare al runtime. Il codice gestisce comunque anche
modelli non quantizzati (input/output float32), per restare compatibile
con un .tflite esportato senza INT8.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from ..exceptions import ClassificationError, ModelNotFoundError

logger = logging.getLogger(__name__)


def _load_interpreter(model_path: Path) -> Any:
    """Istanzia un Interpreter TFLite, provando i runtime disponibili in ordine.

    Su Raspberry Pi OS ``tflite-runtime`` non ha sempre una wheel pronta per
    ogni versione di Python; si prova quindi anche il suo successore
    ufficiale (``ai-edge-litert``) e infine TensorFlow completo, se presente.
    """
    errors = []
    try:
        from tflite_runtime.interpreter import Interpreter  # type: ignore

        return Interpreter(model_path=str(model_path))
    except ImportError as exc:
        errors.append(f"tflite_runtime: {exc}")
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore

        return Interpreter(model_path=str(model_path))
    except ImportError as exc:
        errors.append(f"ai_edge_litert: {exc}")
    try:
        from tensorflow.lite import Interpreter  # type: ignore

        return Interpreter(model_path=str(model_path))
    except ImportError as exc:
        errors.append(f"tensorflow.lite: {exc}")

    raise ClassificationError(
        "Nessun runtime TFLite disponibile. Installa uno tra: "
        "'tflite-runtime', 'ai-edge-litert' o 'tensorflow'. Dettagli: " + " | ".join(errors)
    )


class ImagePredictor:
    """Carica un modello TFLite e predice su singole immagini."""

    def __init__(self, model_path: Path, labels: Sequence[str], img_size: tuple[int, int]) -> None:
        if not Path(model_path).is_file():
            raise ModelNotFoundError(
                f"Modello non trovato: {model_path}. "
                "Esegui 'sync_to_production.py' nel repo toy_classifier per popolare 'models/'."
            )

        logger.info("Caricamento modello TFLite: %s (%d classi)", model_path, len(labels))
        self._interpreter = _load_interpreter(model_path)
        self._interpreter.allocate_tensors()
        self._input_detail = self._interpreter.get_input_details()[0]
        self._output_detail = self._interpreter.get_output_details()[0]
        self._labels = tuple(labels)
        self._img_size = img_size

    @property
    def labels(self) -> tuple[str, ...]:
        return self._labels

    def _preprocess(self, image_path: Path | str) -> np.ndarray:
        image = Image.open(image_path).convert("RGB").resize(self._img_size)
        array = np.asarray(image)  # uint8, HWC

        dtype = self._input_detail["dtype"]
        if dtype in (np.uint8, np.int8):
            # Modello INT8: i pixel grezzi vengono interpretati dal runtime
            # secondo scale/zero-point calibrati in fase di export (vedi
            # docstring del modulo). Nessuna normalizzazione manuale.
            tensor = array.astype(dtype)
        else:
            # Modello non quantizzato: stesso preprocessing del training (rescale 1/255).
            tensor = (array.astype(np.float32) / 255.0).astype(dtype)

        return np.expand_dims(tensor, axis=0)

    def _dequantize(self, raw_output: np.ndarray) -> np.ndarray:
        scale, zero_point = self._output_detail.get("quantization", (0.0, 0))
        if not scale:
            return raw_output.astype(np.float32)
        return (raw_output.astype(np.float32) - zero_point) * scale

    def predict_probs(self, image_path: Path | str) -> np.ndarray:
        """Distribuzione di probabilità sulle classi del modello."""
        self._interpreter.set_tensor(self._input_detail["index"], self._preprocess(image_path))
        self._interpreter.invoke()
        raw = self._interpreter.get_tensor(self._output_detail["index"])[0]
        return self._dequantize(raw)

    def predict(self, image_path: Path | str) -> tuple[str, float]:
        """Classe più probabile e relativa confidenza."""
        probs = self.predict_probs(image_path)
        index = int(np.argmax(probs))
        return self._labels[index], float(probs[index])

    def top_k(self, image_path: Path | str, k: int = 3) -> list[tuple[str, float]]:
        """Le ``k`` classi più probabili, in ordine decrescente."""
        probs = self.predict_probs(image_path)
        order = np.argsort(probs)[::-1][:k]
        return [(self._labels[i], float(probs[i])) for i in order]
