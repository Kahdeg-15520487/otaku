"""/context's preview rendering — the one place asserting printed text is
asserting the payload: the preview IS the request, shown verbatim."""

from otaku.chat.commands.inspect import _render_preview
from otaku.lore.assembler import assemble
from otaku.store.schema import Message


class TestPreview:
    def test_shows_every_message_that_will_be_sent(self) -> None:
        preview = _render_preview(assemble("Be terse.", [user("Hi."), assistant("Hello.")], 8192))
        assert "Be terse." in preview
        assert "Hi." in preview
        assert "Hello." in preview

    def test_marks_each_role(self) -> None:
        preview = _render_preview(assemble("", [user("Hi.")], 8192))
        assert "[user]" in preview

    def test_reports_the_window(self) -> None:
        preview = _render_preview(assemble("", [user("Hi.")], 8192))
        assert "8,192" in preview


def user(body: str) -> Message:
    return Message(role="user", body=body)


def assistant(body: str) -> Message:
    return Message(role="assistant", body=body)
