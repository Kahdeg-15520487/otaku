"""The user's configuration: config.toml. The provider sections are a
sibling surface (`settings.providers`); `Config` deliberately does not
carry them — the Registry does, injected at the launch.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from otaku.formatting import toml_scalar
from otaku.settings import row


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class UiSettings:
    """The configured looks a frontend needs at its own launch — the one
    slice of config.toml that is the frontend's business (a persisted
    slice, hence a settings type; run-time bundles live beside their
    consumers instead)."""

    dialogue_color: str
    dialogue_bold: bool
    show_banner: bool
    # Defaulted where the others are not: "default" is a real value —
    # the platform's own sound — so a caller that has no opinion about
    # sound (the theme's, every time) needs none.
    notification_sound: str = "default"


@dataclass(frozen=True)
class WebSettings:
    """Where the web frontend listens — the other slice of config.toml
    that is a frontend's business, and the only one needed before a
    session exists. Loopback by default: this is one person's
    application, and reaching it from another machine is a decision to
    make on purpose."""

    host: str = "127.0.0.1"
    port: int = 9600


@dataclass(frozen=True)
class Encryption:
    """The [encryption] section. Provider "none" (the default) stores
    content as readable plain text."""

    provider: str = "none"
    retrieve_command: str | None = None


@dataclass(frozen=True)
class Config:
    encryption: Encryption = field(default_factory=Encryption)
    # [settings]
    show_banner: bool = True
    smooth_streaming: bool = True
    notification_sound: str = "default"  # "default" = the platform's own; else a path
    # [ui]
    dialogue_color: str = "auto"
    dialogue_bold: bool = False
    # [web]
    web_host: str = "127.0.0.1"
    web_port: int = 9600
    # [context]
    head_messages: int = 20
    min_tail_messages: int = 150
    max_context: int = 65536
    # [lore_extraction]
    lore_enabled: bool = True
    idle_seconds: float = 300.0
    scene_min_chars: int = 6000
    scene_min_messages: int = 20
    settle_messages: int = 20
    # [database]
    backups: int = 7
    seed_sample: bool = True

    def to_toml(self) -> str:
        """This configuration rendered as config.toml text: every key
        present with an aligned comment, so the whole surface is
        discoverable and editable in place."""
        # One setting per source line, whatever the width — E501 is off
        # for this file (see pyproject).
        # fmt: off
        lines = [
            "[settings]",
            row(f"show_banner = {toml_scalar(self.show_banner)}", "the session header shown when a chat opens"),
            row(f"smooth_streaming = {toml_scalar(self.smooth_streaming)}", "re-time bursty model output into an even stream"),
            row(f"notification_sound = {toml_scalar(self.notification_sound)}", 'what /set notification plays: "default" is the platform\'s own, else a path'),
            "",
            "[ui]",
            row(f"dialogue_color = {toml_scalar(self.dialogue_color)}", 'spoken lines: "auto" fits the background; a color name ("cyan") or #rrggbb'),
            row(f"dialogue_bold = {toml_scalar(self.dialogue_bold)}", "also bold the spoken lines"),
            "",
            "[web]",
            row(f"host = {toml_scalar(self.web_host)}", "where `otaku web` listens; anything but 127.0.0.1 opens it to the network"),
            row(f"port = {self.web_port}", "…and on which port"),
            "",
            "[context]",
            row(f"head_messages = {self.head_messages}", "opening messages kept verbatim in the prompt"),
            row(f"min_tail_messages = {self.min_tail_messages}", "at least this many recent messages kept verbatim"),
            row(f"max_context = {self.max_context}", "the prompt may use at most this many tokens; 0 = the model's whole window"),
            "",
            "[lore_extraction]",
            row(f"enabled = {toml_scalar(self.lore_enabled)}", "extract lore on idle (/extract always works)"),
            row(f"idle_seconds = {toml_scalar(self.idle_seconds)}", "extraction runs after this long idle at the prompt"),
            row(f"scene_min_chars = {self.scene_min_chars}", "a scene closes once it holds this much text…"),
            row(f"scene_min_messages = {self.scene_min_messages}", "…and at least this many messages"),
            row(f"settle_messages = {self.settle_messages}", "newest messages a scene never closes over"),
            "",
            "[database]",
            row(f"backups = {self.backups}", "daily snapshots kept in database/backups/ (0 disables)"),
            row(f"seed_sample = {toml_scalar(self.seed_sample)}", "import the sample story into a freshly created database"),
            "",
            "[encryption]",
            row(f"provider = {toml_scalar(self.encryption.provider)}", "none — content stored as readable plain text"),
            row("", "keychain — key in the OS keychain"),
            row("", "command — key from retrieve_command's stdout"),
            row("", "passphrase — key derived from a passphrase, asked every launch"),
            row("", "disk — key in configs/kek.key"),
        ]
        # fmt: on
        if self.encryption.retrieve_command is not None:
            command = toml_scalar(self.encryption.retrieve_command)
            lines.append(row(f"retrieve_command = {command}", 'only for provider = "command"'))
        else:
            lines.append(
                row('# retrieve_command = "pass otaku/kek"', 'only for provider = "command"')
            )
        return "\n".join(lines) + "\n"

    @property
    def web(self) -> WebSettings:
        """The web frontend's slice, cut like `ui` below."""
        return WebSettings(host=self.web_host, port=self.web_port)

    @property
    def ui(self) -> UiSettings:
        """The frontend slice, cut once here."""
        return UiSettings(
            dialogue_color=self.dialogue_color,
            dialogue_bold=self.dialogue_bold,
            show_banner=self.show_banner,
            notification_sound=self.notification_sound,
        )


def load(path: Path) -> Config:
    """Read and validate config.toml. Raises ConfigError with a message
    that names the file — it is hand-edited, so errors must be human."""
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"{path} does not exist") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML — {e}") from e

    enc_raw = _table(raw, "encryption", path)
    command = enc_raw.get("retrieve_command")
    encryption = Encryption(
        provider=str(enc_raw.get("provider", "none")),
        retrieve_command=str(command) if command is not None else None,
    )

    settings = _table(raw, "settings", path)
    ui = _table(raw, "ui", path)
    web = _table(raw, "web", path)
    context = _table(raw, "context", path)
    lore = _table(raw, "lore_extraction", path)
    database = _table(raw, "database", path)
    try:
        return Config(
            encryption=encryption,
            show_banner=bool(settings.get("show_banner", True)),
            smooth_streaming=bool(settings.get("smooth_streaming", True)),
            notification_sound=str(settings.get("notification_sound", "default")),
            dialogue_color=str(ui.get("dialogue_color", "auto")),
            dialogue_bold=bool(ui.get("dialogue_bold", False)),
            web_host=str(web.get("host", "127.0.0.1")),
            # Clamped to the range a socket accepts, 0 excluded: a port
            # of 0 asks the OS to pick one, and `otaku web` says where
            # the page is BEFORE it binds — an address nobody can be
            # told is no use for a page somebody has to open. A second
            # otaku on one machine names its own port here.
            web_port=min(65535, max(1, _int(web, "port", 9600))),
            head_messages=max(0, _int(context, "head_messages", 20)),
            min_tail_messages=max(1, _int(context, "min_tail_messages", 150)),
            max_context=max(0, _int(context, "max_context", 65536)),
            lore_enabled=bool(lore.get("enabled", True)),
            idle_seconds=max(0.0, _float(lore, "idle_seconds", 300.0)),
            scene_min_chars=max(1, _int(lore, "scene_min_chars", 6000)),
            scene_min_messages=max(1, _int(lore, "scene_min_messages", 20)),
            settle_messages=max(0, _int(lore, "settle_messages", 20)),
            backups=max(0, _int(database, "backups", 7)),
            seed_sample=bool(database.get("seed_sample", True)),
        )
    except ValueError as e:
        raise ConfigError(f"{path}: {e}") from e


def _table(raw: dict[str, object], name: str, path: object) -> dict[str, object]:
    section = raw.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: [{name}] must be a table")
    return section


def _int(section: dict[str, object], key: str, default: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{key}' must be an integer")
    return value


def _float(section: dict[str, object], key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"'{key}' must be a number")
    return float(value)
