"""The step functions, one frozen per schema version — the registry
mapping versions to them lives in the package root, the way the settings
migrations keep their tables there.

A step is HISTORY: it writes what its target version WAS, as a literal
kept beside it, never what `schema.py` currently says — otherwise a later
schema change would silently rewrite an old step's output and break every
precondition after it. `schema.py` stays the CURRENT shape; the
fresh-equals-migrated scenario holds the end of this chain against it, so
a schema edit without a new step fails loudly.

Step 1 -> 2 rewrites the `messages` DDL in place — SQLite's documented
"simpler procedure" (`writable_schema`): a CHECK constraint and a column
name are only text in the stored DDL, nothing on disk depends on them, so
the CHECK widens to admit 'card' and `framing` becomes `template` without
rebuilding the table. The step demands the stored DDL match what version
1 shipped (a hand-edited schema is refused rather than guessed at) and
writes the version-2 text verbatim.
"""

import re
import sqlite3

# The `messages` DDL exactly as each version shipped it. V1 is step 2's
# precondition; V2 is what it writes.
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


def to_2(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'messages'").fetchone()
    if row is None or _normalized(row[0]) != _normalized(_V1_MESSAGES):
        raise sqlite3.DatabaseError("messages DDL is not what schema version 1 shipped")
    conn.execute("PRAGMA writable_schema = ON")
    # fmt: off
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = 'messages'", (_V2_MESSAGES,)
    )
    # fmt: on
    conn.execute("PRAGMA writable_schema = OFF")


def _normalized(sql: str) -> str:
    """DDL with every whitespace run collapsed — the comparison shape for
    preconditions, so an indentation difference never refuses a database
    the step could migrate."""
    return re.sub(r"\s+", " ", sql).strip()
