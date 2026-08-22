"""The provider sections: providers.toml — the [NAME] tables and their
type. `ProviderConfig` lives HERE (provider settings are settings); the
providers package imports it, and nothing converts in between."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from otaku.formatting import toml_key, toml_scalar
from otaku.settings.config import ConfigError


@dataclass(frozen=True)
class ProviderConfig:
    """One provider as configured: an OpenAI-compatible server."""

    name: str
    url: str
    api_key: str = ""
    keep_alive: str = ""  # how long an explicitly loaded model stays resident (ollama)

    @property
    def base_url(self) -> str:
        """The URL without a trailing /v1 — where native management
        endpoints live."""
        return self.url[: -len("/v1")] if self.url.endswith("/v1") else self.url


def load(path: Path) -> dict[str, ProviderConfig]:
    """The [NAME] sections, validated (a section must carry a url).
    Raises ConfigError — the file is hand-edited, so errors must be
    human."""
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"{path} does not exist") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML — {e}") from e
    sections = {name: entry for name, entry in raw.items() if isinstance(entry, dict)}
    if not sections:
        raise ConfigError(f"{path}: at least one [NAME] provider section is required")
    providers: dict[str, ProviderConfig] = {}
    for name, entry in sections.items():
        if "url" not in entry:
            raise ConfigError(f"{path}: [{name}] must have a 'url' key")
        providers[name] = ProviderConfig(
            name=str(name),
            url=str(entry["url"]).rstrip("/"),
            api_key=str(entry.get("api_key", "")),
            keep_alive=str(entry.get("keep_alive", "")),
        )
    return providers


def render(providers: dict[str, ProviderConfig]) -> str:
    """providers.toml text — one top-level [name] section per provider;
    what first run writes."""
    lines = [
        "# otaku providers — one [name] section per provider. The model",
        "# picker edits urls and api keys here; api keys are stored sealed.",
    ]
    for config in providers.values():
        lines += [
            "",
            f"[{toml_key(config.name)}]",
            f"url = {toml_scalar(config.url)}",
            f"api_key = {toml_scalar(config.api_key)}",
        ]
        if config.keep_alive:
            lines.append(f"keep_alive = {toml_scalar(config.keep_alive)}")
    return "\n".join(lines) + "\n"
