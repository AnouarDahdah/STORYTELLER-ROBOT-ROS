"""Test di ``state.LastStory``: il roundtrip che collega il comando 2 al comando 3."""

from __future__ import annotations

import pytest

from imaginarium.state import LastStory, StateError


def test_roundtrip(tmp_path):
    path = tmp_path / "last_story.json"
    original = LastStory.create(
        pool_key="ninja turtle", index=3, lang="it", main_class="action_figure_cartoon", sub_class="tartarughe_ninja"
    )

    original.save(path)
    loaded = LastStory.load(path)

    assert loaded.pool_key == "ninja turtle"
    assert loaded.index == 3
    assert loaded.lang == "it"
    assert loaded.main_class == "action_figure_cartoon"
    assert loaded.sub_class == "tartarughe_ninja"


def test_sub_class_puo_essere_assente(tmp_path):
    path = tmp_path / "last_story.json"
    LastStory.create(
        pool_key="gioco di imitazione", index=0, lang="en", main_class="cibo", sub_class=None
    ).save(path)

    loaded = LastStory.load(path)

    assert loaded.sub_class is None


def test_file_assente_solleva_state_error(tmp_path):
    with pytest.raises(StateError):
        LastStory.load(tmp_path / "non_esiste.json")


def test_file_corrotto_solleva_state_error(tmp_path):
    path = tmp_path / "last_story.json"
    path.write_text("{non e' json valido", encoding="utf-8")

    with pytest.raises(StateError):
        LastStory.load(path)


def test_seconda_scrittura_sovrascrive_la_prima(tmp_path):
    path = tmp_path / "last_story.json"
    LastStory.create(pool_key="a", index=0, lang="it", main_class="x", sub_class=None).save(path)
    LastStory.create(pool_key="b", index=1, lang="en", main_class="y", sub_class="z").save(path)

    loaded = LastStory.load(path)

    assert loaded.pool_key == "b"
    assert loaded.lang == "en"
