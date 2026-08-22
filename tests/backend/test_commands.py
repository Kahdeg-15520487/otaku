"""The shared command surface: what a spec tells the frontends about a
row, and how a typed line finds its spec.

`find` binds a typed line's head to its spec, the longest match winning
for the /set family; the inliner rows never match a line's start — they
close a line, they do not open one. What a row's `args` shape means for
a MENU — whether accepting it leaves the line open — is the frontend's
rule, held beside the menu that acts on it.
"""

from otaku.backend.commands import COMMANDS, CommandKind, find, help_text


class TestFind:
    def test_a_bare_token_finds_its_row(self) -> None:
        spec = find("/fork my title")
        assert spec is not None and spec.token == "/fork"

    def test_the_longest_match_wins_for_the_set_family(self) -> None:
        spec = find("/set think medium")
        assert spec is not None and spec.token == "/set think"

    def test_a_bare_set_is_unknown(self) -> None:
        # The family's usage line is composed by the frontend FROM the
        # table; the bare word names no row.
        assert find("/set") is None

    def test_an_unknown_word_finds_nothing(self) -> None:
        assert find("/nonesuch") is None

    def test_a_direction_finds_its_syntax_row(self) -> None:
        spec = find("/me Elara: hi")
        assert spec is not None and spec.kind is CommandKind.SYNTAX

    def test_an_inliner_row_never_matches_a_line_start(self) -> None:
        # `/cue` exists only behind the `…` of the inline group.
        assert find("/cue whisper") is None


class TestTable:
    def test_every_token_is_unique_per_surface(self) -> None:
        tokens = [spec.token for spec in COMMANDS]
        assert len(tokens) == len(set(tokens))

    def test_every_row_names_a_group_and_a_kind(self) -> None:
        for spec in COMMANDS:
            assert spec.group and isinstance(spec.kind, CommandKind), spec.token

    def test_the_inliners_live_behind_the_ellipsis(self) -> None:
        # Written in the table behind a `…`, which is how the mid-line
        # menu looks them up without colliding with the line-start /ooc.
        inliners = [spec for spec in COMMANDS if spec.token.startswith("… ")]
        assert {spec.token for spec in inliners} == {"… /ooc", "… /cue"}


class TestHelpText:
    def test_every_command_row_appears(self) -> None:
        text = help_text()
        for spec in COMMANDS:
            assert spec.token in text, spec.token

    def test_the_prose_row_opens_the_playing_group(self) -> None:
        lines = help_text().splitlines()
        prompt_row = next(i for i, line in enumerate(lines) if line.lstrip().startswith("PROMPT"))
        assert prompt_row == 1  # right under the first heading
