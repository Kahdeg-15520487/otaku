"""Schema step 3: what a version-2 database becomes.

Constraint changes: `scenes` loses `UNIQUE (story_id, start_message_id)`
— a rewound branch may close a scene starting where an abandoned one
did — while `characters` gains `UNIQUE (story_id, id)` and `journals`
widens its character reference onto it, the composite-FK pattern every
other cross-table reference already follows. A UNIQUE lives as a real
index (a b-tree and its `sqlite_master` row), not only as text, so those
two tables REBUILD (create-copy-drop-rename, the documented procedure)
and only `journals` is a text rewrite; the rename stores the healed name
QUOTED, so each rebuild writes its target text back under
`writable_schema` as the last touch. The step runs with foreign keys
OFF — `database.open` guarantees it; a rebuild's DROP must not fire
cascades into referencing tables — and ends with
`PRAGMA foreign_key_check`, so a database whose rows would not survive
enforcement is refused, not migrated.
"""

import re
import sqlite3

# The v2 texts of the tables this step touches — `scenes` and `journals`
# shipped unchanged since v1, `characters` is what step 2 wrote.
_V2_SCENES = """CREATE TABLE scenes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id         INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    start_message_id INTEGER NOT NULL,
    end_message_id   INTEGER NOT NULL,
    title            BLOB,
    summary          BLOB,               -- this scene only; append-only
    history          BLOB,               -- story-so-far THROUGH this scene; latest = the arc
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (story_id, id),               -- composite-FK target: same-story references only
    UNIQUE (story_id, start_message_id),
    FOREIGN KEY (story_id, start_message_id) REFERENCES messages(story_id, id),
    FOREIGN KEY (story_id, end_message_id)   REFERENCES messages(story_id, id)
)"""

# What changes against V2: the start-uniqueness line goes — a rewound
# branch may close a scene starting where an abandoned one did.
_V3_SCENES = """CREATE TABLE scenes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id         INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    start_message_id INTEGER NOT NULL,
    end_message_id   INTEGER NOT NULL,
    title            BLOB,
    summary          BLOB,               -- this scene only; append-only
    history          BLOB,               -- story-so-far THROUGH this scene; latest = the arc
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (story_id, id),               -- composite-FK target: same-story references only
    FOREIGN KEY (story_id, start_message_id) REFERENCES messages(story_id, id),
    FOREIGN KEY (story_id, end_message_id)   REFERENCES messages(story_id, id)
)"""

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

# What changes against V2: the composite-FK target `UNIQUE (story_id, id)`.
_V3_CHARACTERS = """CREATE TABLE characters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    name        BLOB NOT NULL,
    aliases     BLOB,                    -- JSON array, sealed
    description BLOB,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    card        BLOB,                    -- an imported card as TOML
    UNIQUE (story_id, id)                -- composite-FK target: same-story references only
)"""

_V2_JOURNALS = """CREATE TABLE journals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id     INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    scene_id     INTEGER NOT NULL,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    entry        BLOB NOT NULL,          -- their record of this scene only
    state        BLOB NOT NULL,          -- snapshot right now; latest row wins
    history      BLOB,                   -- cumulative rollup from their entries
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (scene_id, character_id),
    FOREIGN KEY (story_id, scene_id) REFERENCES scenes(story_id, id) ON DELETE CASCADE
)"""

# What changes against V2: the character reference widens to the
# same-story composite — text only, enforced at runtime, no index moves.
_V3_JOURNALS = """CREATE TABLE journals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id     INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    scene_id     INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    entry        BLOB NOT NULL,          -- their record of this scene only
    state        BLOB NOT NULL,          -- snapshot right now; latest row wins
    history      BLOB,                   -- cumulative rollup from their entries
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (scene_id, character_id),
    FOREIGN KEY (story_id, scene_id) REFERENCES scenes(story_id, id) ON DELETE CASCADE,
    FOREIGN KEY (story_id, character_id) REFERENCES characters(story_id, id) ON DELETE CASCADE
)"""

# The rebuilt tables' named indexes, dropped with them — exactly the text
# `schema.py` shipped, so fresh-equals-migrated holds byte for byte.
_V3_INDEXES = (
    "CREATE INDEX idx_scenes_story      ON scenes (story_id)",
    "CREATE INDEX idx_scenes_end        ON scenes (end_message_id)",
    "CREATE INDEX idx_characters_story  ON characters (story_id)",
)


def to_3(conn: sqlite3.Connection) -> None:
    _rebuild(
        conn,
        "scenes",
        _V2_SCENES,
        _V3_SCENES,
        "id, story_id, start_message_id, end_message_id, title, summary, history, created_at, updated_at",
    )
    _rebuild(
        conn,
        "characters",
        _V2_CHARACTERS,
        _V3_CHARACTERS,
        "id, story_id, name, aliases, description, created_at, updated_at, card",
    )
    _rewrite(conn, "journals", _V2_JOURNALS, _V3_JOURNALS)
    for index in _V3_INDEXES:
        conn.execute(index)
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise sqlite3.DatabaseError("foreign keys do not hold after the rebuild")


def _rewrite(conn: sqlite3.Connection, table: str, expect: str, write: str) -> None:
    """One table's stored DDL replaced under `writable_schema`, refused
    unless it matches what the step expects — a hand-edited schema is
    never guessed at. Sound for constraint text only: nothing on disk
    depends on an FK clause."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    if row is None or _normalized(row[0]) != _normalized(expect):
        raise sqlite3.DatabaseError(f"{table} DDL is not what schema version 2 shipped")
    conn.execute("PRAGMA writable_schema = ON")
    # fmt: off
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?", (write, table)
    )
    # fmt: on
    conn.execute("PRAGMA writable_schema = OFF")


def _rebuild(conn: sqlite3.Connection, table: str, expect: str, write: str, columns: str) -> None:
    """A table recreated under its target DDL — for the constraint changes
    `_rewrite` cannot make: a UNIQUE lives as a real index (a b-tree and a
    `sqlite_master` row), so dropping or adding one needs the documented
    rebuild, not a text edit. Same refusal rule as `_rewrite`. The RENAME
    quotes the table name in the stored text, so the target DDL is written
    back under `writable_schema` as the last touch; the caller recreates
    the named indexes the DROP took with the table."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    if row is None or _normalized(row[0]) != _normalized(expect):
        raise sqlite3.DatabaseError(f"{table} DDL is not what schema version 2 shipped")
    conn.execute(write.replace(f"CREATE TABLE {table} (", f"CREATE TABLE mig_{table} (", 1))
    conn.execute(f"INSERT INTO mig_{table} ({columns}) SELECT {columns} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE mig_{table} RENAME TO {table}")
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
