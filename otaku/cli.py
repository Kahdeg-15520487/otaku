"""The process entry: argv routing and nothing else. Bare `otaku` opens
the terminal over an open session; `otaku update` self-updates
(`update.py` is its machinery); `otaku logs …` pages the day-rotated
logs (the sealed request bodies unlocked through `backend.launch`). The
state-dir root is resolved HERE (the env var is entry-point business)
and passed down as a plain path.
"""

import getpass
import os
from datetime import datetime
from pathlib import Path

import click

from otaku import __version__, logging
from otaku import update as updater
from otaku.backend import ConfigError, DatabaseError, EncryptionError
from otaku.backend import launch as backend_launch
from otaku.formatting import pretty_path
from otaku.terminal import chat

_ENV_VAR = "OTAKU_CONFIG_DIR"


def resolve_root() -> Path | None:
    """The state-dir root from OTAKU_CONFIG_DIR — None for the default
    (backend owns the default location; the env var is the entry's)."""
    raw = os.environ.get(_ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else None


@click.group(
    invoke_without_command=True,
    # Wide help: every command's description prints in full, on one line,
    # instead of click's wrapped-and-truncated defaults.
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 160},
)
@click.version_option(__version__, "-v", "--version", prog_name="otaku")
@click.pass_context
def main(ctx: click.Context) -> None:
    """A roleplay terminal client."""
    if ctx.invoked_subcommand is not None:
        return
    root = resolve_root()
    try:
        session = backend_launch.open_session(root, ask_secret=getpass.getpass)
    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        ctx.exit(2)
    except (EncryptionError, DatabaseError) as e:
        click.echo(str(e), err=True)
        ctx.exit(1)
    try:
        chat.run(session)
    except Exception as e:
        # The last resort: whatever escaped every inner containment. The
        # story is safe — every store write is transactional — so say so,
        # record the traceback, and leave quietly.
        path = backend_launch.error_log(root).record("unhandled", e)
        click.echo(
            f"otaku crashed — your story is safe in the database. The crash is "
            f"recorded in {pretty_path(path)}; please attach it to an issue.",
            err=True,
        )
        ctx.exit(1)
    finally:
        session.close()


@main.command(short_help="Update otaku to the latest release")
def update() -> None:
    """Update otaku in place, whatever installed it: a Homebrew or uv
    install runs its own upgrade, a source checkout is left to git, and
    anything else gets pip. The new version runs at the next launch."""
    command = updater.upgrade_command()
    if command is None:
        click.echo("This otaku runs from a source checkout — update it with git:")
        click.echo("  git pull")
        return
    click.echo("Updating via: " + " ".join(command))
    code = updater.run(command)
    root = resolve_root()
    if code == 0:
        backend_launch.system_log(root).record(f"app update finished ({' '.join(command)})")
        click.echo("Done — the new version runs at the next otaku.")
        return
    backend_launch.system_log(root).record(f"app update failed ({' '.join(command)}, exit {code})")
    click.echo("The update did not finish — run the one matching your install:", err=True)
    for manual in updater.MANUAL_COMMANDS:
        click.echo(f"  {manual}", err=True)
    click.get_current_context().exit(1)


class _DeclaredOrderGroup(click.Group):
    """Subcommands listed in declaration order, not alphabetically."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)


@main.group(
    cls=_DeclaredOrderGroup,
    short_help="Day-rotated logs: requests (what the models were sent), "
    "system (the worker's account), error (contained crashes)",
)
def logs() -> None:
    """Day-rotated logs: `requests` (what the models were sent), `system`
    (the background worker's own account), and `error` (every contained
    crash's traceback)."""


@logs.command("requests", short_help="Show the model-request log")
@click.argument("day", required=False)
@click.option("--list", "list_days", is_flag=True, help="List the available log days.")
def logs_requests(day: str | None, list_days: bool) -> None:
    """Print one day's model-request log (DAY as YYYY-MM-DD, default
    today) — the sealed bodies unlocked the way the app unlocks."""
    ctx = click.get_current_context()
    root = resolve_root()
    try:
        request_log = backend_launch.request_log(root, ask_secret=getpass.getpass)
    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        ctx.exit(2)
    except EncryptionError as e:
        click.echo(str(e), err=True)
        ctx.exit(1)

    if list_days:
        _echo_days(request_log.get_days(), "no request logs yet")
        return
    stamp = _day_stamp(ctx, day)
    if not request_log.get_path(stamp).exists():
        click.echo(f"no request log for {logging.dashed(stamp)}", err=True)
        ctx.exit(1)
    click.echo_via_pager(logging.render_requests(request_log, stamp))


@logs.command("system", short_help="Show the background lore work")
@click.argument("day", required=False)
@click.option("--list", "list_days", is_flag=True, help="List the available log days.")
def logs_system(day: str | None, list_days: bool) -> None:
    """Print one day's system log — the background worker's account of
    itself (DAY as YYYY-MM-DD, default today)."""
    _page_plain(backend_launch.system_log(resolve_root()), day, list_days, "system")


@logs.command("error", short_help="Show every contained crash's traceback")
@click.argument("day", required=False)
@click.option("--list", "list_days", is_flag=True, help="List the available log days.")
def logs_error(day: str | None, list_days: bool) -> None:
    """Print one day's error log — every contained crash's traceback
    (DAY as YYYY-MM-DD, default today)."""
    _page_plain(backend_launch.error_log(resolve_root()), day, list_days, "error")


def _page_plain(log: logging.DailyLog, day: str | None, list_days: bool, name: str) -> None:
    """The plain-text logs' shared body: list the days, or page one."""
    ctx = click.get_current_context()
    if list_days:
        _echo_days(log.get_days(), f"no {name} logs yet")
        return
    stamp = _day_stamp(ctx, day)
    path = log.get_path(stamp)
    if not path.exists():
        click.echo(f"no {name} log for {logging.dashed(stamp)}", err=True)
        ctx.exit(1)
    click.echo_via_pager(path.read_text(encoding="utf-8"))


def _day_stamp(ctx: click.Context, day: str | None) -> str:
    """The file stamp a subcommand pages: today when DAY is absent,
    `logging.resolve_day`'s parse otherwise — or a usage error."""
    if day is None:
        return datetime.now().astimezone().strftime("%Y%m%d")
    stamp = logging.resolve_day(day)
    if stamp is None:
        click.echo(
            "DAY must be YYYY-MM-DD (or YYYYMMDD), e.g. otaku logs requests 2026-07-25", err=True
        )
        ctx.exit(2)
    return stamp


def _echo_days(days: list[tuple[str, int]], empty: str) -> None:
    if not days:
        click.echo(empty)
        return
    for row in logging.day_rows(days):
        click.echo(row)
