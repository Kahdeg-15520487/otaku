"""The client's pure wire transforms, request side and answer side.

The prompt-cache marking promises: exactly the system row and the final
row carry `cache_control` (as content PARTS), everything between stays
a plain string, and only the 1h TTL is spelled — "5m" is the marking's
own default. The cached-tokens read promises: OpenAI's spelling wins,
Anthropic's own is the fallback, and anything else is None — never a
guess."""

from dataclasses import dataclass

from otaku.providers.base import OpenAIClient, _cache_marked, _cached_count
from otaku.settings.providers import ProviderConfig


@dataclass(frozen=True)
class Turn:
    role: str
    body: str


class TestApplyThinking:
    """The think setting onto the request, by the knobs a client declares
    (`thinking_knobs`): the OpenAI effort, the template flag, or both — and
    nothing at all for "default" or for an engine without the knob."""

    def test_the_openai_knob_carries_the_level_and_none(self) -> None:
        client = _client(("reasoning_effort",))
        assert _sent(client, "low") == {"reasoning_effort": "low"}
        assert _sent(client, "none") == {"reasoning_effort": "none"}

    def test_the_template_flag_enables_for_a_level_and_disables_for_none(self) -> None:
        client = _client(("enable_thinking",))
        assert _sent(client, "high") == {"chat_template_kwargs": {"enable_thinking": True}}
        assert _sent(client, "none") == {"chat_template_kwargs": {"enable_thinking": False}}

    def test_both_knobs_go_together(self) -> None:
        # Ollama obeys the effort and ignores the flag; llama.cpp and oMLX
        # the other way round — sent together, "none" lands on either.
        client = _client(("reasoning_effort", "enable_thinking"))
        assert _sent(client, "none") == {
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
        assert _sent(client, "medium") == {
            "reasoning_effort": "medium",
            "chat_template_kwargs": {"enable_thinking": True},
        }

    def test_default_sends_nothing(self) -> None:
        assert _sent(_client(("reasoning_effort", "enable_thinking")), None) == {}

    def test_an_engine_without_the_knob_gets_nothing_whatever_the_setting(self) -> None:
        client = _client(("reasoning_effort", "enable_thinking"), supports=False)
        assert _sent(client, "none") == {}
        assert _sent(client, "high") == {}


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


def _client(knobs: tuple[str, ...], *, supports: bool = True) -> OpenAIClient:
    """A client declaring `knobs`, the way each engine's class does."""

    class Client(OpenAIClient):
        supports_thinking = supports
        thinking_knobs = knobs

    return Client(ProviderConfig(name="test", url="http://localhost:1/v1"))


def _sent(client: OpenAIClient, think: str | None) -> dict[str, object]:
    body: dict[str, object] = {}
    client._apply_thinking(body, think)
    return body
