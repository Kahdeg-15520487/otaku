"""The colors otaku prints, in the shade the terminal's background asks for.

One `Theme` per background, `theme()` returning the one in force. Every
conditional color in the app reads it, so a shade is chosen once and named
once — the played block's band, the dialogue and command colors inline,
and every full-screen surface's palette.

A slot is a `Color`, resolved when the theme is built: the escape a
terminal wants and the name prompt_toolkit wants are the SAME decision,
and a caller should not have to make it again to paint with it.

Two kinds of spec go in, and the difference is deliberate:

- A **name** ("blue") compiles to one of the 16 palette slots, which the
  reader's own terminal theme shades. Used where text sits on the
  terminal's own background — the chat, the prompt — so otaku's colors
  belong to their theme rather than fighting it.
- A **#rrggbb** is exact everywhere. Used only where otaku must PAINT: the
  played block's band, the selected row's, and a dialog floating over a
  list it would otherwise show through. A slot the reader's theme could
  shade would make those unreadable against themselves.
- **"default"** hands the terminal back its own color, which is what makes
  a surface transparent. A picker is the terminal with a list on it, not a
  card laid over one.

An unanswered background reads as light: that is the shipped look, and a
pipe has no colors to clash with.
"""

import re
from dataclasses import dataclass, replace

from otaku.settings.config import Config
from otaku.terminal.query import background_is_dark

# A color NAME is the portable form: it compiles to one of the 16 palette
# slots, which every terminal on every platform renders and the reader's
# own theme shades. A #rrggbb is truecolor — exact everywhere, and
# therefore fixed.
_COLOR_NAMES = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
    "bright black": 90,
    "bright red": 91,
    "bright green": 92,
    "bright yellow": 93,
    "bright blue": 94,
    "bright magenta": 95,
    "bright cyan": 96,
    "bright white": 97,
}
# The session's theme, settled once by `use`; empty until then. A list so
# "not settled yet" needs no separate flag.
_CURRENT: list["Theme"] = []

_HEX = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")


@dataclass(frozen=True)
class Color:
    """One color in every form the app paints with, resolved once. The
    empty one is what an unreadable spec becomes: falsy, so a caller reading
    a hand-edited config falls back to its default instead of printing
    garbage at the reader."""

    fg: str = ""  # the SGR foreground escape
    bg: str = ""  # the SGR background escape
    style: str = ""  # what prompt_toolkit calls it, for a style sheet

    def __bool__(self) -> bool:
        return bool(self.fg)


@dataclass(frozen=True)
class Theme:
    """One background's colors, by what they MEAN rather than what they
    are — a surface names the role it needs and gets the right shade."""

    # Full-screen surfaces.
    panel: Color  # the pane a picker draws on
    raised: Color  # a dialog floating over it — opaque, or the list shows through
    text: Color  # body text, over whatever the terminal's background is
    # Text over something OTAKU painted — a band, a selected row, a dialog.
    # It cannot be `text`: that one is the terminal's own foreground, picked
    # to read against the terminal's background and not against ours. Paint
    # a background and you own both colors, or a theme that guessed the
    # background wrong turns white text onto a light grey band.
    ink: Color
    title: Color  # headings and the strong parts of a header
    # Secondary text is DIMMED, not recolored: the surfaces that use this
    # pair it with `dim` (SGR 2), which reduces the intensity of whatever
    # the text already is. A grey guessed against an unknown background
    # can vanish into it — reduced intensity cannot, because it is derived
    # from the color that was readable a moment ago.
    muted: Color  # secondary text — timestamps, help lines, borders
    selection: Color  # the band behind the selected row
    error: Color  # a failure the surface has to report
    ok: Color  # a confirmation (the model picker's tick)
    # Inline, over the terminal's own background.
    band: Color  # the played turn's block, drawn across the row
    placeholder: Color  # the empty prompt's hint
    dialogue: Color  # spoken lines
    dialogue_bold: bool  # weight, not color — but the look is one thing
    command: Color  # a slash command, wherever one is shown


def color(spec: str) -> Color:
    """A color name ("cyan", "bright blue") or a #rrggbb hex, resolved into
    every form the app paints with. The empty `Color` when the spec is
    neither. Names are read loosely — case, hyphens and underscores all
    spell the same slot in a hand-edited file."""
    name = " ".join(spec.strip().lower().replace("-", " ").replace("_", " ").split())
    if name == "default":
        # SGR 39/49: hand the terminal back its own colors. What makes a
        # surface transparent — the reader's background shows through it.
        return Color("\x1b[39m", "\x1b[49m", "default")
    slot = _COLOR_NAMES.get(name)
    if slot is not None:
        # The background code is the foreground one plus ten, which holds
        # for the palette slots and for truecolor alike.
        return Color(f"\x1b[{slot}m", f"\x1b[{slot + 10}m", f"ansi{name.replace(' ', '')}")
    match = _HEX.match(spec.strip())
    if match is None:
        return Color()
    r, g, b = (int(part, 16) for part in match.groups())
    return Color(f"\x1b[38;2;{r};{g};{b}m", f"\x1b[48;2;{r};{g};{b}m", spec.strip().lower())


# A picker is the terminal with a list on it, not a card laid over one:
# the pane, the body text and the headings are the reader's own colors, so
# the browser sits inside their theme instead of punching a hole in it.
# Only what MUST be painted is — the selected row's band, and a dialog,
# which floats over the list and would show it through.
LIGHT = Theme(
    panel=color("default"),
    raised=color("#ffffff"),
    text=color("default"),
    ink=color("#000000"),
    title=color("default"),
    muted=color("default"),
    selection=color("#e4e4e4"),
    error=color("#c0392b"),
    ok=color("#2f9e44"),
    band=color("#f0f0f0"),
    placeholder=color("#8a8a8a"),
    dialogue=color("blue"),
    dialogue_bold=False,
    command=color("magenta"),
)

DARK = Theme(
    panel=color("default"),
    raised=color("#1c1c1c"),
    text=color("default"),
    ink=color("#e4e4e4"),
    title=color("default"),
    muted=color("default"),
    selection=color("#3a3a3a"),
    error=color("#ff6b6b"),
    ok=color("#51cf66"),
    band=color("#303030"),
    # A mid grey reads as a hint against either background, so the hint is
    # the one slot that does not turn over.
    placeholder=color("#8a8a8a"),
    dialogue=color("bright blue"),
    dialogue_bold=False,
    command=color("bright magenta"),
)


def use(config: Config) -> None:
    """Settle the theme for the session: the background's own, with the
    user's `[ui]` colors laid over it. Called once, at the launch, before
    anything draws — which is also when the terminal gets asked what it
    looks like, and that ask READS STDIN. From the first prompt or picker
    on, stdin belongs to prompt_toolkit in raw mode, where a query eats the
    keystroke it lands on.

    A setting that is not a color resolves to the empty one and leaves the
    slot alone, so "auto" needs no special case and a typo costs nothing.
    This is where a whole theme read from a file will land."""
    base = DARK if background_is_dark() else LIGHT
    _CURRENT[:] = [
        replace(
            base,
            dialogue=color(config.dialogue_color) or base.dialogue,
            dialogue_bold=config.dialogue_bold,
        )
    ]


def theme() -> Theme:
    """The colors in force — cheap enough to call per rendered row.

    Before `use` has run there is no configured theme, only the
    background's: what a test, a script, or any code outside a launched
    session sees."""
    if _CURRENT:
        return _CURRENT[0]
    return DARK if background_is_dark() else LIGHT
