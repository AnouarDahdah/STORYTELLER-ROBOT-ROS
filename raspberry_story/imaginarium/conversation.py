"""Stateful, child-safe conversation planning for the story device.

The planner is deliberately offline and deterministic: it never invents contacts,
locations, or personal child data, and it only uses known toy profiles plus
pre-generated story text.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path


NARRATIVE_AXES = (
    "amicizia",
    "coraggio",
    "collaborazione",
    "curiosita",
    "gentilezza",
    "responsabilita",
)


@dataclass
class DeviceConversation:
    device_id: str
    child_name: str = ""
    preferred_language: str = "it"
    current_toy_id: str = ""
    seen_toy_ids: list[str] = field(default_factory=list)
    chapter_count: int = 0
    last_story_index: int = -1
    axis_index: int = 0
    updated_at: str = ""

    def mark_seen(self, toy_id: str) -> None:
        if toy_id and toy_id not in self.seen_toy_ids:
            self.seen_toy_ids.append(toy_id)
        self.current_toy_id = toy_id
        self.updated_at = _dt.datetime.now().isoformat(timespec="seconds")

    def next_axis(self) -> str:
        axis = NARRATIVE_AXES[self.axis_index % len(NARRATIVE_AXES)]
        self.axis_index += 1
        self.updated_at = _dt.datetime.now().isoformat(timespec="seconds")
        return axis

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _dt.datetime.now().isoformat(timespec="seconds")
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str, *, device_id: str) -> "DeviceConversation":
        path = Path(path)
        if not path.is_file():
            return cls(device_id=device_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                device_id=str(data.get("device_id", device_id)),
                child_name=str(data.get("child_name", "")),
                preferred_language=str(data.get("preferred_language", "it")),
                current_toy_id=str(data.get("current_toy_id", "")),
                seen_toy_ids=list(data.get("seen_toy_ids", [])),
                chapter_count=int(data.get("chapter_count", 0)),
                last_story_index=int(data.get("last_story_index", -1)),
                axis_index=int(data.get("axis_index", 0)),
                updated_at=str(data.get("updated_at", "")),
            )
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return cls(device_id=device_id)


def choose_available_story_index(indices: list[int], state: DeviceConversation) -> int:
    """Choose an unseen story index by index; repeat only when the pool has no alternative."""
    if not indices:
        return 0
    alternatives = [index for index in indices if index != state.last_story_index]
    pool = alternatives or indices
    rng = random.Random(f"{state.device_id}:{state.chapter_count}:{state.last_story_index}")
    return rng.choice(pool)


def story_prompt(toy_id: str, axis: str, seen_toys: list[str], language: str = "it") -> str:
    companions = [item for item in seen_toys if item != toy_id]
    companion = companions[-1] if companions else ""
    if language == "it":
        if companion:
            return (
                f"Vuoi ascoltare una nuova storia su {toy_id}, dove incontra {companion} "
                f"e imparano il valore della {axis}?"
            )
        return f"Vuoi ascoltare una nuova storia su {toy_id}, dedicata alla {axis}?"
    if language == "en":
        if companion:
            return f"Would you like a new story about {toy_id}, meeting {companion} and learning about {axis}?"
        return f"Would you like a new story about {toy_id}, about {axis}?"
    if companion:
        return f"Zelis posluati novo zgodbo o {toy_id}, ki sreca {companion} in spozna {axis}?"
    return f"Zelis posluati novo zgodbo o {toy_id}, ki govori o {axis}?"
