"""Completion at the prompt: two menus, one for each slash surface.

Everything completed here is slash-triggered, and there are exactly two
kinds. A line that STARTS with a slash is a command, and `CommandCompleter`
walks the command tree over it — descriptions from /help, a `PATH_LEAF`
node handing the argument to `chat.pathcomplete`. A slash token typed
INSIDE a played line is an inliner, and `InlinerCompleter` offers those.
`SlashCompleter` is the one registered with the prompt; it picks whichever
surface applies and yields nothing when neither does. It also carries what
an open `\"\"\"` block has collected, so a line typed inside one is read as
the continuation it is rather than as the start of a message.

The two are mutually exclusive by construction: `applies` asks the same
question from opposite sides, so on ordinary prose both stay silent and the
menu never pops mid-sentence. `SlashCompleter.partial` answers, for either,
which token is being completed — the prompt needs that to anchor the menu
and to decide whether a menu can be open at all, and it must not have to
know which surface it is.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Self

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from otaku.chat import pathcomplete
from otaku.chat.commands import (
    NAME_LEAF,
    PATH_LEAF,
    CompletionTree,
    completion_tree,
    inliner_menu,
)
from otaku.chat.help import arguments, describe_command, needs_argument
from otaku.terminal import latin_key

# What a cast callable answers with: (name, one-line description) rows —
# the story's characters, for the commands whose argument is one.
Cast = Sequence[tuple[str, str]]


class MenuRow(Completion):
    """A menu row that also says whether the token it inserts leaves the
    line incomplete. The prompt adds a space when accepting one, so the rest
    can be typed straight on — and leaves a command that stands alone ready
    to send, optional parameters included."""

    def __init__(self, *args: Any, argument_required: bool, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.argument_required = argument_required


class _Surface(Completer):
    """One of the two menus. Beyond the completer protocol each answers two
    questions about the line alone: whether it is the surface in play, and
    which token is being completed on it — empty when a menu belongs here
    with nothing typed into it yet."""

    @staticmethod
    def applies(text_before_cursor: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def partial(text_before_cursor: str) -> str:
        raise NotImplementedError


class CommandCompleter(_Surface):
    """The line-start menu: the command tree, walked by whitespace-split
    tokens, each row carrying its /help line as the meta column. A
    `PATH_LEAF` node hands the argument to `chat.pathcomplete` — this owns
    only WHEN that fires (behind an explicit `@`, immediately and while
    typing) and the raw-line slicing that lets spaces survive in paths."""

    def __init__(self, tree: CompletionTree, cast: Callable[[], Cast] | None = None) -> None:
        self.tree = tree
        # The story's cast, looked up live: (name, one-line description)
        # rows for the commands whose argument is a character.
        self.cast = cast or (lambda: ())

    @staticmethod
    def applies(text_before_cursor: str) -> bool:
        return _opens_the_submission(text_before_cursor)

    @staticmethod
    def partial(text_before_cursor: str) -> str:
        """After a trailing space nothing is typed yet and the whole node is
        offered; otherwise the last whitespace-separated word filters it."""
        if text_before_cursor.endswith((" ", "\t")):
            return ""
        tokens = text_before_cursor.split()
        return tokens[-1] if tokens else ""

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        tokens = list(re.finditer(r"\S+", text))
        walked = tokens if text.endswith((" ", "\t")) else tokens[:-1]
        path = [match.group(0) for match in walked]

        node: Any = self.tree
        arg_start: int | None = None
        for match in walked:
            if node in (PATH_LEAF, NAME_LEAF):
                break  # further tokens are argument text (spaces survive)
            token = match.group(0)
            if not isinstance(node, dict) or token not in node:
                return
            node = node[token]
            if node in (PATH_LEAF, NAME_LEAF):
                # The argument begins at the first non-space char after this
                # token — sliced from the raw line, so spaces survive.
                rest = text[match.end() :]
                arg_start = match.end() + (len(rest) - len(rest.lstrip()))
            if node is None:
                return

        if node == NAME_LEAF:
            if arg_start is not None:
                yield from _cast_rows(path[0], text[arg_start:], self.cast())
            return

        if node == PATH_LEAF:
            # Paths complete behind an explicit `@`: the menu pops the
            # moment it is typed and filters while typing. Never on a bare
            # path — a directory listing under every keystroke of ordinary
            # text would be noise. The handlers strip the `@`; it is a
            # trigger, not part of the name.
            if arg_start is not None and text[arg_start:].startswith("@"):
                yield from pathcomplete.completions(text[arg_start + 1 :])
            return

        if not isinstance(node, dict):
            return

        menu = {key: describe_command((*path, key)) for key in node}
        yield from _rows(menu, self.partial(text), tuple(path))


class InlinerCompleter(_Surface):
    """The mid-line menu: the inliners a played line may close with.

    It applies while a slash token is being typed inside prose, and that
    token must open with a slash following whitespace — the same rule
    `framing` runs the inliner by. Ordinary prose therefore stays silent:
    in `and/or`, `he/she`, `24/08/2026` and `https://x.co/` the slash
    follows a non-space. Past a space the token is finished rather than
    being typed, and a line that opens with a slash is the other
    surface's."""

    def __init__(self, menu: dict[str, str]) -> None:
        self.menu = menu

    @staticmethod
    def applies(text_before_cursor: str) -> bool:
        return _inliner_token(text_before_cursor) is not None

    @staticmethod
    def partial(text_before_cursor: str) -> str:
        return _inliner_token(text_before_cursor) or ""

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        yield from _rows(self.menu, self.partial(document.text_before_cursor), ("…",))


class SlashCompleter(Completer):
    """The completer the prompt registers. prompt_toolkit takes exactly
    one, so the choice between the two menus is made here rather than by
    either of them."""

    def __init__(self, surfaces: tuple[_Surface, ...], prefix: Callable[[], str]) -> None:
        self.surfaces = surfaces
        self.prefix = prefix

    @classmethod
    def build(
        cls,
        prefix: Callable[[], str] = lambda: "",
        cast: Callable[[], Cast] | None = None,
    ) -> Self:
        """A completer over the current command table. `prefix` is what an
        open `\"\"\"` block has collected so far — the line being typed is
        read in the context of the message it belongs to, or every
        continuation line would look like the start of one. `cast` answers
        with the story's characters, looked up live for the commands whose
        argument is one."""
        return cls(
            (CommandCompleter(completion_tree(), cast), InlinerCompleter(inliner_menu())), prefix
        )

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        whole = Document(self.prefix() + document.text_before_cursor)
        for surface in self.surfaces:
            if surface.applies(whole.text_before_cursor):
                yield from surface.get_completions(whole, complete_event)
                return

    def partial(self, text_before_cursor: str) -> str | None:
        """The token being completed at the cursor, on whichever surface
        owns it; None when neither does and no menu belongs here. Empty
        means a menu belongs with nothing typed into it yet — the prompt
        anchors on the length, so empty anchors at the cursor."""
        whole = self.prefix() + text_before_cursor
        for surface in _SURFACES:
            if surface.applies(whole):
                return surface.partial(whole)
        return None


# The surfaces as line-level questions, which need no tree — asked in this
# order, and at most one answers.
_SURFACES: tuple[type[_Surface], ...] = (CommandCompleter, InlinerCompleter)


def _opens_the_submission(text_before_cursor: str) -> bool:
    """Whether the cursor sits on a slash that opens the whole submission —
    the only place a command can be typed. A newline before it means the
    line is a continuation inside a `\"\"\"` block, where the message has
    already begun and only an inliner can follow."""
    return "\n" not in text_before_cursor and text_before_cursor.lstrip().startswith("/")


def _inliner_token(text_before_cursor: str) -> str | None:
    """The inliner token being typed at the cursor, its `/` included:
    `she looks up /c` → `"/c"`. None when the cursor is not in one."""
    if text_before_cursor.endswith((" ", "\t")):
        return None
    if _opens_the_submission(text_before_cursor):
        return None
    tokens = list(re.finditer(r"\S+", text_before_cursor))
    if not tokens or not tokens[-1].group(0).startswith("/"):
        return None
    return tokens[-1].group(0)


def _cast_rows(command: str, segment: str, cast: Cast) -> Iterator[Completion]:
    """The cast offered where a command takes a character, shaped for the
    command: `/me` inserts `Name:` and keeps going (the prompt follows),
    `/you` inserts the bare name (the line is then complete — the hint is
    the rarer option, a colon away), and `/merge` completes both sides of
    `A into B`. `segment` is the raw argument text, so names with spaces
    filter whole; past a `:` the argument is content, and no menu belongs
    there."""
    if command == "/merge":
        _, sep, rest = segment.partition(" into ")
        if sep:
            yield from _name_rows(cast, rest, suffix="", required=False)
        else:
            yield from _name_rows(cast, segment, suffix=" into", required=True)
        return
    if ":" in segment:
        return
    if command == "/me":
        yield from _name_rows(cast, segment, suffix=":", required=True)
    else:
        yield from _name_rows(cast, segment, suffix="", required=False)


def _name_rows(cast: Cast, typed: str, *, suffix: str, required: bool) -> Iterator[Completion]:
    """One row per matching cast member: the name shown plain with the
    description as the meta column, the inserted text carrying whatever
    the command's shape needs after it (`:`, ` into`)."""
    wanted = typed.casefold()
    width = max((len(name) for name, _ in cast), default=0)
    for name, about in cast:
        if name.casefold().startswith(wanted):
            yield MenuRow(
                name + suffix,
                start_position=-len(typed),
                display=name.ljust(width),
                display_meta=about or None,
                argument_required=required,
            )


def _rows(menu: dict[str, str], partial: str, path: tuple[str, ...]) -> Iterator[Completion]:
    """Menu rows, filtered by what is typed. Fixed column widths over the
    WHOLE menu, not the filtered subset, so it never resizes as you type.
    `path` is what the keys hang off — the walked command tokens, or `…`
    for the inliners, which is how their /help rows are written."""
    # Each row reads as the line it starts: the command, then what it takes
    # — dimmed, because only the command is inserted. Widths are measured
    # over the WHOLE label so the description column still lines up.
    labels = {key: f"{key} {arguments((*path, key))}".rstrip() for key in menu}
    key_width = max((len(label) for label in labels.values()), default=0)
    meta_width = max((len(meta) for meta in menu.values()), default=0)
    for key, meta in menu.items():
        if key.startswith(latin_key(partial)):
            yield MenuRow(
                key,
                start_position=-len(partial),
                display=[
                    ("", key),
                    ("dim", labels[key][len(key) :]),
                    ("", " " * (key_width - len(labels[key]))),
                ],
                display_meta=meta.ljust(meta_width) if meta_width else None,
                argument_required=needs_argument((*path, key)),
            )
