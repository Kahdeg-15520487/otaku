"""The model and provider operations: switching, the picker's inventory,
and the panel's edits.

Panel saves write providers.toml surgically, seal api keys first
(encryption's sealing plane), and update the running registry in the same
call, so an edit is live at once; a write that could not land is SAID,
not swallowed.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

import httpx

from otaku.backend.session import Refused, Session
from otaku.encryption import SealedError, seal
from otaku.formatting import printable, toml_scalar
from otaku.providers import CLIENTS, ManagedClient, Provider, ProviderConfig
from otaku.settings.migrations import PROMPT_CACHE_ROW, surgery


def switch_model(session: Session, provider: str, model: str) -> str:
    """Switch for the rest of the session, keeping the context (compare
    models on one prompt: switch, then regenerate). Parameters follow the
    model; the switch is remembered. Returns the confirmation; raises
    Refused for an unknown provider or a no-op."""
    known = {config.name for config in session._providers_registry.configured()}
    if provider not in known:
        raise Refused(f"Unknown provider {provider!r}.")
    if f"{provider}/{model}" == session.full_model_name:
        raise Refused(f"Already using {session.full_model_name}.")
    session._update_state(model=f"{provider}/{model}")
    session._reload_params()
    return f"Switched to {session.full_model_name}."


def switch_spec(session: Session, raw: str) -> str:
    """The typed `/model PROVIDER/MODEL` form: owns the ONE split rule
    (the first slash — model names may carry more) and the refusal that
    lists the known providers, then wraps `switch_model`. Both frontends'
    chat boxes route here; the picker and the web PUT use the structured
    form."""
    known = {config.name for config in session._providers_registry.configured()}
    head, _, rest = raw.strip().partition("/")
    if head not in known or not rest:
        names = ", ".join(sorted(known))
        raise Refused(f"Use PROVIDER/MODEL (providers: {names}), or /model with no args to pick.")
    return switch_model(session, head, rest)


def get_providers(
    session: Session, skip: set[str] | None = None
) -> tuple[list[Provider], set[str]]:
    """Every reachable provider with its models, plus the reachable set —
    the picker's one query; `skip` lets it fetch cloud catalogs after
    its screen is up."""
    return session._providers_registry.get_providers(skip)


@dataclass(frozen=True)
class Engine:
    """One supported engine, as the provider panel captions it — name
    (the section key), label (the project's own spelling), and whether
    it runs locally (a catalog's url is fixed; its models are billed)."""

    name: str
    label: str
    local: bool


def engines(session: Session) -> list[Engine]:
    """The supported engines in the panel's canonical order — the ONE
    source of the captions and the local/cloud split, so no frontend
    keeps its own table."""
    return [Engine(cls.kind, cls.label, cls.local) for cls in CLIENTS.values()]


def configured(session: Session) -> set[str]:
    """The configured providers' names — what the panel's one-provider
    refresh skips everything but, and nothing more: the sections
    themselves come one at a time through `section`."""
    return {config.name for config in session._providers_registry.configured()}


def loaded_models(session: Session, provider: str) -> set[str]:
    """Which of an engine's models are loaded right now — the picker's
    read-back after a load or unload, asked of that ONE engine with the
    listing's own patience (a server that just loaded a model is the
    slowest it ever is). Raises Refused when it cannot be reached: a
    refresh that failed quietly would leave the panel claiming the
    opposite of what just happened."""
    try:
        client = session._providers_registry.get_client(provider)
    except ValueError as e:
        raise Refused(str(e)) from e
    try:
        return {model.name for model in client.models() if model.loaded}
    except httpx.HTTPStatusError as e:
        detail = printable(" ".join(e.response.text.split()))[:300]
        raise Refused(f"The engine refused: {detail or e.response.status_code}") from e
    except httpx.RequestError as e:
        raise Refused(f"Could not reach {provider}.") from e


def section(session: Session, provider: str) -> ProviderConfig:
    """The engine's current section when configured, its autoconfigured
    default otherwise — what the panel shows either way."""
    configured = {config.name: config for config in session._providers_registry.configured()}
    if provider in configured:
        return configured[provider]
    if provider in CLIENTS:
        return CLIENTS[provider].autoconfigure()
    return ProviderConfig(name=provider, url="")


def save_field(session: Session, provider: str, attr: Literal["url", "api_key"], value: str) -> str:
    """Save a url or api key: sealed (keys), written surgically into
    providers.toml (a missing section is founded — how a cloud provider
    is added), live in the registry at once. Returns "" or the warning
    when the file could not be written (the session still took it)."""
    value = value.strip()
    if not value:
        raise Refused("Nothing to save.")
    config = section(session, provider)
    if attr == "url":
        value = value.rstrip("/")
        line = f"url = {toml_scalar(value)}"
        updated = replace(config, url=value)
    else:
        try:
            sealed_value = seal(
                value,
                key_file=session._paths.config_key_file,
                service=session._paths.keychain_service,
            )
        except SealedError as e:
            raise Refused(f"Save failed: {e}") from e
        line = f"api_key = {toml_scalar(sealed_value)}"
        updated = replace(config, api_key=value)
    # An engine not in providers.toml yet gets its section written
    # first — this is how a cloud provider is added deliberately. An
    # engine that honours cache breakpoints is founded with the
    # prompt_cache row, the same line the upgrade migration writes, so
    # the setting is visible in the file however the section got there.
    block = f"[{provider}]\nurl = {toml_scalar(config.url)}\n" + 'api_key = ""'
    if provider in CLIENTS and CLIENTS[provider].cache_markers:
        block += "\n" + PROMPT_CACHE_ROW
    written = surgery.update_providers(
        session._paths.providers_file,
        session._paths.config_backups_dir,
        [surgery.ensure_section(provider, block), surgery.set_key(provider, attr, line)],
    )
    session._providers_registry.update_provider(updated)
    if not written:
        # The registry took the value, the file did not — say so, or the
        # next launch silently forgets what the panel confirmed.
        return "Saved for this session only — providers.toml could not be written."
    return ""


def clear_api_key(session: Session, provider: str) -> str:
    """Forget a stored key — file and session both, or NEITHER: a clear
    that cannot reach the file keeps the session copy too, and says so.
    Returns "" when forgotten (or there was nothing to forget)."""
    config = section(session, provider)
    if not config.api_key:
        return ""  # nothing to clear — and the field is visibly bare
    written = surgery.update_providers(
        session._paths.providers_file,
        session._paths.config_backups_dir,
        [surgery.set_key(provider, "api_key", 'api_key = ""')],
    )
    if not written:
        # Forgetting that does not reach the file is not forgetting: the
        # key stays — in the session too, so the (set) mark stays honest.
        return "Not forgotten — providers.toml could not be written."
    session._providers_registry.update_provider(replace(config, api_key=""))
    return ""


def load(session: Session, provider: str, model: str) -> None:
    """Load on a managed engine; blocks until the server answers. Every
    failure raises Refused with the curated sentence (not managed, the
    engine unreachable, the engine's own error text) — no transport
    exception type ever crosses the boundary."""
    _perform(_managed(session, provider).load_model, model, provider)


def unload(session: Session, provider: str, model: str) -> None:
    _perform(_managed(session, provider).unload_model, model, provider)


def _managed(session: Session, provider: str) -> ManagedClient:
    try:
        client = session._providers_registry.get_client(provider)
    except ValueError as e:
        raise Refused(str(e)) from e
    if not isinstance(client, ManagedClient):
        raise Refused(f"{provider} cannot load or unload models.")
    return client


def _perform(action: Callable[[str], None], model: str, provider: str) -> None:
    """One load/unload call, its failures curated into Refused — shared
    by both doors, so the wording cannot fork."""
    try:
        action(model)
    except httpx.HTTPStatusError as e:
        detail = printable(" ".join(e.response.text.split()))[:300]
        raise Refused(f"The engine refused: {detail or e.response.status_code}") from e
    except httpx.RequestError as e:
        raise Refused(f"Could not reach {provider}.") from e
