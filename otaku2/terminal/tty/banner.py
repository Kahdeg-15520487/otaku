"""The chat banner: pixel-art mark beside the session's facts.

Two vertical pixels per character cell (▀ with a background colour), so a
16x12 sprite fits in 6 terminal rows next to six lines of text. Falls back
to plain ASCII when stdout isn't a TTY, and to no colour at all when
NO_COLOR is set — the banner is decoration, and must never corrupt a
redirected or piped session.
"""

import os
import shutil
import sys
from dataclasses import dataclass

from otaku2.backend.api.reports import BannerFacts
from otaku2.formatting import format_context, truncate_label
from otaku2.terminal.tty import BOLD, DEFAULT_BG, DIM, RESET


def _fg(color: int) -> str:
    """SGR 256-color foreground. The sprite is the one thing that paints by
    palette INDEX rather than by a theme role: it is a fixed picture, not
    part of the interface, so its colors are its own."""
    return f"\x1b[38;5;{color}m"


def _bg(color: int) -> str:
    """SGR 256-color background — the lower half of a sprite cell."""
    return f"\x1b[48;5;{color}m"


# A girl with long violet hair — the face reads at 16x12 because the eyes
# get two cells each (dark iris + a white shine pixel).
_SPRITE = [
    "....hhhhhhhh....",
    "..hhhhhhhhhhhh..",
    ".hhhhhhhhhhhhhh.",
    ".hhhhhhhhhhhhhh.",
    ".hhssssssssssbh.",
    ".hhseessseesshh.",
    ".hhsewsssewsshh.",
    ".hhssssmssssshh.",
    "..hhsssssssshh..",
    "...hhhhhhhhhh...",
    "....cccccccc....",
    "...cccccccccc...",
]
# 256-colour: h violet hair, s skin, e iris, w shine, m mouth, b blush,
# c collar.
_PALETTE = {"h": 140, "s": 223, "e": 236, "w": 231, "m": 167, "b": 217, "c": 60, ".": None}

_ASCII = [" /---\\ ", "| o o |", "|  _  |", " \\---/ ", "       "]

_MAX_WIDTH = 72

# The story line's width — the same cut the landed line uses
# (`formatting.truncate_label`), so the banner and the line under it can
# never disagree on a name.
_STORY_WIDTH = 50


@dataclass(frozen=True)
class _Style:
    """The banner's escape codes — or empty strings when colour is off."""

    accent: str = ""
    bold: str = ""
    dim: str = ""
    gray: str = ""
    rule: str = ""
    reset: str = ""


_COLOUR = _Style(
    accent=_fg(180),
    bold=BOLD,
    dim=DIM,
    gray=_fg(242),
    # Dimmed, not a grey: a fixed near-black read at 9.7:1 on a white
    # terminal and 2.2:1 on a black one, where the rule all but vanished.
    # Reduced intensity is derived from the text color, so it holds on
    # either — the same reason the pickers dim instead of recoloring.
    rule=DIM,
    reset=RESET,
)
_PLAIN = _Style()


def render(facts: BannerFacts) -> str:
    """The banner shown when a chat session opens — the facts are the
    backend's (`api.reports.banner`), the drawing is this module's."""
    style = _COLOUR if _colour() else _PLAIN

    details = [f"{style.gray}{facts.engine}{style.reset}" if facts.engine else ""]
    if facts.context:
        details.append(f"{style.gray}{format_context(facts.context)} context{style.reset}")
    detail = f"{style.dim} · {style.reset}".join(part for part in details if part)

    lines = [
        f"{style.accent}{style.bold}otaku{style.reset} {style.dim}v{facts.version}{style.reset}",
        f"{style.dim}a roleplay terminal client{style.reset}",
        f"{style.accent}{facts.model}{style.reset}",
        detail,
        f"{style.gray}{truncate_label(facts.story, _STORY_WIDTH)}{style.reset}"
        if facts.story
        else f"{style.dim}/help for commands{style.reset}",
    ]

    width = min(shutil.get_terminal_size((80, 24)).columns, _MAX_WIDTH)
    out = [""]
    for i, sprite_row in enumerate(_sprite_rows()):
        text = lines[i] if i < len(lines) else ""
        out.append(f"  {sprite_row}   {text}".rstrip())
    out.append(f"  {style.rule}{'─' * width}{style.reset}")
    return "\n".join(out)


def _colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.environ.get("OTAKU_COLOR") == "1"


def _sprite_rows() -> list[str]:
    """The sprite as terminal rows — each row packs two sprite lines into
    one cell using a half-block glyph."""
    if not _colour():
        return list(_ASCII)
    rows: list[str] = []
    for y in range(0, len(_SPRITE), 2):
        top = _SPRITE[y]
        bottom = _SPRITE[y + 1] if y + 1 < len(_SPRITE) else "." * len(top)
        row = ""
        for x in range(len(top)):
            upper, lower = _PALETTE.get(top[x]), _PALETTE.get(bottom[x])
            if upper is None:
                row += RESET + " " if lower is None else f"{_fg(lower)}{DEFAULT_BG}▄"
            elif lower is None:
                row += f"{_fg(upper)}{DEFAULT_BG}▀"
            else:
                row += f"{_fg(upper)}{_bg(lower)}▀"
        rows.append(row + RESET)
    return rows
