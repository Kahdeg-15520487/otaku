"""What the app remembers between sessions: state.toml — rewritten
wholesale on every change; there are no user edits to preserve."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from otaku2.formatting import toml_scalar
from otaku2.settings import row, write_atomic


@dataclass(frozen=True)
class StateConfig:
    model: str = ""  # "provider/model" to resume; "" = open the picker
    story: int = 0  # story id to reattach; 0 = start detached
    verbose: bool = False
    autocorrect: bool = True
    think: str = "none"


def load(path: Path) -> tuple[StateConfig, list[str]]:
    """Missing file → defaults; a malformed one falls back with a
    returned warning — remembered state is never worth failing a launch,
    and this module never prints."""
    if not path.exists():
        return StateConfig(), []
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        return StateConfig(), [f"Ignoring {path.name} ({e})."]
    story = raw.get("story")
    return StateConfig(
        model=str(raw.get("model", "")),
        story=story if isinstance(story, int) and story > 0 else 0,
        verbose=bool(raw.get("verbose", False)),
        autocorrect=bool(raw.get("autocorrect", True)),
        think=str(raw.get("think", "none")),
    ), []


def save(path: Path, state: StateConfig) -> None:
    body = "\n".join(
        [
            "# Written by otaku — what it remembers between sessions.",
            row(f"model = {toml_scalar(state.model)}", "bare `otaku` resumes this model"),
            row(f"story = {state.story}", "and reattaches this story (0 = none)"),
            row(f"verbose = {str(state.verbose).lower()}", "/set verbose"),
            row(f"autocorrect = {str(state.autocorrect).lower()}", "/set autocorrect"),
            row(f"think = {toml_scalar(state.think)}", "/set think"),
        ]
    )
    write_atomic(path, body + "\n")
