"""Schema step 2: what a version-1 database becomes.

The step rewrites the `messages` and `characters` DDL in place —
SQLite's documented "simpler procedure" (`writable_schema`): a CHECK
constraint and a column name are only text in the stored DDL, nothing on
disk depends on them, so the CHECK widens to admit 'card', `framing`
becomes `template`, and `characters` gains its `card` column, all
without rebuilding a table. The step demands the stored DDL match what
version 1 shipped (a hand-edited schema is refused rather than guessed
at) and writes the version-2 text verbatim.
"""

import re
import sqlite3

# The `messages` DDL exactly as each version shipped it. V1 is the
# step's precondition; V2 is what it writes.
_V1_MESSAGES = """CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    parent_id   INTEGER,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant')),
    kind        TEXT NOT NULL DEFAULT 'dialogue'
                  CHECK (kind IN ('dialogue','narration','ooc')),
    speaker_id  INTEGER REFERENCES characters(id) ON DELETE SET NULL,  -- extracted automatically
    speaker     BLOB,                    -- extracted automatically; name-at-the-time snapshot
    body        BLOB NOT NULL,           -- exactly what was typed/generated
    framing     BLOB,                    -- /me /you /ooc injection, joined to body at wire time
    provider    TEXT,                    -- who generated an assistant turn
    model       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (story_id, id),               -- composite-FK target: same-story references only
    FOREIGN KEY (story_id, parent_id) REFERENCES messages(story_id, id),
    CHECK (parent_id IS NULL OR parent_id < id)
)"""

# What changes against V1: the kind CHECK admits 'card', `framing` is
# renamed to `template` (its comment rewritten with it) — both only text.
_V2_MESSAGES = """CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    parent_id   INTEGER,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant')),
    kind        TEXT NOT NULL DEFAULT 'dialogue'
                  CHECK (kind IN ('dialogue','narration','ooc','card')),
    speaker_id  INTEGER REFERENCES characters(id) ON DELETE SET NULL,  -- extracted automatically
    speaker     BLOB,                    -- extracted automatically; name-at-the-time snapshot
    body        BLOB NOT NULL,           -- exactly what was typed/generated
    template    BLOB,                    -- the template the turn was played with, filled at wire time
    provider    TEXT,                    -- who generated an assistant turn
    model       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (story_id, id),               -- composite-FK target: same-story references only
    FOREIGN KEY (story_id, parent_id) REFERENCES messages(story_id, id),
    CHECK (parent_id IS NULL OR parent_id < id)
)"""


_V1_CHARACTERS = """CREATE TABLE characters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    name        BLOB NOT NULL,
    aliases     BLOB,                    -- JSON array, sealed
    description BLOB,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)"""

# What changes against V1: the `card` column appended — LAST, because the
# record format is positional and existing rows must read NULL there, not
# shift their trailing values into it.
_V2_CHARACTERS = """CREATE TABLE characters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    name        BLOB NOT NULL,
    aliases     BLOB,                    -- JSON array, sealed
    description BLOB,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    card        BLOB                     -- an imported card as TOML
)"""


def to_2(conn: sqlite3.Connection) -> None:
    _rewrite(conn, "messages", _V1_MESSAGES, _V2_MESSAGES)
    _rewrite(conn, "characters", _V1_CHARACTERS, _V2_CHARACTERS)


def _rewrite(conn: sqlite3.Connection, table: str, expect: str, write: str) -> None:
    """One table's stored DDL replaced under `writable_schema`, refused
    unless it matches what the step expects — a hand-edited schema is
    never guessed at. Adding a COLUMN this way is sound for the same
    reason as the constraint and the rename: the record format is
    positional and rows shorter than the schema read as NULL in the
    missing columns, which is exactly what `ADD COLUMN` relies on."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    if row is None or _normalized(row[0]) != _normalized(expect):
        raise sqlite3.DatabaseError(f"{table} DDL is not what schema version 1 shipped")
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
