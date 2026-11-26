#!/usr/bin/env python3
"""Verify that all files required for real identification and storytelling exist."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from imaginarium.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Imaginarium model and story assets")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.is_file():
        print(f"MISSING config: {config_path}")
        return 1

    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"INVALID config: {exc}")
        return 1

    checks: list[tuple[str, Path, str]] = []
    hierarchy = config.paths.models_root / "hierarchy.json"
    checks.append(("TFLite hierarchy", hierarchy, "Classifier hierarchy/label metadata"))

    try:
        hierarchy_data = json.loads(hierarchy.read_text(encoding="utf-8"))
        main_model = hierarchy_data.get("main_model")
        if main_model:
            checks.append(("Main TFLite model", config.paths.models_root / main_model, "Fine-tuned MobileNetV2 or hierarchical main classifier"))
        for name, entry in hierarchy_data.get("subclassifiers", {}).items():
            model = entry.get("model")
            if model:
                checks.append((f"Submodel {name}", config.paths.models_root / model, "Hierarchical subclass classifier"))
    except (json.JSONDecodeError, OSError):
        checks.append(("Main TFLite model", config.paths.models_root / "model.tflite", "Model is unknown until hierarchy.json exists"))

    checks += [
        ("Subject map", config.paths.subject_map, "Raw labels to story pool keys"),
    ]
    for language in ("it", "en", "sl"):
        lang = config.language(language)
        checks.append((f"{language} story pool", lang.story_pool, "Pre-generated language story pool"))
        checks.append((f"{language} Piper voice", lang.tts.voice_model, "Offline TTS model"))
        if lang.tts.voice_config:
            checks.append((f"{language} Piper config", lang.tts.voice_config, "Piper model metadata"))

    failed = 0
    print("Imaginarium full-system asset check")
    print(f"Config: {config_path}")
    print()
    for label, path, purpose in checks:
        if path.is_file():
            print(f"[OK]     {label}: {path}")
        else:
            failed += 1
            print(f"[MISSING] {label}: {path}  ({purpose})")

    print()
    if failed:
        print(f"FAIL: {failed} required file(s) missing")
        print("The ROS system can still run digital-twin/power/microphone nodes.")
        return 1

    print("PASS: all checked assets are present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
