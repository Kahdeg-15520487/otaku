"""Provider lookup and fan-out.

The provider's section name selects its engine — the single-model
engines ("llamacpp", "koboldcpp"), the local managed registries
("ollama", "omlx", "lmstudio"), and the cloud catalogs ("openrouter",
"nanogpt") each get their native client; any other name is served as a
plain OpenAI endpoint. First-run autoconfiguration writes sections for
the local engines only — a cloud provider is added deliberately, keys
and all.

The `Registry` is composed by the backend package and injected
everywhere a client
is resolved: the configured providers, the request-log sink, the
smoothing flag, and the per-provider client cache. File persistence is
NOT here — the panel saves write through settings and then call
`update_provider`. Nothing here ever blocks or exits the app: an
unreachable provider is skipped in fan-outs, and a dead one costs its
own timeout — overlapped with the others, never the launch.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from otaku.providers.base import ManagedClient, OpenAIClient, Provider, RequestSink
from otaku.providers.clients.koboldcpp import KoboldCppClient
from otaku.providers.clients.llamacpp import LlamaCppClient
from otaku.providers.clients.lmstudio import LmStudioClient
from otaku.providers.clients.nanogpt import NanoGptClient
from otaku.providers.clients.ollama import OllamaClient
from otaku.providers.clients.omlx import OmlxClient
from otaku.providers.clients.openrouter import OpenRouterClient
from otaku.settings.providers import ProviderConfig

_T = TypeVar("_T")  # Registry.map's result type

# The client classes with a native API, by the provider name that
# activates them, in the model picker's canonical order; every other
# name gets the plain OpenAIClient.
CLIENTS: dict[str, type[OpenAIClient]] = {
    LlamaCppClient.kind: LlamaCppClient,
    KoboldCppClient.kind: KoboldCppClient,
    OllamaClient.kind: OllamaClient,
    OmlxClient.kind: OmlxClient,
    LmStudioClient.kind: LmStudioClient,
    OpenRouterClient.kind: OpenRouterClient,
    NanoGptClient.kind: NanoGptClient,
}


class Registry:
    def __init__(
        self,
        providers: dict[str, ProviderConfig],
        *,
        request_log: RequestSink | None = None,
        smooth: bool = True,
    ) -> None:
        self._providers = providers
        self._request_log = request_log
        self._smooth = smooth
        self._clients: dict[str, OpenAIClient] = {}

    def get_client(self, provider: str) -> OpenAIClient:
        """The named provider's client, cached — its engine chosen by the
        name (see the module docstring). Raises ValueError for an
        unconfigured provider."""
        if provider in self._clients:
            return self._clients[provider]
        config = self._providers.get(provider)
        if config is None:
            raise ValueError(f"no provider {provider!r} in the configuration")
        cls = CLIENTS.get(provider, OpenAIClient)
        client = cls(config, request_log=self._request_log, smooth=self._smooth)
        self._clients[provider] = client
        return client

    def configured(self) -> list[ProviderConfig]:
        """Every configured provider, name-sorted — reachable or not; the
        provider panel edits them all."""
        return [self._providers[name] for name in sorted(self._providers)]

    def update_provider(self, config: ProviderConfig) -> None:
        """Swap one provider's configuration for the running session and
        drop its cached client, so the next request is built against the
        new url and key. Persisting the change is the caller's business."""
        self._providers[config.name] = config
        self._clients.pop(config.name, None)

    def map(self, fn: Callable[[str, ProviderConfig], _T]) -> list[_T]:
        """Run `fn(provider, config)` for every configured provider
        concurrently, results in configuration order — one dead
        provider's timeout overlaps the others instead of adding to
        them. `fn` handles its own errors; an exception propagates."""
        items = list(self._providers.items())
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=len(items)) as pool:
            return list(pool.map(lambda item: fn(item[0], item[1]), items))

    def get_providers(self, skip: set[str] | None = None) -> tuple[list[Provider], set[str]]:
        """Every reachable provider with its models, plus the reachable
        set — the model picker's one query, each engine answering with
        its rich rows in one pass. `skip` names providers to leave out:
        the picker opens on the local engines' answers and fetches the
        cloud catalogs asynchronously, after the screen is up."""

        # Inner on purpose: the filter closes over the skip set.
        def gather(provider: str, config: ProviderConfig) -> tuple[str, Provider] | None:
            if skip and provider in skip:
                return None
            return self._gather(provider, config)

        results = [r for r in self.map(gather) if r is not None]
        return [row for _name, row in results], {name for name, _row in results}

    def _gather(self, provider: str, config: ProviderConfig) -> tuple[str, Provider] | None:
        """One provider's row, or None when it is unreachable."""
        client = self.get_client(provider)
        try:
            models = client.models(timeout=5.0)
        except Exception:
            return None
        return provider, Provider(config, models, isinstance(client, ManagedClient), client.local)


def autoconfigure_providers() -> dict[str, ProviderConfig]:
    """The first-run provider sections: one per local engine, present
    whether or not the engine is installed, each with its configuration
    (port, api key) detected from the machine. Runs only at the one
    first-run config write; the file is the user's thereafter."""
    configured = (
        LlamaCppClient.autoconfigure(),
        KoboldCppClient.autoconfigure(),
        OllamaClient.autoconfigure(),
        OmlxClient.autoconfigure(),
        LmStudioClient.autoconfigure(),
    )
    return {config.name: config for config in configured}
