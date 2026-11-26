"""Test di ``MultiLanguageStoryCache``: pesca sincronizzata per indice, fallback, nomi coerenti."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from conftest import story_entry, write_pool
from imaginarium.config import CacheConfig
from imaginarium.story_cache import MultiLanguageStoryCache, StoryCacheError


def _make_cache(tmp_path: Path) -> MultiLanguageStoryCache:
    write_pool(
        tmp_path / "it.json",
        {
            "treno": [story_entry("Il Trenino corre.", nome="Trenino"), story_entry("Il Trenino fischia.", nome="Trenino")],
            "veicolo giocattolo": [story_entry(f"Storia veicolo IT {i}") for i in range(5)],
            "gioco di imitazione": [story_entry(f"Storia generica IT {i}") for i in range(5)],
        },
    )
    write_pool(
        tmp_path / "en.json",
        {
            "treno": [story_entry("Trenino runs.", nome="Trenino"), story_entry("Trenino whistles.", nome="Trenino")],
            "veicolo giocattolo": [story_entry(f"Vehicle story EN {i}") for i in range(5)],
            "gioco di imitazione": [story_entry(f"Generic story EN {i}") for i in range(5)],
        },
    )
    return MultiLanguageStoryCache.load({"it": tmp_path / "it.json", "en": tmp_path / "en.json"})


@pytest.fixture
def cache_config() -> CacheConfig:
    return CacheConfig(enabled=True, min_pool=1, personalize_name=False)


def test_pick_synced_stesso_indice_in_ogni_lingua(tmp_path, cache_config):
    cache = _make_cache(tmp_path)
    rng = random.Random(0)

    pick = cache.pick_synced("treno", cache_config, languages=["it", "en"], rng=rng)

    assert pick is not None
    assert pick.pool_key == "treno"
    it_text, en_text = pick.stories["it"].text, pick.stories["en"].text
    # Indice 0 -> "corre"/"runs", indice 1 -> "fischia"/"whistles": mai incrociati.
    assert ("corre" in it_text) == ("runs" in en_text)
    assert ("fischia" in it_text) == ("whistles" in en_text)


def test_pool_troppo_piccolo_scende_al_fallback(tmp_path, cache_config):
    cache = _make_cache(tmp_path)
    config = cache_config.__class__(enabled=True, min_pool=3, personalize_name=False)  # "treno" ne ha solo 2

    pick = cache.pick_synced(
        "treno", config, languages=["it", "en"], fallback_pool_key="veicolo giocattolo"
    )

    assert pick is not None
    assert pick.pool_key == "veicolo giocattolo"


def test_nessuna_corrispondenza_ritorna_none(tmp_path, cache_config):
    cache = _make_cache(tmp_path)

    pick = cache.pick_synced("soggetto_inesistente", cache_config, languages=["it", "en"])

    assert pick is None


def test_lingua_non_caricata_solleva_errore(tmp_path, cache_config):
    cache = _make_cache(tmp_path)

    with pytest.raises(StoryCacheError):
        cache.pick_synced("treno", cache_config, languages=["it", "sl"])


def test_get_at_indice_esatto(tmp_path):
    cache = _make_cache(tmp_path)

    story = cache.get_at("treno", "en", 1)

    assert story is not None
    assert "whistles" in story.text


def test_get_at_indice_fuori_range(tmp_path):
    cache = _make_cache(tmp_path)

    assert cache.get_at("treno", "en", 99) is None
    assert cache.get_at("soggetto_inesistente", "en", 0) is None


def test_personalizzazione_usa_lo_stesso_nome_in_ogni_lingua(tmp_path):
    cache = _make_cache(tmp_path)
    config = CacheConfig(enabled=True, min_pool=1, personalize_name=True)
    rng = random.Random(42)

    pick = cache.pick_synced("treno", config, languages=["it", "en"], rng=rng)

    assert pick is not None
    it_name = pick.stories["it"].plan.nome
    en_name = pick.stories["en"].plan.nome
    assert it_name == en_name
    assert it_name in pick.stories["it"].text
    assert en_name in pick.stories["en"].text
