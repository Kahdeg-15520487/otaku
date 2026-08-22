"""The shared command surface: what a spec tells the frontends about a
row, and how a typed line finds its spec.

`needs_argument` answers whether a command is incomplete as it stands,
and the answer comes from its `args` shape — the same shape the menus
show — so the two can never disagree about what a command takes. A
required follower leaves the line unfinished; a bracketed one is
optional, which means the bare command is both valid and the usual
thing meant, and Enter should send it rather than reach for the rarer
option. `find` binds a typed line's head to its spec, the longest match
winning for the /set family; the inliner rows never match a line's
start — they close a line, they do not open one.
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


class TestNeedsArgument:
    def test_a_command_that_stands_alone_needs_nothing(self) -> None:
        for command in ("/undo", "/regen", "/clear", "/info", "/help", "/bye"):
            spec = find(command)
            assert spec is not None and spec.needs_argument is False, command

    def test_a_required_parameter_leaves_the_line_unfinished(self) -> None:
        for command in ("/me x", "/you x", "/ooc x", "/title x", "/import x", "/system x"):
            spec = find(command)
            assert spec is not None and spec.needs_argument is True, command
        merge = find("/merge A into B")
        assert merge is not None and merge.needs_argument is True

    def test_an_optional_parameter_leaves_it_finished(self) -> None:
        # The bracket is the whole signal, and the bare form is the one
        # usually meant: `/usage`, not `/usage all`.
        for command in ("/usage", "/last", "/fork", "/export", "/model"):
            spec = find(command)
            assert spec is not None and spec.needs_argument is False, command

    def test_the_set_family_needs_its_values(self) -> None:
        for line in ("/set think", "/set verbose", "/set parameter"):
            spec = find(line)
            assert spec is not None and spec.needs_argument is True, line

    def test_the_inliners_need_their_text(self) -> None:
        # Written in the table behind a `…`, which is how the mid-line
        # menu looks them up without colliding with the line-start /ooc.
        inliners = [spec for spec in COMMANDS if spec.token.startswith("… ")]
        assert {spec.token for spec in inliners} == {"… /ooc", "… /cue"}
        assert all(spec.needs_argument for spec in inliners)


class TestTable:
    def test_every_token_is_unique_per_surface(self) -> None:
        tokens = [spec.token for spec in COMMANDS]
        assert len(tokens) == len(set(tokens))

    def test_every_row_names_a_group_and_a_kind(self) -> None:
        for spec in COMMANDS:
            assert spec.group and isinstance(spec.kind, CommandKind), spec.token


class TestHelpText:
    def test_every_command_row_appears(self) -> None:
        text = help_text()
        for spec in COMMANDS:
            assert spec.token in text, spec.token

    def test_the_prose_row_opens_the_playing_group(self) -> None:
        lines = help_text().splitlines()
        prompt_row = next(i for i, line in enumerate(lines) if line.lstrip().startswith("PROMPT"))
        assert prompt_row == 1  # right under the first heading
