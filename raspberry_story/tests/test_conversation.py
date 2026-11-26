from __future__ import annotations

from imaginarium.conversation import DeviceConversation, choose_available_story_index, story_prompt


def test_conversation_remembers_seen_toys(tmp_path):
    state = DeviceConversation.load(tmp_path / "missing.json", device_id="device-a")
    state.mark_seen("treno")
    state.mark_seen("orsetto")
    state.mark_seen("treno")
    state.save(tmp_path / "conversation.json")

    loaded = DeviceConversation.load(tmp_path / "conversation.json", device_id="device-a")
    assert loaded.seen_toy_ids == ["treno", "orsetto"]
    assert loaded.current_toy_id == "treno"


def test_story_index_changes_when_alternative_exists():
    state = DeviceConversation(device_id="device-a", chapter_count=1, last_story_index=0)
    first = choose_available_story_index([0, 1, 2], state)
    assert first in (1, 2)


def test_story_index_repeats_only_when_no_alternative():
    state = DeviceConversation(device_id="device-a", chapter_count=4, last_story_index=1)
    assert choose_available_story_index([1], state) == 1


def test_story_prompt_mentions_seen_companion():
    text = story_prompt("treno", "amicizia", ["treno", "orsetto"], "it")
    assert "treno" in text
    assert "orsetto" in text
    assert "amicizia" in text
