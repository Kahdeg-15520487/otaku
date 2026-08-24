"""The command surface both frontends share: every command, what it
takes, what it is called — the declaration, not the dispatch.

Each spec's `kind` is the separation the frontends route by. OPERATION
is an enforceable contract: exactly ONE backend call of shape
`(session, raw argument text) -> the sentence to show` (Refused caught
the same way) — a frontend wires these generically through a typed
adapter table, so the type checker holds the promise. Anything that
returns data, needs a screen, an ask, paging, or the ledger is
INTERACTIVE: the frontend owns the sequence; every state touch inside
it is still a backend call. SYNTAX rows are typed like commands and
discoverable like them but dispatch as story language
(`backend.api.play.submit`) — their tokens and argument shapes are
DERIVED from `context.syntax` below, so the language is declared once.
Semantic argument parsing lives in the backend operations; a frontend
only splits the token. The terminal adds its keys section and shortcut
column; a web palette binds (or skips) medium-bound commands.
"""

import enum
from dataclasses import dataclass

from otaku.context import syntax
from otaku.context.syntax import is_command

__all__ = [
    "COMMANDS",
    "GROUP_LABELS",
    "PROSE_DESCRIPTION",
    "PROSE_GROUP",
    "PROSE_LABEL",
    "CommandKind",
    "CommandSpec",
    "find",
    "is_command",
]

# The explainer /help opens the playing group with — prose is the
# surface's real first row, in both frontends' chat boxes. It is not a
# command and has no spec: what a help page needs is the label to give
# it, the group it opens, and the sentence.
PROSE_LABEL = "PROMPT"
PROSE_GROUP = "playing"
PROSE_DESCRIPTION = "Your character speaks or acts; the model continues the scene — sent verbatim"

# What each group is called, in the table's own order. Every group has a
# name: a heading is how a reader finds a command they cannot spell, and
# the two rows about otaku itself are no less findable than the rest. The
# wording is shared — the punctuation and the case around it are each
# frontend's drawing.
GROUP_LABELS: dict[str, str] = {
    "playing": "Playing",
    "inline": "Inside a prompt",
    "stories": "Stories",
    "lore": "Lore",
    "inspect": "Inspect",
    "transfer": "Import/export",
    "settings": "Models and settings",
    "meta": "Meta",
}


class CommandKind(enum.Enum):
    """The separation the frontends route by (see the module docstring)."""

    OPERATION = "operation"
    INTERACTIVE = "interactive"
    SYNTAX = "syntax"


@dataclass(frozen=True)
class CommandSpec:
    """One row of the surface. `args` is the argument shape as /help
    spells it ("NAME[: HINT]", "[N]"); a bracketed shape is optional and
    the bare command is complete as it stands."""

    token: str
    args: str
    description: str
    group: str
    kind: CommandKind


def _direction(token: str, description: str) -> CommandSpec:
    """A direction's row: token and argument shape read off the Line
    class that owns them — one declaration, in `context.syntax`."""
    return CommandSpec(
        token, syntax.DIRECTIONS[token].args, description, "playing", CommandKind.SYNTAX
    )


def _inliner(token: str, description: str) -> CommandSpec:
    """An inliner's row, its token checked against `context.syntax`. The
    `… ` prefix is deliberately part of the identity: `/ooc` opens a
    line AND closes one, and the two surfaces must not collide in
    `find` — the ellipsis is how the old help kept them apart too."""
    assert token in syntax.INLINERS
    return CommandSpec(f"… {token}", "TEXT", description, "inline", CommandKind.SYNTAX)


# fmt: off
COMMANDS: tuple[CommandSpec, ...] = (
    # Playing
    _direction("/me", "Send PROMPT, hinting the model that you write as NAME"),
    _direction("/you", "Tell the model to play NAME; optional HINT rides the turn"),
    _direction("/ooc", "Talk to the model out of character"),
    CommandSpec("/undo", "", "Discard the last turn", "playing", CommandKind.INTERACTIVE),
    CommandSpec("/regen", "", "Re-run the last prompt (mid-stream: cancel + regen)", "playing", CommandKind.INTERACTIVE),
    CommandSpec("/last", "[N]", "Show the last N turns (default 5) — a clean view after undos, regens, etc.", "playing", CommandKind.INTERACTIVE),
    CommandSpec("/clear", "", "Clear the screen", "playing", CommandKind.INTERACTIVE),
    # Inside a prompt
    _inliner("/ooc", "An aside out of character"),
    _inliner("/cue", "Steer just the next reply — not kept in context afterwards"),
    # Stories
    CommandSpec("/stories", "", "Browse stories, resume an old one", "stories", CommandKind.INTERACTIVE),
    CommandSpec("/fork", "[TITLE]", "Continue in a copy of this story; the original stays", "stories", CommandKind.OPERATION),
    CommandSpec("/system", "<text | FILE>", "Set the system prompt for this story — either directly or from a file", "stories", CommandKind.INTERACTIVE),
    CommandSpec("/title", "NEW", "Set the story title", "stories", CommandKind.OPERATION),
    CommandSpec("/new", "[TITLE]", "Clear context and start a new story", "stories", CommandKind.OPERATION),
    # Lore
    CommandSpec("/lore", "", "Browse and edit the memory: scenes, cast, journals", "lore", CommandKind.INTERACTIVE),
    CommandSpec("/cast", "", "The same browser, opened directly on the cast", "lore", CommandKind.INTERACTIVE),
    CommandSpec("/extract", "", "Extract lore from the recent messages now; triggered automatically after 5 minutes of inactivity", "lore", CommandKind.INTERACTIVE),
    CommandSpec("/merge", "A into B", "Fold a duplicate character into the real one", "lore", CommandKind.OPERATION),
    # Inspect
    CommandSpec("/context", "", "Preview the next request (assembled prompt + budgets)", "inspect", CommandKind.INTERACTIVE),
    CommandSpec("/balance", "", "Account balance of cloud providers", "inspect", CommandKind.OPERATION),
    CommandSpec("/usage", "[all]", "Tokens spent on this story (or everything)", "inspect", CommandKind.OPERATION),
    CommandSpec("/info", "", "Show details about the current model + session", "inspect", CommandKind.OPERATION),
    # Import/export
    CommandSpec("/card", "FILE [NAME]", "Import a character card (PNG or JSON) into this story — NAME renames them", "transfer", CommandKind.INTERACTIVE),
    CommandSpec("/import", "FILE", "Import a story: an otaku export, SillyTavern chat (.jsonl), or plain text", "transfer", CommandKind.INTERACTIVE),
    CommandSpec("/export", "[FILE]", "Export the whole story to Markdown (memory + messages)", "transfer", CommandKind.INTERACTIVE),
    # Models and settings
    CommandSpec("/model", "[PROVIDER/MODEL]", "Switch model", "settings", CommandKind.INTERACTIVE),
    CommandSpec("/set think", "<level>", "Thinking effort for the model: on|off|none|low|medium|high|max|default", "settings", CommandKind.OPERATION),
    CommandSpec("/set parameter", "<name> <val>", "Set an inference parameter for the model; no <val> shows it, <val> = reset returns the default", "settings", CommandKind.OPERATION),
    CommandSpec("/set verbose", "on|off", "Show the stats line after each reply", "settings", CommandKind.OPERATION),
    CommandSpec("/set autocorrect", "on|off", "Settle a character name you type in /you and /me commands to the cast's own spelling", "settings", CommandKind.OPERATION),
    CommandSpec("/set notification", "on|off", "Play a sound when a reply lands (the sound is configs/config.toml's notification_sound)", "settings", CommandKind.OPERATION),
    # Meta
    CommandSpec("/help", "", "Show this help", "meta", CommandKind.INTERACTIVE),
    CommandSpec("/bye", "", "Exit", "meta", CommandKind.INTERACTIVE),
)
# fmt: on


def find(token: str) -> CommandSpec | None:
    """The spec a typed line's head names — the longest match wins, so
    "/set think medium" finds the "/set think" row; None for an unknown
    command (bare "/set" included: the family's usage line is composed
    by the frontend FROM this table, never freehand). Inliner rows
    (`… /ooc`) never match — they close a line, they do not open one."""
    words = token.split()
    for depth in (2, 1):
        head = " ".join(words[:depth])
        for spec in COMMANDS:
            if spec.token == head:
                return spec
    return None
