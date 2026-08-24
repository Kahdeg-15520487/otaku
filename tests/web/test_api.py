"""What the page asks for, where the answer is pure.

Three promises `web.api` makes that running the app cannot show. An
argument is cut the way the terminal cuts one, so an untidily typed line
means the same thing in both frontends. A command line resolves to a
call — or to None — without the session, so an unknown token is refused
before anything queues. And every play event has a name on the wire,
with the union CLOSED — a new kind must fail here rather than arrive as
a silence.
"""

from typing import get_args

from otaku.backend.api.play import Declined, Done, Failed, PlayEvent, Recorded, Text, Thinking
from otaku.store.schema import Message
from otaku.web import api


class TestArgument:
    """`web.api._argument` — the terminal's own rule, copied and cited
    (`terminal.chat.bindings._argument`): everything after the token,
    verbatim from the first non-space character."""

    def test_a_one_word_token_leaves_the_rest(self) -> None:
        assert api._argument("/title The River", "/title") == "The River"

    def test_a_family_token_takes_both_words(self) -> None:
        assert api._argument("/set think medium", "/set think") == "medium"

    def test_untidy_spacing_still_finds_the_argument(self) -> None:
        # The reason this is not a fixed-width slice: that would hand the
        # backend "k  medium".
        assert api._argument("/set  think  medium", "/set think") == "medium"

    def test_spacing_inside_the_argument_is_kept(self) -> None:
        # Verbatim from the first non-space character — a story's title
        # is the reader's text, not the parser's.
        assert api._argument("/title  A  B", "/title") == "A  B"

    def test_a_bare_command_has_no_argument(self) -> None:
        assert api._argument("/fork", "/fork") == ""

    def test_trailing_space_is_no_argument(self) -> None:
        assert api._argument("/fork   ", "/fork") == ""


class TestEvent:
    """`web.api.event` — one play event as the page reads it."""

    def test_every_kind_has_a_name_on_the_wire(self) -> None:
        assert api.event(Recorded(Message(role="user", body="hi")))["type"] == "recorded"
        assert api.event(Thinking("hm"))["type"] == "thinking"
        assert api.event(Text("word"))["type"] == "text"
        assert api.event(Declined("no model"))["type"] == "declined"
        assert api.event(Failed("the provider hung up"))["type"] == "failed"
        assert api.event(Done(reply="done", stats="7 tok/s"))["type"] == "done"

    def test_the_union_is_covered(self) -> None:
        # The match is exhaustive by construction; this is what makes
        # ADDING a kind fail here instead of shipping as a silence.
        assert {kind.__name__ for kind in get_args(PlayEvent)} == {
            "Recorded",
            "Thinking",
            "Text",
            "Declined",
            "Failed",
            "Done",
        }

    def test_a_text_event_carries_its_text(self) -> None:
        assert api.event(Text("the light"))["text"] == "the light"

    def test_a_recorded_event_carries_the_turn(self) -> None:
        turn = api.event(Recorded(Message(id=4, role="user", body="I listen.")))["turn"]
        assert turn == {"id": 4, "role": "user", "body": "I listen."}


class TestAnswering:
    """`web.api.answering` — a command line resolved to its call, or to
    None, WITHOUT the session: the promise that lets the server refuse
    an unknown token from its own thread, before anything queues."""

    def test_a_wired_operation_resolves(self) -> None:
        assert api.answering("/title The River") is not None

    def test_a_family_row_resolves_by_its_two_word_token(self) -> None:
        assert api.answering("/set think medium") is not None

    def test_an_unknown_token_is_none(self) -> None:
        assert api.answering("/frobnicate") is None

    def test_a_declared_row_this_frontend_does_not_wire_is_none(self) -> None:
        # `/last` is INTERACTIVE and screen-only here: the table declares
        # it, but no sentence answers it, so the line is the page's to
        # route — never a 404 the reader meant as a screen.
        assert api.answering("/last 3") is None

    def test_story_language_is_never_an_answer(self) -> None:
        # A direction is story; routing it here would eat a played line.
        assert api.answering("/me Maren: I wave.") is None


class TestCommandsTable:
    """`web.api.commands_table` — what the page's help and menus read."""

    def test_every_row_carries_what_a_menu_needs(self) -> None:
        for row in api.commands_table()["rows"]:
            assert set(row) == {"token", "args", "description", "group", "kind"}
            assert row["token"] and row["description"] and row["group"]

    def test_every_group_is_named(self) -> None:
        table = api.commands_table()
        assert {row["group"] for row in table["rows"]} <= set(table["groups"])

    def test_the_prose_row_names_the_group_it_opens(self) -> None:
        table = api.commands_table()
        assert table["prose"]["group"] in table["groups"]
        assert table["prose"]["label"] and table["prose"]["description"]

    def test_what_the_page_may_answer_is_declared(self) -> None:
        # A token the page thinks it can answer but the table does not
        # declare is a button that would 404.
        table = api.commands_table()
        declared = {row["token"] for row in table["rows"]}
        assert set(table["answers"]) <= declared
