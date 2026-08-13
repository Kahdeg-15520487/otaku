"""Schema migrations: an old database brought to the current version.

This module is the machinery — the ladder, the backup, the refusals; the
steps live one module per version (`v2`, `v3`), each frozen WHOLE: a
step writes what its target version WAS, as literals kept beside it, and
its helpers are its own, shared with no sibling — so no later change can
silently rewrite what an old step writes and break every precondition
after it.

A versioned ladder, distinct from the settings migrations on purpose: a
TOML file has no cursor, so those steps re-detect their own applicability
at every launch; a database has one — `meta.schema_version` — and SQLite's
transactional DDL makes step-plus-stamp atomic, so the ladder never needs
to guess where it stands. Steps transform old databases toward the DDL in
`schema.py`, which stays the single source of the CURRENT shape; a fresh
database is created from it directly and never replays a step. The
invariant holding it all together: a migrated database and a fresh one
are identical, `sqlite_master` row for row (the scenario suite asserts
it).

How every case at open resolves:

    no file            create at current schema, stamp — no backup, no message
    version == current fast no-op: no write, no backup, no print
    older              backup FIRST, then steps in order, each step + stamp
                       in one transaction -> one line "Database migrated
                       (v1 -> v2)", echoed to the system log -> launch
    newer              refuse: name both versions - update the app, or
                       restore the pre-migration backup it took
    a step fails       its transaction rolls back -> the database is
                       consistent at the last stamped version, unharmed;
                       refuse to launch, saying exactly that
    crash mid-ladder   nothing special: the next launch resumes from the
                       stamp; the interrupted step rolled back
    backup impossible  refuse to migrate at all — never touch an unbacked
                       database
    two processes      BEGIN IMMEDIATE serializes; the loser waits,
                       re-reads the version, no-ops
    encrypted database irrelevant by design: sealing is per-field at the
                       app level, so schema steps never need the cipher
"""

import sqlite3
from pathlib import Path

from otaku.logs.system import SystemLog
from otaku.paths import Paths
from otaku.store.migrations import v2, v3
from otaku.store.schema import SCHEMA_VERSION

# The ladder itself: one entry per schema version, each a version
# module's frozen step. Mirrors the settings migrations, whose tables
# also live in their package root with the moves in sibling modules.
_STEPS = {2: v2.to_2, 3: v3.to_3}


def migrate(conn: sqlite3.Connection, paths: Paths) -> str | None:
    """Bring an existing database to the current version; the report line
    to print when anything was actually migrated, else None. Raises
    `DatabaseError` for every refusal the module docstring names — and the
    message always says what state the database was LEFT in, because a
    refusal that reads as damage costs more trust than the failure."""
    from otaku.store.database import DatabaseError  # circular: database runs this ladder

    stored = _version(conn, paths.database_file)
    current = int(SCHEMA_VERSION)
    if stored == current:
        return None
    if stored > current:
        raise DatabaseError(
            f"{paths.database_file} uses schema version {stored}, made by a newer otaku "
            f"than this one (schema {current}); update the app (`otaku update`) — or restore "
            f"the pre-migration backup a newer version left in {paths.backups_dir}"
        )
    backup = _backup(conn, paths, stored)
    for target in range(stored + 1, current + 1):
        try:
            conn.execute("BEGIN IMMEDIATE")
            _STEPS[target](conn)
            # fmt: off
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(target),)
            )
            # fmt: on
            conn.commit()
        except Exception as e:
            conn.rollback()
            at = target - 1
            raise DatabaseError(
                f"Migrating {paths.database_file} to schema v{target} failed ({e}); the "
                f"database is unharmed at version {at}, and the pre-migration backup at "
                f"{backup} was not touched"
            ) from e
    SystemLog(paths).record(f"database migrated (v{stored} → v{current}), backup at {backup.name}")
    return f"Database migrated (v{stored} → v{current})"


def _version(conn: sqlite3.Connection, path: Path) -> int:
    from otaku.store.database import DatabaseError  # circular: database runs this ladder

    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as e:
        raise DatabaseError(
            f"{path} is not a database this app wrote ({e}); move the file aside"
        ) from e
    if row is None or not str(row[0]).isdigit():
        raise DatabaseError(
            f"{path} carries schema version {row[0] if row else None!r}; "
            "not a database this app wrote"
        )
    return int(row[0])


def _backup(conn: sqlite3.Connection, paths: Paths, version: int) -> Path:
    """The pre-migration snapshot, taken before any step runs — `VACUUM
    INTO` is consistent even mid-WAL. Named for the version it preserves;
    a leftover from an earlier attempt is kept, not overwritten (`-N`
    appended, the config-backup convention). A backup that cannot be
    written refuses the whole migration: never touch an unbacked
    database."""
    from otaku.store.database import DatabaseError  # circular: database runs this ladder

    stem, suffix = paths.database_file.stem, paths.database_file.suffix
    try:
        paths.backups_dir.mkdir(parents=True, exist_ok=True)
        dest = paths.backups_dir / f"{stem}-schema-v{version}{suffix}"
        n = 2
        while dest.exists():
            dest = paths.backups_dir / f"{stem}-schema-v{version}-{n}{suffix}"
            n += 1
        conn.execute("VACUUM INTO ?", (str(dest),))
    except (sqlite3.Error, OSError) as e:
        raise DatabaseError(
            f"Could not back up {paths.database_file} before migrating ({e}); nothing was changed"
        ) from e
    return dest
