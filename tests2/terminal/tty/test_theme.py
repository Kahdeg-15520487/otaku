"""The color vocabulary, and the shades a background asks for.

`color`'s contract: a name becomes one of the 16 palette slots (portable,
and shaded by the reader's own theme), a #rrggbb becomes truecolor, and
anything else becomes the empty
`Color`, which is falsy, so a caller reading a hand-edited config falls
back to its default. Whatever goes in comes back resolved into every
form the app paints with at once — the foreground escape, the background
escape, and the name prompt_toolkit wants — because they are one decision.

`use` settles the session's theme: the background's own with the user's
`[ui]` colors laid over it, and a setting that is not a color leaving its
slot alone.

The shipped themes' contract is that they are COMPLETE and correctly
SPLIT: a surface naming a role gets a color for it on either background;
what otaku paints turns over with the background, and what it leaves to
the terminal is the same answer in both.
"""

from collections.abc import Iterator
from dataclasses import fields

import pytest

from otaku2.settings.config import UiSettings
from otaku2.terminal.tty.theme import _CURRENT, DARK, LIGHT, Color, Theme, color, theme, use


@pytest.fixture(autouse=True)
def unsettled() -> Iterator[None]:
    """Every case starts with no theme settled and leaves none behind:
    `use` writes module state, and one leaked out of here would decide
    another module's colors."""
    saved = list(_CURRENT)
    _CURRENT.clear()
    yield
    _CURRENT[:] = saved


class TestColor:
    def test_a_name_becomes_a_palette_slot(self) -> None:
        assert _fg("cyan") == "\x1b[36m"
        assert _fg("blue") == "\x1b[34m"
        assert _fg("bright blue") == "\x1b[94m"

    def test_names_are_read_loosely(self) -> None:
        # However someone spells it in a hand-edited config.
        assert _fg("Cyan") == _fg(" cyan ") == _fg("cyan")
        assert _fg("bright-blue") == _fg("bright_blue") == _fg("Bright  Blue")

    def test_a_hex_becomes_truecolor(self) -> None:
        assert _fg("#5869f6") == "\x1b[38;2;88;105;246m"
        assert _fg("#5869F6") == _fg("#5869f6")

    def test_the_background_escape_is_the_foreground_plus_ten(self) -> None:
        assert color("cyan").bg == "\x1b[46m"
        assert color("bright blue").bg == "\x1b[104m"
        assert color("#5869f6").bg == "\x1b[48;2;88;105;246m"

    def test_a_name_carries_prompt_toolkits_spelling(self) -> None:
        assert color("cyan").style == "ansicyan"
        assert color("bright magenta").style == "ansibrightmagenta"

    def test_a_hex_is_its_own_style(self) -> None:
        assert color("#5869F6").style == "#5869f6"

    def test_anything_else_is_the_emptycolor(self) -> None:
        # Falsy, so the caller falls back to its default; nothing is
        # printed at the reader.
        for spec in ("chartreuse", "#12345", "#gggggg", "", "auto"):
            assert not color(spec), spec


class TestThemes:
    def test_every_color_is_filled_on_both_backgrounds(self) -> None:
        for name, shipped in (("LIGHT", LIGHT), ("DARK", DARK)):
            for field in fields(Theme):
                shade = getattr(shipped, field.name)
                if not isinstance(shade, Color):
                    continue  # a weight, not a color
                assert shade.fg and shade.bg and shade.style, f"{name}.{field.name}"

    def test_what_otaku_chooses_turns_over_with_the_background(self) -> None:
        # A color otaku picks rather than inherits has to be picked for the
        # background it lands on, or one of the two makes it unreadable.
        for role in ("raised", "ink", "selection", "band"):
            assert getattr(LIGHT, role) != getattr(DARK, role), role

    def test_what_is_transparent_is_the_same_in_both(self) -> None:
        # These hand the terminal back its own colors, which is an answer
        # no background changes.
        for role in ("panel", "text", "title", "muted"):
            assert getattr(LIGHT, role) == getattr(DARK, role) == color("default"), role


def _fg(spec: str) -> str:
    return color(spec).fg


class TestUse:
    def test_a_configured_color_lays_over_the_background(self) -> None:
        use(_config(dialogue_color="cyan", dialogue_bold=True))
        assert theme().dialogue == color("cyan")
        assert theme().dialogue_bold is True
        # Everything the user did not name stays the background's own.
        assert theme().panel in (LIGHT.panel, DARK.panel)

    def test_a_setting_that_is_not_a_color_leaves_the_slot_alone(self) -> None:
        # Which is what makes "auto" unremarkable, and a typo harmless.
        for spec in ("auto", "chartreuse", ""):
            use(_config(dialogue_color=spec))
            assert theme().dialogue in (LIGHT.dialogue, DARK.dialogue), spec


def _config(*, dialogue_color: str = "auto", dialogue_bold: bool = False) -> UiSettings:
    return UiSettings(dialogue_color=dialogue_color, dialogue_bold=dialogue_bold, show_banner=True)
