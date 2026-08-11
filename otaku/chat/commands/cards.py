"""/card — import a character card into the current story.

An import is three writes and NO model call. The composed card block
lands as a `kind='card'` user turn — a card import is a prompt, appended
like any other, and the block is what the model will read from then on.
The cast row carries the card's fields as TOML (`characters.card`), the
source the block was built from and the archive later features read. The
greeting — the character's own first words — lands as an ordinary
dialogue turn, user-role with the speaker set: authored content the
writer brought, the same shape a `/me` line leaves. The player answers
the greeting, and that reply is the story's next inference; importing
never speaks for anyone.

The persona: card text addresses `{{user}}` constantly, so the import
asks who that is — once per story, in effect, because the default is
read back from the latest imported card's own TOML. A non-tty stdin
takes the default silently.
"""

import sys
import tomllib
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from otaku.chat.session import Session, message
from otaku.store import Store
from otaku.store.schema import Message
from otaku.terminal import error_line, user_block
from otaku.transfer.cards import CardError, bind, card_toml, compose, load_card

# A card block above roughly this many tokens gets a warning: it rides
# every request verbatim and never leaves the context, so on a small
# local window it crowds out the story itself.
_LARGE_CARD_TOKENS = 4000


def cmd_card(session: Session, store: Store, args: list[str]) -> None:
    """`/card FILE [NAME]` — FILE is a card PNG or JSON; NAME renames the
    character at import (the card's own name is only its default)."""
    raw = session.raw_args.strip().removeprefix("@")
    if not raw:
        print("Usage: /card FILE [NAME]")
        return
    path, rename = _file_and_name(raw)
    try:
        data = path.read_bytes()
    except OSError as e:
        print(error_line(f"Could not read {path}: {e}"))
        return
    try:
        card, notes = load_card(data, file_name=path.name)
    except CardError as e:
        print(error_line(f"Not a character card: {e}"))
        return
    if rename:
        card = replace(card, name=rename)
    if session.story_id is not None:
        existing = store.characters.find(session.story_id, card.name)
        if existing is not None:
            # A refusal, not a failure: the cast already answers to this
            # name — importing over it would double the character.
            source = "imported earlier" if existing.card else "extracted from play"
            print(
                f"{existing.name} already exists in this story ({source}) — "
                f"import under another name: /card FILE NAME."
            )
            return
    persona = _ask_persona(_remembered_persona(store, session.story_id) or "you")
    toml = card_toml(card, user=persona)
    block = compose(toml, session.prompts.card_framing)

    session.record_turn(store, Message(role="user", body=block, kind="card"))
    assert session.story_id is not None  # record_turn just ensured it
    character_id = store.characters.add(session.story_id, card.name, card=toml)
    greeting = bind(card.greeting, char=card.name, user=persona)
    if greeting:
        session.record_turn(
            store,
            Message(
                role="user",
                body=greeting,
                kind="dialogue",
                speaker=card.name,
                speaker_id=character_id,
            ),
        )

    for note in notes:
        print(note)
    size = len(block) // 4
    print(f"Imported {card.name} (card ≈ {size} tokens).")
    if size > _LARGE_CARD_TOKENS:
        print("A large card — it rides every request verbatim and never leaves the context.")
    if greeting:
        print()
        print(user_block(message(greeting, "user")))


def _file_and_name(raw: str) -> tuple[Path, str]:
    """`FILE [NAME]` split by what EXISTS: the longest leading run of
    tokens naming a real file is the file, the rest is the rename — so
    both a path with spaces and a multi-word name read correctly. Nothing
    matching falls through whole, for `read_bytes` to refuse honestly."""
    tokens = raw.split()
    for i in range(len(tokens), 0, -1):
        candidate = Path(" ".join(tokens[:i])).expanduser()
        if candidate.is_file():
            return candidate, " ".join(tokens[i:]).strip()
    return Path(raw).expanduser(), ""


def _ask_persona(default: str) -> str:
    """Who the player is in this story — `{{user}}` in every card text.
    Enter takes the default; a non-tty stdin never blocks on the ask."""
    if not sys.stdin.isatty():
        return default
    answer = input(f"Play as [{default}]: ").strip()
    return answer or default


def _remembered_persona(store: Store, story_id: int | None) -> str:
    """The story's own memory of the persona: the `user` binding recorded
    in the latest imported card's TOML — so a story asks once and later
    imports default to the same name, with no setting anywhere."""
    if story_id is None:
        return ""
    for character in reversed(store.characters.list(story_id)):
        if not character.card:
            continue
        with suppress(tomllib.TOMLDecodeError):
            user = tomllib.loads(character.card).get("user")
            if isinstance(user, str) and user:
                return user
    return ""
