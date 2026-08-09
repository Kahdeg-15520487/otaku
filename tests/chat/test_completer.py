"""Which completion menu belongs at the cursor, and what it filters by.

Two surfaces, asked the same two questions. `applies` decides which one is
in play — a line opening with a slash is the command menu's, a slash token
being typed inside prose is the inliner menu's, and ordinary prose is
neither's, so the menu never pops mid-sentence. `partial` is the token
being completed, empty when a menu belongs with nothing typed into it yet.

`menu_partial` is the two of them as one question, which is what the prompt
asks: it must anchor the menu and decide whether one can be open at all
without knowing which surface answered.
"""

from otaku.chat.completer import CommandCompleter, InlinerCompleter, menu_partial


class TestInlinerSurface:
    def test_a_slash_after_a_word_opens_it(self) -> None:
        assert InlinerCompleter.partial("she looks up /") == "/"

    def test_a_partly_typed_inliner_is_the_filter(self) -> None:
        assert InlinerCompleter.partial("she looks up /c") == "/c"

    def test_a_fully_typed_inliner_is_still_the_token(self) -> None:
        assert InlinerCompleter.partial("she looks up /cue") == "/cue"

    def test_past_the_space_the_token_is_finished(self) -> None:
        assert InlinerCompleter.applies("she looks up /cue ") is False

    def test_the_inliners_own_text_is_not_a_token(self) -> None:
        assert InlinerCompleter.applies("she looks up /cue keep") is False

    def test_prose_alone_opens_nothing(self) -> None:
        assert InlinerCompleter.applies("she looks up") is False

    def test_an_empty_line_opens_nothing(self) -> None:
        assert InlinerCompleter.applies("") is False

    def test_a_command_line_belongs_to_the_other_surface(self) -> None:
        assert InlinerCompleter.applies("/cu") is False
        assert InlinerCompleter.applies("  /cu") is False

    # Prose keeps its slashes: the slash must follow whitespace.
    def test_a_slash_inside_a_word_opens_nothing(self) -> None:
        assert InlinerCompleter.applies("she looks up and/") is False

    def test_a_url_opens_nothing(self) -> None:
        assert InlinerCompleter.applies("read https://") is False

    def test_a_date_opens_nothing(self) -> None:
        assert InlinerCompleter.applies("on 24/") is False

    def test_a_slash_typed_after_a_space_does_open_it(self) -> None:
        # The rule's one cost: a slash following a space cannot be told
        # apart from one starting a command, so a spaced "and /or" opens the
        # menu for a keystroke. The next character filters every row away.
        assert InlinerCompleter.partial("and /") == "/"


class TestCommandSurface:
    def test_a_slash_line_is_its_own(self) -> None:
        assert CommandCompleter.applies("/me") is True

    def test_leading_space_still_counts(self) -> None:
        assert CommandCompleter.applies("  /me") is True

    def test_prose_is_not_its_own(self) -> None:
        assert CommandCompleter.applies("she looks up /") is False

    def test_the_last_word_is_the_filter(self) -> None:
        assert CommandCompleter.partial("/set thi") == "thi"

    def test_after_a_space_nothing_is_typed_yet(self) -> None:
        assert CommandCompleter.partial("/set ") == ""


class TestMenuPartial:
    def test_a_command_line_answers(self) -> None:
        assert menu_partial("/me") == "/me"

    def test_an_argument_about_to_be_typed_answers_empty(self) -> None:
        # Empty is not None: a menu belongs, and it anchors at the cursor.
        assert menu_partial("/set ") == ""

    def test_an_inliner_answers(self) -> None:
        assert menu_partial("she looks up /c") == "/c"

    def test_prose_answers_with_no_menu(self) -> None:
        assert menu_partial("she looks up") is None

    def test_the_two_surfaces_never_both_answer(self) -> None:
        for text in ("/me", "  /set ", "she looks up /c", "she looks up", "", "and/or"):
            answered = [s for s in (CommandCompleter, InlinerCompleter) if s.applies(text)]
            assert len(answered) <= 1, text
