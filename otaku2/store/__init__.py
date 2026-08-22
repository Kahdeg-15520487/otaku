"""The story store: SQLite (optionally encrypted) behind explicit operations.

`Store.open` builds the database nucleus over the paths it is handed and
exposes one ops group per table:

    store.stories     stories and their message trees (source)
    store.messages    individual messages (source)
    store.scenes      scenes and the story-so-far rollup (derivatives)
    store.characters  the cast (derivatives)
    store.journals    per-character memory (derivatives)
    store.usage       token accounting
    store.history     the terminal's Up/Down input history
"""

from pathlib import Path
from typing import Self

from otaku2.encryption import Cipher
from otaku2.store.database import Database, DatabaseError, is_encrypted
from otaku2.store.ops.lore import CharacterOps, JournalOps, SceneOps
from otaku2.store.ops.records import HistoryOps, UsageOps
from otaku2.store.ops.stories import MessagesOps, StoryOps

__all__ = ["DatabaseError", "Store", "is_encrypted"]


class Store:
    def __init__(self, db: Database) -> None:
        self.stories = StoryOps(db)
        self.messages = MessagesOps(db)
        self.scenes = SceneOps(db)
        self.characters = CharacterOps(db)
        self.journals = JournalOps(db)
        self.usage = UsageOps(db)
        self.history = HistoryOps(db)
        self._db = db

    @classmethod
    def open(cls, db_path: Path, cipher: Cipher, *, backups_dir: Path, keep: int) -> Self:
        """`Database.open`'s contract (creation, migration, the canary,
        the daily backup), wrapped with the ops groups."""
        return cls(Database.open(db_path, cipher, backups_dir=backups_dir, keep=keep))

    @property
    def notes(self) -> list[str]:
        """The nucleus's administrative facts (migration ran, backup
        written or failed) — the caller logs them; the store never does."""
        return self._db.notes

    def close(self) -> None:
        self._db.close()
