"""The generic provider: any server behind the OpenAI protocol, by url
and key, over the protocol alone. Models come from /models — a window
read when the listing carries `context_length`, the extension the
catalogs share — and turns stream from /chat/completions. Nothing an
engine's own API would add: no load state, no sizes, no warm-up (the url
may name a hosted catalog, where a warm-up bills a window for one
token), and the window otherwise unknown. The one provider a reader
configures entirely by hand, so it has no first-run section."""

from otaku.providers.base import ModelInfo, OpenAIClient


class GenericClient(OpenAIClient):
    kind = "generic"
    label = "Generic OpenAI provider"
    # `locality` stays UNKNOWN: a url says nothing about where it runs.

    def _list(self, timeout: float) -> list[ModelInfo]:
        return self._catalog(timeout)
