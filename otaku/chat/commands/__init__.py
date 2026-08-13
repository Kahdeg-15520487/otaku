"""Slash commands: the dispatch table and the completion tree.

`COMMANDS` pairs each command with its handler and its tab-completion
subtree. The names themselves — and their descriptions — belong to
`chat.help`, which every layer can read; this module answers to them.
"""

from collections.abc import Callable

from otaku.chat.commands import card, inspect, lore, meta, playing, settings, stories, transfer
from otaku.chat.framing import FRAMING_COMMANDS, FRAMING_INLINERS, framing
from otaku.chat.help import command_tokens, describe_command
from otaku.chat.session import KNOWN_PARAMS, Session
from otaku.store import Store

# A completion-tree leaf may be PATH_LEAF: "complete a filesystem path
# here" (behind an `@`; see completer.py). Paths may contain spaces —
# handlers read them from raw_args, never from split args, and strip the
# leading `@`.
PATH_LEAF = "<path>"

# A leaf may instead be NAME_LEAF: "a character name goes here" — the
# completer offers the story's cast, shaped per command (see
# completer._cast_rows). Names may contain spaces, so like a path the
# argument is read from the raw text, never from split tokens.
NAME_LEAF = "<name>"

CompletionTree = dict[str, "CompletionTree | str | None"]

CommandHandler = Callable[[Session, Store, list[str]], None]


def _set_tree() -> CompletionTree:
    """/set's completion subtree: each setting with its value menu."""
    levels = ("on", "off", "none", "low", "medium", "high", "max", "default")
    return {
        "think": {level: None for level in levels},
        "parameter": {p: {"reset": None} for p in KNOWN_PARAMS},
        "verbose": {"on": None, "off": None},
        "autocorrect": {"on": None, "off": None},
    }


# Each entry pairs the handler with its tab-completion subtree (None = no
# arguments), one entry per source line. Ordered as in `chat.help` so
# the menu lists commands in the same order as the help.
# fmt: off
COMMANDS: dict[str, tuple[CommandHandler, CompletionTree | str | None]] = {
    "/undo": (playing.cmd_undo, None),
    "/regen": (playing.cmd_regen, None),
    "/last": (playing.cmd_last, None),
    "/clear": (playing.cmd_clear, None),
    "/stories": (stories.cmd_stories, None),
    "/fork": (stories.cmd_fork, None),
    "/system": (stories.cmd_system, PATH_LEAF),
    "/title": (stories.cmd_title, None),
    "/new": (stories.cmd_new, None),
    "/lore": (lore.cmd_lore, None),
    "/cast": (lore.cmd_cast, None),
    "/extract": (lore.cmd_extract, None),
    "/merge": (lore.cmd_merge, NAME_LEAF),
    "/context": (inspect.cmd_context, None),
    "/usage": (inspect.cmd_usage, {"all": None}),
    "/balance": (inspect.cmd_balance, None),
    "/info": (inspect.cmd_info, None),
    "/card": (card.cmd_card, PATH_LEAF),
    "/import": (transfer.cmd_import, PATH_LEAF),
    "/export": (transfer.cmd_export, PATH_LEAF),
    "/model": (settings.cmd_model, None),
    "/set": (settings.cmd_set, _set_tree()),
    "/help": (meta.cmd_help, None),
    "/bye": (meta.cmd_bye, None),
}
# fmt: on

# What is dispatchable and what `chat.help` names must be the same set.
# This is the only module that sees both, and everything that dispatches
# imports it, so the two tables are checked the moment they meet. They
# have to agree in FOUR places: a command missing its row gets no /help
# line, a blank description in the menu, `needs_argument` False (so Enter
# sends it bare), and no highlighting — all of them silent. A row naming
# something that does not dispatch is the same drift the other way.
_DISPATCHABLE = set(COMMANDS) | set(FRAMING_COMMANDS) | set(FRAMING_INLINERS)
assert set(command_tokens()) == _DISPATCHABLE, (
    f"chat.help and the dispatch tables disagree: {_DISPATCHABLE ^ set(command_tokens())}"
)


def completion_tree() -> CompletionTree:
    """The slash-completion tree. Two sources, because the menu offers more
    than the dispatch table holds: the framing syntax (`/me`, `/you`,
    `/ooc`) is typed at the prompt like a command and must be discoverable
    like one, though nothing dispatches it. Descriptions still come from
    `chat.help` for both, so the menu and /help cannot disagree."""
    syntax: CompletionTree = {
        token: NAME_LEAF if cls.needs_name else None for token, cls in FRAMING_COMMANDS.items()
    }
    return {**syntax, **{name: subtree for name, (_, subtree) in COMMANDS.items()}}


def inliner_menu() -> dict[str, str]:
    """The mid-line menu: every inliner with its description. The names come
    from `framing.FRAMING_INLINERS`, which owns the syntax, and the text from
    `chat.help` like every other row's — an inliner is written there behind
    a `…`, so `/ooc` inside a line and `/ooc` opening one keep their separate
    meanings without colliding."""
    rows = {token: describe_command(("…", token)) for token in FRAMING_INLINERS}
    assert all(rows.values()), "every inliner needs a _HELP_ROWS line"
    return rows


# The playing commands manage the screen ledger themselves: two take an
# exchange back (a played prompt echoes its own block, in repl.submit). Every other command's output
# lands below the last exchange and invalidates the ledger — when it comes:
# the dispatch window watches for the write rather than assuming one (see
# `ScreenLedger.command_output`), so a picker left without a choice costs
# the exchanges above it nothing.
_PLAYING = {"/undo", "/regen", "/card"}


def dispatch(line: str, session: Session, store: Store) -> bool:
    """True when the line was a slash command (handled); False when it
    should be played as a prompt. A slash is not enough to make it a
    command: the framing syntax opens with one too, and those lines belong
    to the prompt, not here. The line lands verbatim in `session.raw_line`
    and its argument text in `session.raw_args` (free-text handlers keep
    the user's exact spacing — split-and-rejoin would collapse it)."""
    if not line.startswith("/") or framing(line).token:
        return False
    command, *args = line.split()
    session.raw_line = line
    split_once = line.split(None, 1)
    session.raw_args = split_once[1] if len(split_once) > 1 else ""
    entry = COMMANDS.get(command)
    with session.screen.command_output(manages_screen=command in _PLAYING):
        if entry is None:
            print(f"Unknown command: {command}. Type /help.")
            return True
        handler, _ = entry
        handler(session, store, args)
        return True
