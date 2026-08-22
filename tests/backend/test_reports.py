"""/context's preview rendering — the one place asserting printed text is
asserting the payload: the preview IS the request, shown verbatim."""

from otaku.backend.api.reports import _render_preview
from otaku.context.assembler import ContextShape, assemble
from otaku.store.schema import Message

SHAPE = ContextShape(head_messages=20, tail_messages=150, recap_header="", card_framing="")


class TestPreview:
    def test_shows_every_message_that_will_be_sent(self) -> None:
        prompt = assemble("Be terse.", [user("Hi."), assistant("Hello.")], 8192, shape=SHAPE)
        preview = _render_preview(prompt, dim="", reset="")
        assert "Be terse." in preview
        assert "Hi." in preview
        assert "Hello." in preview

    def test_marks_each_role(self) -> None:
        preview = _render_preview(assemble("", [user("Hi.")], 8192, shape=SHAPE), dim="", reset="")
        assert "[user]" in preview

    def test_reports_the_window(self) -> None:
        preview = _render_preview(assemble("", [user("Hi.")], 8192, shape=SHAPE), dim="", reset="")
        assert "8,192" in preview


def user(body: str) -> Message:
    return Message(role="user", body=body)


def assistant(body: str) -> Message:
    return Message(role="assistant", body=body)
