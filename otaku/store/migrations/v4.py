"""Schema step 4: what a version-3 database becomes.

One change: `token_usage` gains a `cached_tokens` column — how much of a
request's prompt the provider served from its cache. Appended LAST,
because the record format is positional and existing rows must read NULL
there, not shift their trailing values into it; only text changes, so
the table is rewritten in place under `writable_schema` (the same
documented "simpler procedure" step 2 used, its helpers copied here
because a step's helpers are frozen with it, shared with no sibling).
"""

import re
import sqlite3

# The `token_usage` DDL exactly as each version shipped it. V3 is the
# step's precondition (unchanged since v1); V4 is what it writes.
_V3_TOKEN_USAGE = """CREATE TABLE token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id          INTEGER REFERENCES stories(id) ON DELETE SET NULL,  -- survives deletion
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    duration_seconds  REAL,
    created_at        TEXT NOT NULL
)"""

# What changes against V3: the `cached_tokens` column appended.
_V4_TOKEN_USAGE = """CREATE TABLE token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id          INTEGER REFERENCES stories(id) ON DELETE SET NULL,  -- survives deletion
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    duration_seconds  REAL,
    created_at        TEXT NOT NULL,
    cached_tokens     INTEGER             -- of prompt_tokens, served from the provider's cache
)"""


def to_4(conn: sqlite3.Connection) -> None:
    _rewrite(conn, "token_usage", _V3_TOKEN_USAGE, _V4_TOKEN_USAGE)


def _rewrite(conn: sqlite3.Connection, table: str, expect: str, write: str) -> None:
    """One table's stored DDL replaced under `writable_schema`, refused
    unless it matches what the step expects — a hand-edited schema is
    never guessed at. Adding a COLUMN this way is sound because the
    record format is positional and rows shorter than the schema read as
    NULL in the missing columns, which is exactly what `ADD COLUMN`
    relies on."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    if row is None or _normalized(row[0]) != _normalized(expect):
        raise sqlite3.DatabaseError(f"{table} DDL is not what schema version 3 shipped")
    conn.execute("PRAGMA writable_schema = ON")
    # fmt: off
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?", (write, table)
    )
    # fmt: on
    conn.execute("PRAGMA writable_schema = OFF")


def _normalized(sql: str) -> str:
    """DDL with every whitespace run collapsed — the comparison shape for
    preconditions, so an indentation difference never refuses a database
    the step could migrate."""
    return re.sub(r"\s+", " ", sql).strip()
