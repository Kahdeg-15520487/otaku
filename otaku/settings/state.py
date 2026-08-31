"""What the app remembers between sessions: state.toml — rewritten
wholesale on every change; there are no user edits to preserve. What a
hand-edited or older file may hold is settled onto the vocabulary as it
is read (`State.settled`), so nothing downstream has to distrust it."""

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from otaku.formatting import toml_scalar
from otaku.settings import row, write_atomic

# Thinking effort as this file spells it. "default" is not a level: it
# means send nothing and let the model decide. This is the FILE's
# vocabulary — the order a menu offers it in is a frontend-shared
# decision and lives with the rest of the /set vocabulary
# (`backend.session.THINK_MENU`).
THINK_LEVELS = {"none", "low", "medium", "high", "xhigh", "max"}
THINK_DEFAULT = "default"


@dataclass(frozen=True)
class State:
    model: str = ""  # "provider/model" to resume; "" = open the picker
    story: int = 0  # story id to reattach; 0 = start detached
    verbose: bool = False
    autocorrect: bool = True
    notification: bool = False
    think: str = "none"

    @property
    def provider(self) -> str:
        """The provider half of `model` — split at the FIRST slash, since
        a model name may carry more of them."""
        return self.model.partition("/")[0]

    @property
    def bare_model(self) -> str:
        """The model half, as a server expects it; "" when nothing is
        remembered, and "" for a half-written spec ("ollama/")."""
        return self.model.partition("/")[2]

    def settled(self) -> "State":
        """This state on the vocabulary the app understands: a `think`
        it does not recognize falls to "none" — never a failed launch,
        and the next write heals the file."""
        if self.think == THINK_DEFAULT or self.think in THINK_LEVELS:
            return self
        return replace(self, think="none")


def load(path: Path) -> tuple[State, list[str]]:
    """Missing file → defaults; a malformed one falls back with a
    returned warning — remembered state is never worth failing a launch,
    and this module never prints."""
    if not path.exists():
        return State(), []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return State(), [f"Ignoring {path.name} ({e})."]
    story = raw.get("story")
    return State(
        model=str(raw.get("model", "")),
        story=story if isinstance(story, int) and story > 0 else 0,
        verbose=bool(raw.get("verbose", False)),
        autocorrect=bool(raw.get("autocorrect", True)),
        notification=bool(raw.get("notification", False)),
        think=str(raw.get("think", "none")),
    ).settled(), []


def save(path: Path, state: State) -> None:
    body = "\n".join(
        [
            "# Written by otaku — what it remembers between sessions.",
            row(f"model = {toml_scalar(state.model)}", "bare `otaku` resumes this model"),
            row(f"story = {state.story}", "and reattaches this story (0 = none)"),
            row(f"verbose = {str(state.verbose).lower()}", "/set verbose"),
            row(f"autocorrect = {str(state.autocorrect).lower()}", "/set autocorrect"),
            row(f"notification = {str(state.notification).lower()}", "/set notification"),
            row(f"think = {toml_scalar(state.think)}", "/set think"),
        ]
    )
    write_atomic(path, body + "\n")
