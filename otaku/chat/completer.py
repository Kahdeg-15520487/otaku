"""Completion at the prompt: two menus, one for each slash surface.

Everything completed here is slash-triggered, and there are exactly two
kinds. A line that STARTS with a slash is a command, and `CommandCompleter`
walks the command tree over it — descriptions from /help, a `PATH_LEAF`
node handing the argument to `chat.pathcomplete`. A slash token typed
INSIDE a played line is an inliner, and `InlinerCompleter` offers those.
`SlashCompleter` is the one registered with the prompt; it picks whichever
surface applies and yields nothing when neither does.

The two are mutually exclusive by construction: `applies` asks the same
question from opposite sides, so on ordinary prose both stay silent and the
menu never pops mid-sentence. `menu_partial` answers, for either, which
token is being completed — the prompt needs that to anchor the menu and to
decide whether a menu can be open at all, and it must not have to know
which surface it is.
"""

import re
from collections.abc import Iterator
from typing import Any, Self

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from otaku.chat import pathcomplete
from otaku.chat.commands import (
    PATH_LEAF,
    CompletionTree,
    completion_tree,
    describe_command,
    inliner_menu,
)


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

    def __init__(self, tree: CompletionTree) -> None:
        self.tree = tree

    @staticmethod
    def applies(text_before_cursor: str) -> bool:
        return text_before_cursor.lstrip().startswith("/")

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
            if node == PATH_LEAF:
                break  # further tokens are path text (spaces in filenames)
            token = match.group(0)
            if not isinstance(node, dict) or token not in node:
                return
            node = node[token]
            if node == PATH_LEAF:
                # The argument begins at the first non-space char after this
                # token — sliced from the raw line, so spaces survive.
                rest = text[match.end() :]
                arg_start = match.end() + (len(rest) - len(rest.lstrip()))
            if node is None:
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
        yield from _rows(menu, self.partial(text))


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
        yield from _rows(self.menu, self.partial(document.text_before_cursor))


class SlashCompleter(Completer):
    """The completer the prompt registers. prompt_toolkit takes exactly
    one, so the choice between the two menus is made here rather than by
    either of them."""

    def __init__(self, surfaces: tuple[_Surface, ...]) -> None:
        self.surfaces = surfaces

    @classmethod
    def build(cls) -> Self:
        """A completer over the current command table."""
        return cls((CommandCompleter(completion_tree()), InlinerCompleter(inliner_menu())))

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        for surface in self.surfaces:
            if surface.applies(document.text_before_cursor):
                yield from surface.get_completions(document, complete_event)
                return


# The surfaces as line-level questions, which need no tree — asked in this
# order, and at most one answers.
_SURFACES: tuple[type[_Surface], ...] = (CommandCompleter, InlinerCompleter)


def menu_partial(text_before_cursor: str) -> str | None:
    """The token being completed at the cursor, on whichever surface owns
    it; None when neither does and no menu belongs here. Empty means a menu
    belongs with nothing typed into it yet — the prompt anchors on the
    length, so empty anchors at the cursor."""
    for surface in _SURFACES:
        if surface.applies(text_before_cursor):
            return surface.partial(text_before_cursor)
    return None


def _inliner_token(text_before_cursor: str) -> str | None:
    """The inliner token being typed at the cursor, its `/` included:
    `she looks up /c` → `"/c"`. None when the cursor is not in one."""
    if text_before_cursor.endswith((" ", "\t")):
        return None
    if text_before_cursor.lstrip().startswith("/"):
        return None
    tokens = list(re.finditer(r"\S+", text_before_cursor))
    if not tokens or not tokens[-1].group(0).startswith("/"):
        return None
    return tokens[-1].group(0)


def _rows(menu: dict[str, str], partial: str) -> Iterator[Completion]:
    """Menu rows, filtered by what is typed. Fixed column widths over the
    WHOLE menu, not the filtered subset, so it never resizes as you type."""
    key_width = max((len(key) for key in menu), default=0)
    meta_width = max((len(meta) for meta in menu.values()), default=0)
    for key, meta in menu.items():
        if key.startswith(partial):
            yield Completion(
                key,
                start_position=-len(partial),
                display=key.ljust(key_width),
                display_meta=meta.ljust(meta_width) if meta_width else None,
            )
