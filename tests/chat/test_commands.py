"""What the command table tells the menu about a row.

`needs_argument` answers whether a command is incomplete as it stands, and
the answer comes from its `_HELP_ROWS` label — the same row the menu shows
as its description — so the two can never disagree about what a command
takes. A required follower leaves the line unfinished; a bracketed one is
optional, which means the bare command is both valid and the usual thing
meant, and Enter should send it rather than reach for the rarer option.
"""

from otaku.chat.commands import needs_argument


class TestNeedsArgument:
    def test_a_command_that_stands_alone_needs_nothing(self) -> None:
        for command in ("/undo", "/regen", "/clear", "/info", "/help", "/bye"):
            assert needs_argument((command,)) is False, command

    def test_a_required_parameter_leaves_the_line_unfinished(self) -> None:
        for command in ("/me", "/you", "/ooc", "/title", "/import", "/system", "/merge"):
            assert needs_argument((command,)) is True, command

    def test_an_optional_parameter_leaves_it_finished(self) -> None:
        # The bracket is the whole signal, and the bare form is the one
        # usually meant: `/usage`, not `/usage all`.
        for command in ("/usage", "/last", "/fork", "/export", "/model"):
            assert needs_argument((command,)) is False, command

    def test_a_subcommand_counts_as_a_follower(self) -> None:
        assert needs_argument(("/set",)) is True

    def test_a_subcommand_can_need_one_of_its_own(self) -> None:
        assert needs_argument(("/set", "think")) is True
        assert needs_argument(("/set", "verbose")) is True

    def test_the_inliners_need_their_text(self) -> None:
        # Written in _HELP_ROWS behind a `…`, which is how the mid-line
        # menu looks them up without colliding with the line-start `/ooc`.
        assert needs_argument(("…", "/ooc")) is True
        assert needs_argument(("…", "/cue")) is True

    def test_a_completed_path_needs_nothing_more(self) -> None:
        assert needs_argument(("/usage", "all")) is False
        assert needs_argument(("/set", "verbose", "on")) is False

    def test_an_unknown_command_needs_nothing(self) -> None:
        assert needs_argument(("/nonesuch",)) is False
