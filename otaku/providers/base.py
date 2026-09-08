"""The OpenAI-compatible client — and the base of every ENGINE family
("engine" everywhere here: the model server — llama.cpp, Ollama, a cloud
catalog — never the application's backend package).

`OpenAIClient` speaks the OpenAI wire protocol: `/models` to list and
streaming `/chat/completions` to generate. That is the whole protocol
surface; a provider that is just an OpenAI endpoint is served by this
class as is. `models()` is the one listing call, returning rich
`ModelInfo` rows — the base fills only the names, and each engine family
fills what its native APIs know in one pass.

The families, one subclass each:

- `LocalSingleClient` — a single-model engine (llama.cpp, KoboldCpp):
  the server fronts one model chosen at its own launch, or none.
- `ManagedClient` — a local registry (Ollama, omlx, LM Studio) that can
  load and unload models on demand; the UI offers those actions exactly
  when a client `isinstance`-checks as one of these.
- `CloudClient` — a hosted catalog (OpenRouter, NanoGPT): models are
  listed with their context windows, never sized (no disk to weigh),
  and every row is simply available.

`chat_stream` yields typed chunks: `Thinking` deltas, `Text` deltas, and
a final `Stats`. Bursty output is re-timed into an even flow when
smoothing is on (see `providers.smoothing`); calls nobody watches pass
watched=False and skip it.
"""

import contextlib
import enum
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import httpx

from otaku.formatting import Money
from otaku.providers import smoothing
from otaku.settings.providers import ProviderConfig


@dataclass(frozen=True)
class ModelInfo:
    """One model as its provider reports it — the row every listing
    returns, filled as far as the engine's native API can see."""

    name: str
    size: int | None = None  # bytes on disk; local engines only
    context: int | None = None  # the model's context window, when reported
    loaded: bool = False


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Thinking:
    text: str


@dataclass(frozen=True)
class Stats:
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_seconds: float
    # The loaded context window, when the engine exposes it.
    context_max: int | None = None
    # Decode-only span: first emitted token → end of stream, excluding the
    # prefill — the honest tok/s denominator.
    generation_seconds: float | None = None
    # Of prompt_tokens, served from the provider's cache — None where the
    # provider reports nothing (a local engine, caching off).
    cached_tokens: int | None = None


Chunk = Text | Thinking | Stats


class Locality(enum.Enum):
    """Where a provider's server runs, as far as its CLIENT can tell —
    class knowledge, like `supports_thinking`. An engine's client knows
    (llama.cpp is on this machine, OpenRouter is not); the generic
    provider is a url and cannot. Every reader picks its safe side for
    UNKNOWN: what costs money or waits on the internet (the warm-up, a
    catalog fetch at a header's speed) treats it as REMOTE, what edits
    (the url) treats it as LOCAL, and a caption says neither."""

    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Provider:
    """One reachable provider with its models — what
    `Registry.get_providers` answers and the model picker lists."""

    config: ProviderConfig
    models: list[ModelInfo]
    can_load_unload: bool
    locality: Locality  # not LOCAL: nothing to size, no load state


class DeclinedError(RuntimeError):
    """The engine answered the request with a refusal or an in-stream
    error instead of content. str(e) carries the provider's own sentence.
    Its own type, so a caller can tell "the model declined" from a bug:
    a background pass skips the piece and moves on, the reply path shows
    the sentence."""


class RequestSink(Protocol):
    """Where requests and their answers are recorded — the injected log
    seam; the session's request log satisfies it. `record_request`
    returns the id the answer is later filed under."""

    def record_request(self, provider: str, purpose: str, body: dict[str, object]) -> str: ...

    def record_answer(
        self,
        provider: str,
        purpose: str,
        request_id: str,
        *,
        outcome: str,
        seconds: float,
        first_token_seconds: float | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        cached_tokens: int | None,
        text: str,
        thinking: str = "",
    ) -> None: ...


class WireMessage(Protocol):
    """What a chat request needs of a message: a role and its wire text.
    `store.schema.Message` satisfies it structurally."""

    @property
    def role(self) -> str: ...
    @property
    def body(self) -> str: ...


class OpenAIClient:
    # Every client names itself — the section key that selects it, and
    # how the provider panel captions it. The protocol is not a provider,
    # so the base declares the names and holds none.
    kind: ClassVar[str]
    label: ClassVar[str]
    # Whether the engine understands a request-level thinking knob —
    # class knowledge, not configuration. The OpenAI protocol itself has
    # `reasoning_effort`, so the base says yes; engines where thinking is
    # baked into the model declare False, and /set think refuses levels.
    supports_thinking: ClassVar[bool] = True
    # The request fields a think setting goes out on. `reasoning_effort`
    # is OpenAI's, which the hosted catalogs and Ollama read (Ollama
    # ignores the flag); `enable_thinking` is the chat template's flag,
    # sent in `chat_template_kwargs`, which llama.cpp's server and oMLX
    # read (both ignore the effort). A local engine gets BOTH, so "none"
    # lands on whichever of the two its server obeys.
    thinking_knobs: ClassVar[tuple[str, ...]] = ("reasoning_effort",)
    # Where the server runs (see `Locality`). The protocol alone cannot
    # say, so the base says UNKNOWN; the engine bases below know.
    locality: ClassVar[Locality] = Locality.UNKNOWN
    # Whether the engine honours explicit prompt-cache breakpoints
    # (`cache_control` on content parts — Anthropic's marking, forwarded
    # by OpenRouter). Class knowledge like `supports_thinking`; the
    # section's `prompt_cache` key modulates it ("off" | "5m" | "1h"),
    # never enables it where the engine cannot.
    cache_markers: ClassVar[bool] = False

    @classmethod
    def autoconfigure(cls) -> ProviderConfig:
        """The engine's default provider section: what the provider panel
        shows before an engine is configured, and what first-run writes
        for the local engines (each client says what it detects). The
        plain OpenAI client has no natural endpoint — a generic provider
        is configured by hand."""
        return ProviderConfig(name=cls.kind, url="")

    def __init__(
        self,
        config: ProviderConfig,
        *,
        request_log: RequestSink | None = None,
        smooth: bool = False,
    ) -> None:
        self.config = config
        self._request_log = request_log
        self._smooth = smooth
        self._context_cache: dict[str, int] = {}

    @property
    def _headers(self) -> dict[str, str]:
        """What every request to this provider carries: the protocol's
        bearer auth over the configured key, and whatever the engine's
        own service asks for on top (see `OpenRouterClient`). The scheme
        belongs here and not to the section — a provider is configured
        with a key, never with the way a key is presented on the wire.
        A SUBCLASS HOOK: the one door, so a header a subclass adds
        cannot miss a call site, and cannot reach another provider."""
        return {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}

    # ---------- the OpenAI protocol ----------

    def models(self, timeout: float = 10.0) -> list[ModelInfo]:
        """Every model this provider offers, as rich rows — the one
        listing call, never overridden. Each engine shapes its own rows
        in `_list`, the single override point; the base knows only the
        plain /models names."""
        return self._list(timeout)

    def model(self, name: str, timeout: float = 10.0) -> ModelInfo | None:
        """The listing row for one model — best effort: None when the
        provider does not offer it or cannot be reached."""
        try:
            rows = self.models(timeout)
        except Exception:
            return None
        for row in rows:
            if row.name == name:
                return row
        return None

    def _list(self, timeout: float) -> list[ModelInfo]:
        return [ModelInfo(name=name) for name in self._model_names(timeout)]

    def _model_names(self, timeout: float) -> list[str]:
        """The bare /models listing, sorted — raises when unreachable."""
        response = httpx.get(
            f"{self.config.url}/models",
            headers=self._headers,
            timeout=_timeout(timeout, connect=2.0),
        )
        response.raise_for_status()
        data = response.json()
        return sorted(str(m["id"]) for m in data.get("data", []))

    def _catalog(self, timeout: float, *, query: str = "") -> list[ModelInfo]:
        """The /models listing as rows, every one available (nothing to
        load, nothing to size), with the context window read where the
        server sends `context_length` — not the protocol's, but the
        extension the catalogs share. `query` is what a service wants
        appended to include the details. Raises when unreachable. The
        listing just paid for every window it carried, so the cache is
        seeded: the budget's ask never refetches what the picker
        brought home."""
        response = httpx.get(
            f"{self.config.url}/models{query}",
            headers=self._headers,
            timeout=_timeout(timeout, connect=2.0),
        )
        response.raise_for_status()
        rows = []
        for entry in response.json().get("data", []):
            context = entry.get("context_length")
            rows.append(
                ModelInfo(
                    name=str(entry["id"]),
                    context=context if isinstance(context, int) and context > 0 else None,
                    loaded=True,
                )
            )
        for row in rows:
            if row.context:
                self._context_cache[row.name] = row.context
        return sorted(rows, key=lambda row: row.name)

    def chat_stream(
        self,
        model: str,
        messages: Sequence[WireMessage],
        params: dict[str, object],
        *,
        think: str | None = None,
        timeout: float = 600.0,
        purpose: str = "chat",
        watched: bool = True,
        on_idle: Callable[[], None] | None = None,
    ) -> Iterator[Chunk]:
        """Stream one completion: Thinking and Text deltas, then a final
        Stats. `watched=False` for calls nobody watches — an accumulated
        string gains nothing from pacing, and the held lag would only
        delay their cancellation."""
        # The messages payload: plain strings — or, where the engine
        # honours cache breakpoints and the section has not said off,
        # the marked form (`_cache_marked`).
        wire: list[dict[str, object]]
        if self.cache_markers and self.config.prompt_cache != "off":
            wire = _cache_marked(messages, self.config.prompt_cache or "5m")
        else:
            wire = [{"role": m.role, "content": m.body} for m in messages]
        body: dict[str, object] = {
            "model": model,
            "messages": wire,
            "stream": True,
            "stream_options": {"include_usage": True},
            **params,
        }
        sent = dict(body)
        self._apply_thinking(sent, think)
        stream = self._request(model, sent, timeout, purpose)
        if sent != body:
            # The thinking knob rode along, and engines differ on it:
            # "none" cannot be sent to a model whose reasoning is
            # mandatory, and some engines reject the field outright —
            # both as a 400 before anything streams. One retry without
            # the knob leaves them their own default.
            stream = self._retry_without_thinking(stream, model, body, timeout, purpose)
        if watched and self._smooth:
            return smoothing.smoothen(stream, on_idle)
        return stream

    def _request(
        self, model: str, body: dict[str, object], timeout: float, purpose: str
    ) -> Iterator[Chunk]:
        """One logged attempt: the request recorded, its stream returned."""
        request_id = ""
        if self._request_log is not None:
            request_id = self._request_log.record_request(self.config.name, purpose, body)
        return self._stream(model, body, timeout, purpose, request_id)

    def _retry_without_thinking(
        self,
        stream: Iterator[Chunk],
        model: str,
        body: dict[str, object],
        timeout: float,
        purpose: str,
    ) -> Iterator[Chunk]:
        """Retry a thinking-carrying request that a 400 refused
        before anything streamed, as `body` — the same request with no
        thinking field, so the engine runs its own default. Only a
        stream that produced NOTHING falls back: a mid-stream failure
        has words on someone's screen, and a second take would repeat
        them."""
        yielded = False
        try:
            for chunk in stream:
                yielded = True
                yield chunk
        except GeneratorExit:
            # Deterministically, not at collection: cancel-and-keep
            # records the partial the moment the consumer lets go.
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            raise
        except httpx.HTTPStatusError as e:
            if yielded or e.response.status_code != 400:
                raise
            yield from self._request(model, body, timeout, purpose)

    def _stream(
        self, model: str, body: dict[str, object], timeout: float, purpose: str, request_id: str
    ) -> Iterator[Chunk]:
        start = time.monotonic()
        first_token_at: float | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        cached_tokens: int | None = None
        text: list[str] = []
        thoughts: list[str] = []
        recorded = False

        def answered(outcome: str) -> None:
            """File the answer under the request's log id — once, however
            the stream ends: the clean end, the consumer closing it (the
            cancel-and-keep door), or a transport failure. What had
            arrived rides along either way."""
            nonlocal recorded
            if recorded or self._request_log is None or not request_id:
                return
            recorded = True
            waited = (first_token_at - start) if first_token_at is not None else None
            self._request_log.record_answer(
                self.config.name,
                purpose,
                request_id,
                outcome=outcome,
                seconds=time.monotonic() - start,
                first_token_seconds=waited,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                text="".join(text),
                thinking="".join(thoughts),
            )

        try:
            with httpx.stream(
                "POST",
                f"{self.config.url}/chat/completions",
                json=body,
                headers=self._headers,
                timeout=_timeout(timeout, connect=5.0),
            ) as response:
                if response.status_code >= 400:
                    # Drain now, while the stream is open — the error body (the
                    # server's explanation) must stay readable after close.
                    with contextlib.suppress(httpx.HTTPError):
                        response.read()
                response.raise_for_status()
                trouble: list[str] = []
                for event in _events(response):
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        prompt_tokens = usage.get("prompt_tokens")
                        completion_tokens = usage.get("completion_tokens")
                        cached = _cached_count(usage)
                        if cached is not None:
                            cached_tokens = cached
                    # A refusal or an in-stream error arrives as its own
                    # frame with no content; swallowed, the stream would
                    # end as an empty "ok" reply. Collected and raised
                    # once the stream ends, so the caller's failure
                    # carries the provider's own sentence.
                    failure = event.get("error")
                    if isinstance(failure, dict) and failure.get("message"):
                        trouble.append(str(failure["message"]))
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    refusal = delta.get("refusal")
                    if refusal:
                        trouble.append(str(refusal))
                    thinking = delta.get("reasoning_content") or delta.get("reasoning")
                    if thinking:
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                        thoughts.append(str(thinking))
                        yield Thinking(text=str(thinking))
                    content = delta.get("content")
                    if content:
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                        text.append(str(content))
                        yield Text(text=str(content))
                if trouble:
                    raise DeclinedError("the model declined: " + "; ".join(trouble))
        except GeneratorExit:
            answered("cancelled")
            raise
        except Exception as e:
            answered(f"failed: {type(e).__name__}")
            raise

        end = time.monotonic()
        # Filed BEFORE the final yield: a consumer that takes the last
        # Text and closes without pulling the stats still leaves a
        # finished answer in the log, not a "cancelled".
        answered("ok")
        yield Stats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_seconds=end - start,
            context_max=self.get_context_size(model),
            generation_seconds=(end - first_token_at) if first_token_at is not None else None,
            cached_tokens=cached_tokens,
        )

    def _apply_thinking(self, body: dict[str, object], think: str | None) -> None:
        """Translate the think setting into the request, on every knob the
        engine reads (`thinking_knobs`): a level enables thinking and names
        the effort, "none" actively disables it, None sends nothing and
        leaves the engine's default. An engine without the knob gets
        nothing whatever the setting."""
        if not think or not self.supports_thinking:
            return
        if "reasoning_effort" in self.thinking_knobs:
            body["reasoning_effort"] = think
        if "enable_thinking" in self.thinking_knobs:
            body["chat_template_kwargs"] = {"enable_thinking": think != "none"}

    # ---------- passive introspection (native APIs; defaults = unknown) ----------

    def get_context_size(self, model: str) -> int | None:
        """The loaded context window for `model`, or None when the engine
        does not expose it. Only a real answer is cached — None retries,
        because the usual cause is asking before the model loads."""
        if model in self._context_cache:
            return self._context_cache[model]
        result = self._fetch_context_size(model)
        if result is not None:
            self._context_cache[model] = result
        return result

    def _fetch_context_size(self, model: str) -> int | None:
        """The subclass hook `get_context_size` caches — each engine's
        native way of asking; the base knows none. Declared here so the
        extension point is visible on the interface that owns it."""
        return None

    # ---------- helpers for the engines ----------

    def _get_json(self, path: str, *, timeout: float) -> Any | None:
        """GET `<base url>{path}` → parsed JSON; None on any error or
        non-200. For best-effort native-API reads only."""
        try:
            response = httpx.get(
                f"{self.config.base_url}{path}",
                headers=self._headers,
                timeout=_timeout(timeout, connect=1.0),
            )
            if response.status_code == 200:
                return response.json()
        except (httpx.HTTPError, OSError, ValueError):
            pass
        return None

    def _post_json(self, path: str, body: dict[str, Any], *, timeout: float) -> Any | None:
        """POST `<base url>{path}` → parsed JSON; None on any error or
        non-200. For best-effort native-API reads only — actions that must
        fail loudly use httpx directly."""
        try:
            response = httpx.post(
                f"{self.config.base_url}{path}",
                json=body,
                headers=self._headers,
                timeout=_timeout(timeout, connect=1.0),
            )
            if response.status_code == 200:
                return response.json()
        except (httpx.HTTPError, OSError, ValueError):
            pass
        return None


class LocalSingleClient(OpenAIClient):
    """A single-model engine (llama.cpp, KoboldCpp): the server fronts the
    one model it was launched with — or none — and never loads or unloads.
    Every listed row is loaded, and the context window is the SERVER's:
    the native endpoint takes no model name, so a listing asks once and
    stamps every row. That keeps a listing that came back long — a
    catalog url pasted into the section answers with hundreds of names —
    at one probe rather than one per name, each a full round trip."""

    locality = Locality.LOCAL
    thinking_knobs: ClassVar[tuple[str, ...]] = ("reasoning_effort", "enable_thinking")

    def _list(self, timeout: float) -> list[ModelInfo]:
        names = self._model_names(timeout)
        context = self._window(names)
        return [ModelInfo(name=name, context=context, loaded=True) for name in names]

    def _window(self, names: list[str]) -> int | None:
        """The server's one window, asked through the cache under the
        first name — the hook ignores the name, and a real engine lists
        exactly one, so the chosen model's later ask is the same entry."""
        return self.get_context_size(names[0]) if names else None


class ManagedClient(OpenAIClient, ABC):
    """A local registry (Ollama, omlx, LM Studio) that can load and unload
    models on demand — the actions on top of the passive base. UI offers
    load/unload exactly when a client is one of these."""

    locality = Locality.LOCAL
    thinking_knobs: ClassVar[tuple[str, ...]] = ("reasoning_effort", "enable_thinking")

    @abstractmethod
    def load_model(self, model: str) -> None: ...

    @abstractmethod
    def unload_model(self, model: str) -> None: ...


class CloudClient(OpenAIClient):
    """A hosted catalog (OpenRouter, NanoGPT): the standard listing with
    each model's context window harvested when the catalog reports one.
    Nothing is sized — there is no disk to weigh — and every row is simply
    available, so all of them list as loaded. Cloud alone has an account
    to bill, so `balance` lives here."""

    locality = Locality.REMOTE
    # Extra query string for the catalog listing, when the service wants
    # one to include the model details.
    _MODELS_QUERY: ClassVar[str] = ""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        request_log: RequestSink | None = None,
        smooth: bool = False,
    ) -> None:
        super().__init__(config, request_log=request_log, smooth=smooth)
        # One failed catalog fetch stops chat-time context lookups for
        # the session — a down catalog must not tax every turn with a
        # timeout; any later successful listing clears the mark.
        self._catalog_down = False

    def balance(self, timeout: float = 10.0) -> Money | None:
        """The account balance as the catalog reports it — None when the
        service will not say. Money, not a rendered string: what a
        reader sees is the frontends' to decide, and a figure somebody
        is billed against is not a float."""
        return None

    def _key_works(self, timeout: float) -> bool:
        """Whether the configured api key actually opens the account.
        Catalogs can be public (OpenRouter's is), so a listing alone
        proves nothing; subclasses answer through an authenticated
        endpoint. The base client cannot know and stays permissive."""
        return True

    def _list(self, timeout: float) -> list[ModelInfo]:
        # No key, or one the account rejects → unreachable: rows from a
        # public catalog would only invite a chat that fails with 401.
        if not self.config.api_key:
            raise PermissionError(f"{self.config.name} has no api key")
        if not self._key_works(timeout):
            raise PermissionError(f"{self.config.name} rejected the api key")
        rows = self._catalog(timeout, query=self._MODELS_QUERY)
        self._catalog_down = False
        return rows

    def _fetch_context_size(self, model: str) -> int | None:
        # The catalog is the one source — usually pre-seeded by `_list`;
        # this fetch is the fallback when nothing listed yet.
        if self._catalog_down:
            return None
        try:
            rows = self.models(timeout=5.0)
        except Exception:
            self._catalog_down = True
            return None
        for row in rows:
            if row.name == model:
                return row.context
        return None


def _cache_marked(messages: Sequence[WireMessage], ttl: str) -> list[dict[str, object]]:
    """The messages payload with prompt-cache breakpoints: the system row
    and the final row become content PARTS carrying `cache_control`;
    everything between stays a plain string. Two breakpoints are enough —
    the provider's lookup scans block boundaries backwards from a marker
    for the longest cached prefix, so one rolling trailing mark per
    request finds last turn's entry on its own. `ttl` "5m" is the
    marking's own default and is not spelled; "1h" is."""
    marker: dict[str, object] = {"type": "ephemeral"}
    if ttl == "1h":
        marker["ttl"] = "1h"

    def marked(m: WireMessage) -> dict[str, object]:
        return {
            "role": m.role,
            "content": [{"type": "text", "text": m.body, "cache_control": dict(marker)}],
        }

    out: list[dict[str, object]] = [{"role": m.role, "content": m.body} for m in messages]
    if out and messages[0].role == "system":
        out[0] = marked(messages[0])
    if len(messages) > 1 or (messages and messages[0].role != "system"):
        out[-1] = marked(messages[-1])
    return out


def _events(response: httpx.Response) -> Iterator[dict[str, Any]]:
    """The stream's data events, the SSE framing shed: one parsed object
    per `data:` line, ending at `[DONE]`. Anything else on the wire —
    comment lines, keepalives, a line that will not parse — is skipped,
    never fatal."""
    for raw in response.iter_lines():
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _cached_count(usage: dict[str, Any]) -> int | None:
    """Of a usage report's prompt tokens, how many the provider served
    from cache — OpenAI's spelling first (OpenRouter normalizes to it),
    Anthropic's own as the fallback; None when neither is there."""
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
    else:
        cached = usage.get("cache_read_input_tokens")
    if isinstance(cached, int):
        return cached
    return None


def _timeout(total: float, *, connect: float) -> httpx.Timeout:
    """The httpx timeout with its connect phase capped separately. A
    dead-but-routable host — a mistyped LAN IP, a firewalled port — hangs
    the handshake, and a flat timeout lets it hold the whole read budget
    (a five-second launch stall per such provider); a host that is
    listening at all completes the handshake in milliseconds. The read
    budget stays `total`: a slow answer is not a dead host."""
    return httpx.Timeout(total, connect=min(connect, total))
