"""OpenRouter: a hosted catalog over many upstream providers, speaking the
OpenAI protocol at https://openrouter.ai/api/v1. The base cloud listing
already harvests each model's `context_length` from the catalog."""

from otaku.providers.base import CloudClient
from otaku.settings.providers import ProviderConfig

# OpenRouter attributes a request to the app that sent it, by three
# headers it reads and nobody else does — the referer is the app's
# identity (without it there is no app at all), the title is how it is
# named, and the categories are which shelves it is browsed from. They
# say WHICH APP, never which user, and go to OpenRouter alone: the
# `_headers` hook is per client.
#
# The categories must come from OpenRouter's own vocabulary or they are
# dropped in silence, and two is the documented maximum per request —
# these are those two.
_ATTRIBUTION = {
    "HTTP-Referer": "https://otaku.sh",
    "X-OpenRouter-Title": "otaku",
    "X-OpenRouter-Categories": "roleplay,creative-writing",
}


class OpenRouterClient(CloudClient):
    kind = "openrouter"
    label = "OpenRouter"

    @property
    def _headers(self) -> dict[str, str]:
        return {**super()._headers, **_ATTRIBUTION}

    @classmethod
    def autoconfigure(cls) -> ProviderConfig:
        # The deliberate-add default: the catalog's one endpoint; the api
        # key is the user's to provide.
        return ProviderConfig(name=cls.kind, url="https://openrouter.ai/api/v1")

    def balance(self, timeout: float = 10.0) -> str | None:
        # /credits reports lifetime purchases and spend, in dollars.
        data = self._get_json("/v1/credits", timeout=timeout)
        credits = data.get("data") if isinstance(data, dict) else None
        if not isinstance(credits, dict):
            return None
        total = credits.get("total_credits")
        used = credits.get("total_usage")
        if isinstance(total, int | float) and isinstance(used, int | float):
            return f"${total - used:.2f}"
        return None

    def _key_works(self, timeout: float) -> bool:
        # /credits answers only a working key — the catalog is public.
        return self.balance(timeout=timeout) is not None
