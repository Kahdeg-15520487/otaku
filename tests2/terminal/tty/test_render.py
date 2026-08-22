"""The display vocabulary: `command_tokens` reads the shared table for
the names alone — what the highlighter picks commands out by. A label
that is a key at the prompt rather than a command must not contribute
one, and argument placeholders never do."""

from otaku2.terminal.tty.render import command_tokens


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
