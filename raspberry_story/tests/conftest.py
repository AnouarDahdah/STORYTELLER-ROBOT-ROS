"""Fixture comuni: pool di storie finti, mappa soggetti finta, config minima.

Nessuna di queste fixture tocca hardware o TFLite: i test di questa cartella
coprono solo i moduli a logica pura (subjects, story_cache, state,
l'orchestrazione di commands), verificabili anche su una macchina di
sviluppo senza Raspberry Pi collegato.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Il package sta nella cartella padre di tests/ ('Production'): aggiungerla
# a sys.path rende i test lanciabili da qualunque directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from imaginarium.subjects import SubjectMap  # noqa: E402


def write_pool(path: Path, stories: dict[str, list[dict]]) -> Path:
    """Scrive un pool di storie nel formato letto da ``StoryCache.load``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generato": "test", "modello": "test", "storie": stories}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def story_entry(text: str, *, nome: str | None = None, genere: str = "maschile") -> dict:
    """Una voce del pool, con o senza piano (per testare la personalizzazione)."""
    entry: dict = {"text": text, "model": "test"}
    if nome:
        entry["plan"] = {
            "nome": nome,
            "genere": genere,
            "luogo": "un posto",
            "problema": "un problema",
            "svolta": "una svolta",
            "finale": "un finale",
            "morale": "una morale",
        }
    return entry


@pytest.fixture
def subject_map() -> SubjectMap:
    """Una mappa soggetti minima ma realistica: 1 sottoclasse coperta, 1 no."""
    return SubjectMap(
        subclass_to_pool_key={"vehicle/treno": "treno"},
        main_class_to_bucket={
            "vehicle": "veicolo giocattolo",
            "animal_real": "animale di peluche",
        },
        final_fallback_subject="gioco di imitazione",
    )
