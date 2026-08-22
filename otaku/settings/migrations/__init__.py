"""Config migrations: the one way the app edits the settings files.

This module holds the shape-change tables themselves and `migrate`, the
whole launch step; `surgery` is the toolkit every edit is built from,
`providers_file` the moves over providers.toml, and `prompt_texts` the
refreshed templates for prompts.toml. Everything here is idempotent and
convergent: it all simply reruns at every launch — no version stamp to
trust, no one-shot step whose half-state could stick — so a crash
between writes, a hand edit, or a launch that could not finish heals on
the next one. A file is written only when something actually changed.
"""

import contextlib
from collections.abc import Callable
from pathlib import Path

from otaku.settings import row, write_atomic
from otaku.settings.migrations.prompt_texts import (
    EXTRACT_0_2_2,
    refresh_template,
    update_prompts,
)
from otaku.settings.migrations.providers_file import (
    ensure_providers,
    move_providers,
    seal_api_keys,
)
from otaku.settings.migrations.surgery import (
    Migration,
    apply_migrations,
    drop_key_everywhere,
    ensure_section,
    set_key,
    update_config,
    update_providers,
)
from otaku.settings.prompts import EXTRACT_DEFAULT
from otaku.settings.providers import ProviderConfig

__all__ = [
    "Migration",
    "apply_migrations",
    "ensure_section",
    "migrate",
    "set_key",
    "update_providers",
]


# config.toml's shape-change table, oldest first: one factory call per
# change across app versions, each safe to re-run on any config the app
# ever wrote.
_CONFIG_MIGRATIONS: list[Migration] = [
    # 0.2.2 — dialogue coloring arrives with the [ui] section.
    ensure_section(
        "ui",
        "[ui]\n"
        + row(
            'dialogue_color = "auto"',
            'spoken lines: "auto" fits the background; a color name ("cyan") or #rrggbb',
        )
        + "\n"
        + row("dialogue_bold = false", "also bold the spoken lines"),
        after="settings",
    ),
]


# prompts.toml's shape-change table: the stub materializes every template,
# so a changed built-in must be carried to existing files — and only into
# files still holding the superseded shipped text, byte-exact (an edited
# template never matches and is never touched).
_PROMPT_MIGRATIONS: list[Migration] = [
    # 0.3.0 — journals become the record of presence: one per character
    # present, silent bystanders included, arrivals and departures named.
    refresh_template("extract_prompt", EXTRACT_0_2_2, EXTRACT_DEFAULT),
]


def _provider_migrations(
    seal: Callable[[str], str], is_sealed: Callable[[str], bool]
) -> list[Migration]:
    """providers.toml's shape-change table — a function, unlike the
    config table above, because its entries need the launch's sealer.
    Its sections carry the user's own names, so an entry here sweeps all
    of them — and runs after the move from an old config, so it cleans a
    section the same way wherever the section came from."""
    return [
        # 0.2.2 — thinking support became class knowledge of the engine.
        drop_key_everywhere("supports_thinking"),
        # 0.2.2 — api keys live sealed; a plain one (hand-typed, or left
        # by a launch that could not seal) is sealed as soon as possible.
        seal_api_keys(seal, is_sealed),
    ]


def migrate(
    *,
    config_path: Path,
    providers_path: Path,
    prompts_path: Path,
    backups_dir: Path,
    provider_defaults: dict[str, ProviderConfig],
    seal: Callable[[str], str],
    is_sealed: Callable[[str], bool],
) -> None:
    """The whole launch step over the settings files, in order: the
    config table, the provider move, the providers table (plain api
    keys sealed — `is_sealed` rides with `seal` so the migration skips
    sealed keys itself; an unsealable line stays for the next launch),
    the given engines' sections ensured, the
    prompt-template refreshes. providers.toml itself converges too:
    missing beside an existing config — a crash between the first-run
    writes, a hand deletion — it is founded empty here, for the ensured
    sections to fill. A missing config is bootstrap's business, and
    failures are swallowed — a migration is never worth a launch."""
    update_config(config_path, backups_dir, _CONFIG_MIGRATIONS)
    move_providers(config_path, providers_path, backups_dir)
    if config_path.exists() and not providers_path.exists():
        with contextlib.suppress(OSError):
            write_atomic(providers_path, "")
    update_providers(providers_path, backups_dir, _provider_migrations(seal, is_sealed))
    ensure_providers(providers_path, backups_dir, provider_defaults)
    update_prompts(prompts_path, backups_dir, _PROMPT_MIGRATIONS)
