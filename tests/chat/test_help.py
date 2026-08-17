"""What the command surface tells the rest of the app about a row.

`needs_argument` answers whether a command is incomplete as it stands, and
the answer comes from its `_HELP_ROWS` label — the same row the menu shows
as its description — so the two can never disagree about what a command
takes. A required follower leaves the line unfinished; a bracketed one is
optional, which means the bare command is both valid and the usual thing
meant, and Enter should send it rather than reach for the rarer option.

`command_tokens` reads the same labels for the names alone: the vocabulary
display picks commands out by. A label that is a key at the prompt rather
than a command ("Up / Down", `@`) must not contribute one.

`shortcut` reads the row's other column — the key that runs the command
without typing it — which the menu shows beside the name, so the faster
way is learned where the slower one is being used.
"""

from otaku.chat.help import command_tokens, needs_argument, shortcut


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


class TestShortcut:
    def test_a_command_with_a_key_reports_it(self) -> None:
        assert shortcut(("/undo",)) == "Ctrl+U"
        assert shortcut(("/model",)) == "Ctrl+O"

    def test_a_command_without_one_reports_nothing(self) -> None:
        for command in ("/me", "/new", "/card", "/extract"):
            assert shortcut((command,)) == "", command

    def test_an_unknown_command_reports_nothing(self) -> None:
        assert shortcut(("/nonsense",)) == ""

    def test_a_subcommand_takes_its_own_row(self) -> None:
        # `/set think` has no key of its own, and must not inherit one.
        assert shortcut(("/set", "think")) == ""


class TestCommandTokens:
    def test_names_every_command_the_help_lists(self) -> None:
        tokens = command_tokens()
        for command in ("/me", "/you", "/ooc", "/cue", "/undo", "/set", "/info", "/bye"):
            assert command in tokens, command

    def test_holds_each_name_once(self) -> None:
        # `/ooc` is written twice — opening a line, and inside one.
        tokens = command_tokens()
        assert len(tokens) == len(set(tokens))

    def test_leaves_out_what_is_a_key_rather_than_a_command(self) -> None:
        # "Up / Down" carries a bare slash; `@` and '"""' carry none.
        tokens = command_tokens()
        assert "/" not in tokens
        assert all(token.startswith("/") and len(token) > 1 for token in tokens)

    def test_leaves_out_the_argument_placeholders(self) -> None:
        # A label is "/me NAME: PROMPT" — only its command is a token.
        for word in ("PROMPT", "NAME", "TEXT", "FILE", "@"):
            assert word not in command_tokens(), word
