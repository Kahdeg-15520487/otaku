"""The client's pure wire transforms, request side and answer side.

The prompt-cache marking promises: exactly the system row and the final
row carry `cache_control` (as content PARTS), everything between stays
a plain string, and only the 1h TTL is spelled — "5m" is the marking's
own default. The cached-tokens read promises: OpenAI's spelling wins,
Anthropic's own is the fallback, and anything else is None — never a
guess."""

from dataclasses import dataclass

from otaku.providers.base import _cache_marked, _cached_count


@dataclass(frozen=True)
class Turn:
    role: str
    body: str


class TestCacheMarked:
    def test_system_and_last_are_marked_and_the_middle_stays_plain(self) -> None:
        wire = _cache_marked(
            [
                Turn("system", "premise"),
                Turn("user", "hi"),
                Turn("assistant", "hello"),
                Turn("user", "go on"),
            ],
            "5m",
        )
        assert wire[0] == {
            "role": "system",
            "content": [
                {"type": "text", "text": "premise", "cache_control": {"type": "ephemeral"}}
            ],
        }
        assert wire[1] == {"role": "user", "content": "hi"}
        assert wire[2] == {"role": "assistant", "content": "hello"}
        assert wire[3] == {
            "role": "user",
            "content": [{"type": "text", "text": "go on", "cache_control": {"type": "ephemeral"}}],
        }

    def test_without_a_system_row_only_the_last_is_marked(self) -> None:
        wire = _cache_marked(
            [Turn("user", "hi"), Turn("assistant", "hello"), Turn("user", "on")], "5m"
        )
        assert wire[0] == {"role": "user", "content": "hi"}
        assert isinstance(wire[-1]["content"], list)

    def test_a_single_message_is_marked_once(self) -> None:
        # One row is both first and last; it must not be marked twice.
        (only,) = _cache_marked([Turn("user", "hi")], "5m")
        assert only["content"] == [
            {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
        ]

    def test_a_lone_system_row_is_marked_once(self) -> None:
        (only,) = _cache_marked([Turn("system", "premise")], "5m")
        assert isinstance(only["content"], list)
        assert len(only["content"]) == 1

    def test_the_hour_ttl_is_spelled_and_the_default_is_not(self) -> None:
        five = _cache_marked([Turn("user", "hi")], "5m")
        hour = _cache_marked([Turn("user", "hi")], "1h")
        assert five[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert hour[0]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


class TestCachedCount:
    def test_the_openai_spelling_wins(self) -> None:
        usage = {"prompt_tokens": 9, "prompt_tokens_details": {"cached_tokens": 4}}
        assert _cached_count(usage) == 4

    def test_the_anthropic_spelling_is_the_fallback(self) -> None:
        assert _cached_count({"prompt_tokens": 9, "cache_read_input_tokens": 4}) == 4

    def test_a_details_block_shadows_the_fallback(self) -> None:
        # A details block without the count is an engine that reports the
        # block, not the cache — the other spelling is not consulted.
        usage = {"prompt_tokens_details": {}, "cache_read_input_tokens": 4}
        assert _cached_count(usage) is None

    def test_anything_else_is_none(self) -> None:
        assert _cached_count({"prompt_tokens": 9}) is None
        assert _cached_count({"prompt_tokens_details": {"cached_tokens": "4"}}) is None
