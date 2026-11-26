# Required data for the full Imaginarium system

This file describes every external data/model asset that is not currently in the source package.

## 1. Toy identification model

Copy a hierarchy export under:

```text
raspberry_story/models/
├── hierarchy.json
├── model.tflite
├── subject_map.json
└── <submodel directories/files referenced by hierarchy.json>
```

`hierarchy.json` must use the existing registry schema:

```json
{
  "main_labels": ["vehicle", "animal_real"],
  "main_model": "model.tflite",
  "img_size": [224, 224],
  "subclassifiers": {
    "vehicle": {"labels": ["treno", "macchinine"], "model": "vehicle/model.tflite"},
    "animal_real": {"labels": ["cane", "gatto"], "model": null}
  }
}
```

Use `model.tflite` input/output values compatible with `imaginarium/inference/predictor.py`:
- RGB image, resized to `img_size`
- UINT8 or INT8 quantized input/output, or FLOAT32
- TFLite output length exactly matching `main_labels` or subclass `labels`

A fine-tuned MobileNetV2 model must be exported by the original development/export pipeline. The code cannot reconstruct it from story files or photos alone.

## 2. Subject map

Generate from the real hierarchy and one IT story pool:

```bash
cd raspberry_story
python tools/build_subject_map.py \
  --hierarchy models/hierarchy.json \
  --pool runtime/stories_it.json \
  --out models/subject_map.json
```

This file maps model raw labels to keys in `runtime/stories_*.json`.

## 3. Story pools

Copy all synchronized language pools:

```text
raspberry_story/runtime/
├── stories_it.json
├── stories_en.json
└── stories_sl.json
```

Entries must use aligned subject keys and indices across languages.

## 4. Piper voices

Copy the three ONNX models and JSON metadata referenced by `config.yaml`:

```text
raspberry_story/voices/
├── it_IT-paola-medium.onnx
├── it_IT-paola-medium.onnx.json
├── en_US-lessac-medium.onnx
├── en_US-lessac-medium.onnx.json
├── sl_SI-artur-medium.onnx
└── sl_SI-artur-medium.onnx.json
```

## 5. Optional microphone model

For offline child speech recognition:

```text
~/models/vosk/
```

The directory must contain Vosk model files. `microphone_node.py` remains degraded without it.

## 6. Raspberry Pi hardware configuration

Update `config.yaml` after hardware measurement:
- `/dev/video0` or the actual camera device
- ALSA playback device
- ALSA recording device
- GPIO power and LED pins
- Piper voice paths

## 7. Verification commands

Run from `raspberry_story`:

```bash
python tools/check_full_system_assets.py
python test_camera.py
python test_classify.py --image runtime/photos/test_camera.jpg
python test_audio.py
python test_tts.py "Ciao, questo è un test"
python -m pytest
```

The asset checker is the authoritative readiness check. Identification or storytelling will remain degraded until every required file reports `[OK]`.
