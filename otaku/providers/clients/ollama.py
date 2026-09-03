"""Ollama: the model registry, load/unload, sizes, and context windows via
the native /api endpoints; chat rides the OpenAI protocol at /v1."""

import os

import httpx

from otaku.providers.base import ManagedClient, ModelInfo
from otaku.settings.providers import ProviderConfig


class OllamaClient(ManagedClient):
    kind = "ollama"
    label = "Ollama"

    @classmethod
    def autoconfigure(cls) -> ProviderConfig:
        """The first-run section, its host and port detected from
        OLLAMA_HOST — a remote server stays remote."""
        raw = os.environ.get("OLLAMA_HOST") or ""
        host = _parse_host(raw) or "localhost"
        port = _parse_port(raw) or 11434
        url = f"http://{host}:{port}/v1"
        return ProviderConfig(name=cls.kind, url=url, keep_alive="24h")

    def load_model(self, model: str) -> None:
        body = {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": self.config.keep_alive or "24h",
        }
        response = httpx.post(
            f"{self.config.base_url}/api/generate",
            json=body,
            headers=self._headers,
            timeout=None,
        )
        response.raise_for_status()

    def unload_model(self, model: str) -> None:
        body = {"model": model, "prompt": "", "stream": False, "keep_alive": 0}
        response = httpx.post(
            f"{self.config.base_url}/api/generate",
            json=body,
            headers=self._headers,
            timeout=None,
        )
        response.raise_for_status()

    def _list(self, timeout: float) -> list[ModelInfo]:
        """One row per model: names and sizes from /api/tags, load state
        and the live window from /api/ps — one call each, however long
        the registry. An unloaded model carries NO window: Ollama sizes
        one at load time, from a server-wide default (tiered by VRAM, or
        OLLAMA_CONTEXT_LENGTH) clamped to the card's trained maximum, and
        no endpoint says what that default is. The card's figure is a
        ceiling, not the window — reported as one it budgeted stories
        past what the model could hold. A loaded model missing from the
        registry still belongs in the list."""
        sizes: dict[str, int] = {}
        data = self._get_json("/api/tags", timeout=timeout)
        if data is None:
            raise httpx.ConnectError(f"{self.config.name} is not answering /api/tags")
        for entry in data.get("models") or [] if isinstance(data, dict) else []:
            name = entry.get("name") or entry.get("model")
            size = entry.get("size")
            if isinstance(name, str):
                sizes[name] = size if isinstance(size, int) and size > 0 else 0
        running = self._running(timeout=1.5)
        # The listing just paid for every live window — seed the cache,
        # so the budget's ask for a loaded model never refetches it.
        for name, window in running.items():
            if window:
                self._context_cache[name] = window
        names = sorted(sizes) + sorted(set(running) - set(sizes))
        return [
            ModelInfo(
                name=name,
                size=sizes.get(name) or None,
                context=running.get(name) or None,
                loaded=name in running,
            )
            for name in names
        ]

    def _running(self, timeout: float) -> dict[str, int]:
        """The loaded models with their live windows, from /api/ps: name →
        context_length, 0 where the server does not state one."""
        running: dict[str, int] = {}
        data = self._get_json("/api/ps", timeout=timeout)
        if not isinstance(data, dict):
            return running
        for entry in data.get("models") or []:
            name = entry.get("name") or entry.get("model")
            if not name:
                continue
            window = entry.get("context_length")
            running[str(name)] = window if isinstance(window, int) and window > 0 else 0
        return running

    def _fetch_context_size(self, model: str) -> int | None:
        # Only a loaded model has a window (see `_list`): unknown until
        # then, and the base caches nothing for an unknown — so the first
        # turn, the one whose request loads the model, budgets on the
        # assembler's default, and the next ask reads the live figure.
        return self._running(timeout=1.5).get(model) or None


def _parse_host(value: str) -> str | None:
    """The host of a `host:port`, `http://host[:port]`, or bare `host`
    string; None when there is none (`:port`, a bare port, empty)."""
    trimmed = value.strip()
    for scheme in ("http://", "https://"):
        if trimmed.startswith(scheme):
            trimmed = trimmed[len(scheme) :]
            break
    trimmed = trimmed.split("/", 1)[0]
    host, colon, _ = trimmed.rpartition(":")
    if not colon:
        return None if not trimmed or trimmed.isdigit() else trimmed
    return host or None


def _parse_port(value: str) -> int | None:
    """The port of a `host:port`, `:port`, `http://host:port`, or bare
    `port` string; None when the tail is not a valid port."""
    try:
        port = int(value.rsplit(":", 1)[-1].strip())
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None
