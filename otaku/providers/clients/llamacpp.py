"""llama.cpp's bundled server (`llama-server`): one model per process,
chosen at launch — no load/unload. Chat rides the OpenAI protocol at /v1;
the loaded context window comes from the native /props endpoint."""

from otaku.providers.base import LocalSingleClient
from otaku.settings.providers import ProviderConfig


class LlamaCppClient(LocalSingleClient):
    kind = "llamacpp"
    label = "llama.cpp"
    # Thinking rides the two knobs the base sends a local engine: llama.cpp
    # ignores `reasoning_effort` and reads the template flag alone — and its
    # template allows thinking by default, so nothing sent means "sometimes".

    @classmethod
    def autoconfigure(cls) -> ProviderConfig:
        # Configured by launch flags — nothing on disk to detect a port
        # from, so the section is llama-server's standard default.
        return ProviderConfig(name=cls.kind, url="http://localhost:8080/v1")

    def _fetch_context_size(self, model: str) -> int | None:
        data = self._get_json("/props", timeout=1.5)
        if isinstance(data, dict):
            settings = data.get("default_generation_settings")
            if isinstance(settings, dict):
                context = settings.get("n_ctx")
                if isinstance(context, int) and context > 0:
                    return context
        return None
