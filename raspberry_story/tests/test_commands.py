"""Test di orchestrazione dei 3 comandi, senza hardware.

Sostituisce scatto/classificazione/sintesi/riproduzione con dei fake e
verifica il filo che li lega: risoluzione del soggetto, pesca sincronizzata
dal pool, salvataggio e rilettura dello stato fra comando 2 e comando 3. Non
copre camera/audio/TFLite reali (serve il Raspberry Pi per quello, vedi
docs/07_monitoraggio_risorse.md e i test manuali in test_camera.py/test_audio.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import story_entry, write_pool
from imaginarium import commands
from imaginarium.config import (
    AppConfig,
    AudioConfig,
    CacheConfig,
    CameraConfig,
    LanguageConfig,
    PathsConfig,
    StoryConfig,
    TTSConfig,
)
from imaginarium.inference import HierarchicalPrediction


def _write_subject_map(path: Path) -> None:
    data = {
        "subclass_to_story": {
            "vehicle/treno": {"pool_key": "treno", "method": "test"},
        },
        "main_class_to_legacy_bucket": {
            "vehicle": "veicolo giocattolo",
            "animal_real": "animale di peluche",
        },
        "final_fallback_subject": "gioco di imitazione",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_pools(root: Path) -> None:
    for lang, word in (("it", "corre"), ("en", "runs"), ("sl", "teče")):
        write_pool(
            root / f"stories_{lang}.json",
            {
                "treno": [story_entry(f"Il treno {word}.", nome="Trenino")],
                "veicolo giocattolo": [story_entry(f"Storia veicolo {lang} {i}") for i in range(3)],
                "gioco di imitazione": [story_entry(f"Storia generica {lang} {i}") for i in range(3)],
            },
        )


def _make_config(tmp_path: Path) -> AppConfig:
    _write_subject_map(tmp_path / "models" / "subject_map.json")
    _write_pools(tmp_path / "runtime")

    def tts_for(lang: str) -> TTSConfig:
        return TTSConfig(voice_model=tmp_path / f"voices/{lang}.onnx", voice_config=None)

    return AppConfig(
        paths=PathsConfig(
            models_root=tmp_path / "models",
            photos_dir=tmp_path / "runtime/photos",
            audio_dir=tmp_path / "runtime/audio",
            subject_map=tmp_path / "models/subject_map.json",
            last_story=tmp_path / "runtime/last_story.json",
        ),
        camera=CameraConfig(),
        audio=AudioConfig(),
        story=StoryConfig(min_main_confidence=0.55, min_sub_confidence=0.50),
        cache=CacheConfig(enabled=True, min_pool=1, personalize_name=False, fallback_to_model=False),
        tts=TTSConfig(),
        languages={
            "it": LanguageConfig(story_pool=tmp_path / "runtime/stories_it.json", tts=tts_for("it")),
            "en": LanguageConfig(story_pool=tmp_path / "runtime/stories_en.json", tts=tts_for("en")),
            "sl": LanguageConfig(story_pool=tmp_path / "runtime/stories_sl.json", tts=tts_for("sl")),
        },
        command1_languages=("it", "en", "sl"),
    )


class _FakeClassifier:
    """Sostituisce HierarchicalClassifier: nessun modello, nessuna foto reale."""

    prediction: HierarchicalPrediction | None = None  # impostato dal test

    @classmethod
    def from_config(cls, config):
        return cls()

    def classify(self, image_path, top_k: int = 3):
        assert _FakeClassifier.prediction is not None, "il test deve impostare _FakeClassifier.prediction"
        return _FakeClassifier.prediction


@pytest.fixture(autouse=True)
def _patch_hardware(monkeypatch, tmp_path):
    """Sostituisce scatto/classificazione/sintesi/riproduzione con dei fake."""

    def fake_capture_photo(camera_config, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"jpeg-finto")
        return output_path

    def fake_synthesize(text, output_path, tts_config):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return output_path

    played: list[Path] = []

    def fake_play_audio(audio_config, input_path):
        played.append(Path(input_path))

    monkeypatch.setattr(commands, "capture_photo", fake_capture_photo)
    monkeypatch.setattr(commands, "HierarchicalClassifier", _FakeClassifier)
    monkeypatch.setattr(commands, "synthesize", fake_synthesize)
    monkeypatch.setattr(commands, "play_audio", fake_play_audio)
    yield played


def _prediction(**overrides) -> HierarchicalPrediction:
    defaults = dict(
        main_class="vehicle", main_confidence=0.9, sub_class="treno", sub_confidence=0.9
    )
    defaults.update(overrides)
    return HierarchicalPrediction(**defaults)


def test_comando1_racconta_la_stessa_storia_in_3_lingue(tmp_path):
    config = _make_config(tmp_path)
    _FakeClassifier.prediction = _prediction()

    result = commands.run_command_1(config, image_path=tmp_path / "foto.jpg")

    assert result.resolution.tier == "sottoclasse"
    assert result.resolution.pool_key == "treno"
    assert set(result.stories) == {"it", "en", "sl"}
    # Stesso protagonista (nome non tradotto) in ogni lingua: coerenza fra le tre voci.
    nomi = {lang.plan.nome for lang in result.stories.values()}
    assert len(nomi) == 1


def test_comando2_poi_comando3_ritrovano_la_stessa_storia(tmp_path):
    config = _make_config(tmp_path)
    _FakeClassifier.prediction = _prediction()

    c2 = commands.run_command_2(config, "it", image_path=tmp_path / "foto.jpg")
    assert c2.lang == "it"
    assert c2.resolution.pool_key == "treno"

    c3 = commands.run_command_3(config)

    assert set(c3.stories) == {"en", "sl"}
    assert c3.last_story.pool_key == c2.resolution.pool_key
    assert c3.last_story.index == c2.index
    # La traduzione EN allo stesso indice e' quella del pool, non una nuova generazione.
    assert "runs" in c3.stories["en"].text


def test_comando3_senza_comando2_precedente_fallisce(tmp_path):
    config = _make_config(tmp_path)

    with pytest.raises(commands.CommandError):
        commands.run_command_3(config)


def test_sottoclasse_incerta_usa_il_bucket_della_classe_principale(tmp_path):
    config = _make_config(tmp_path)
    _FakeClassifier.prediction = _prediction(sub_confidence=0.2)  # sotto il 50%

    result = commands.run_command_2(config, "it", image_path=tmp_path / "foto.jpg")

    assert result.resolution.tier == "classe_principale"
    assert result.resolution.pool_key == "veicolo giocattolo"


def test_classe_principale_incerta_usa_il_fallback_finale(tmp_path):
    config = _make_config(tmp_path)
    _FakeClassifier.prediction = _prediction(main_confidence=0.3, sub_confidence=0.9)

    result = commands.run_command_2(config, "it", image_path=tmp_path / "foto.jpg")

    assert result.resolution.tier == "generico"
    assert result.resolution.pool_key == "gioco di imitazione"


def test_no_play_non_chiama_play_audio(tmp_path, _patch_hardware):
    config = _make_config(tmp_path)
    _FakeClassifier.prediction = _prediction()

    commands.run_command_2(config, "it", image_path=tmp_path / "foto.jpg", play=False)

    assert _patch_hardware == []
