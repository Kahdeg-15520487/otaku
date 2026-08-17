"""/card — import a character card into the current story.

An import is three writes and NO model call. The `/card` line itself
lands as a `kind='card'` user turn, stored AS TYPED like every framing
command — the wire composes the card block from the archive at request
time (the assembler, via `framing.card_to_wire`), found through the
row's speaker link, so a `/lore` correction to the TOML reaches every
future request. The cast row carries the card's fields as that TOML
(`characters.card`). The greeting — the character's own first words —
lands as an AUTHORED assistant turn, speaker set, provider `card` and
the file's name for a model — the source, spelled the way generated rows
spell theirs: the card introduces the character and the character
answers, so the model continues the voice, and `/undo` takes the
exchange whole — the unplayed character with it, so a retry is never
refused as a duplicate.

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

from otaku.chat.framing import card_to_wire
from otaku.chat.session import Session, message
from otaku.paths import existing_file
from otaku.store import Store
from otaku.store.schema import Message
from otaku.terminal import DIM, RESET, error_line
from otaku.terminal.cursor import measure, terminal_width
from otaku.transfer.card import CardError, bind, card_toml, load_card

# A card block above roughly this many tokens gets a warning: it rides
# every request verbatim and never leaves the context, so on a small
# local window it crowds out the story itself.
_LARGE_CARD_TOKENS = 4000


def cmd_card(session: Session, store: Store, args: list[str]) -> None:
    """`/card FILE [NAME]` — FILE is a card PNG or JSON; NAME renames the
    character at import (the card's own name is only its default)."""
    raw = session.raw_args.strip().removeprefix("@")
    if not raw:
        # /card manages the screen, so every path that prints below the
        # last exchange instead of playing must invalidate, like any
        # fallback print site.
        print("Usage: /card FILE [NAME]")
        session.screen.invalidate()
        return
    path, rename = _file_and_name(raw)
    try:
        data = path.read_bytes()
    except OSError as e:
        print(error_line(f"Could not read {path}: {e}"))
        session.screen.invalidate()
        return
    try:
        card, notes = load_card(data, file_name=path.name)
    except CardError as e:
        print(error_line(f"Not a character card: {e}"))
        session.screen.invalidate()
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
            session.screen.invalidate()
            return
    persona = _ask_persona(session, _remembered_persona(store, session.story_id) or "you")
    toml = card_toml(card, user=persona)
    block = card_to_wire(toml, session.prompts.card_framing)

    session.record_turn(store, Message(role="user", body=f"/card {raw}", kind="card"))
    assert session.story_id is not None  # record_turn just ensured it
    character_id = store.characters.add(session.story_id, card.name, card=toml)
    # The speaker link is the compose key: the row was recorded before the
    # cast row could exist, so the attribution follows it.
    row = session.messages[-1]
    store.messages.set_speaker(row.id, character_id, card.name)
    session.messages[-1] = replace(row, speaker=card.name, speaker_id=character_id)
    greeting = bind(card.greeting, char=card.name, user=persona)
    if greeting:
        session.record_turn(
            store,
            Message(
                role="assistant",
                body=greeting,
                kind="dialogue",
                speaker=card.name,
                speaker_id=character_id,
                # The source, spelled the way generated rows spell theirs:
                # no model wrote this — the card's file did.
                provider="card",
                model=path.name,
            ),
        )

    # The import plays like a submission: the typed line (and the ask)
    # erased and re-echoed as the grey block, the report and the greeting
    # riding the exchange — so /undo takes the screen back whole.
    session.screen.echo_block(message(f"/card {raw}", "user"))
    size = len(block) // 4
    report = [f"imported {card.name} (card ≈ {size} tokens)", *notes]
    if size > _LARGE_CARD_TOKENS:
        report.append("a large card — it rides every request and never leaves the context")
    print(f"{DIM}[ {' · '.join(report)} ]{RESET}", file=session.screen.reply)
    if greeting:
        print(file=session.screen.reply)
        print(session.rendered_turn(session.messages[-1]), file=session.screen.reply)


def drop_unplayed_card(session: Session, store: Store, popped: list[Message]) -> None:
    """Undoing a card import takes the character with it — while they are
    UNPLAYED: the import wrote the row, the undo unwrites it, and the
    duplicate refusal stops blocking a retry (the reason imports get
    undone at all). A journal marks them played — extraction wove them
    into the story — and then the cast row stays: a character with
    history is story, not import residue."""
    assert session.story_id is not None  # undo just popped from this story
    for row in popped:
        if row.kind != "card" or row.speaker_id is None:
            continue
        journaled = any(
            j.character_id == row.speaker_id for j in store.journals.list(session.story_id)
        )
        if not journaled:
            store.characters.delete(row.speaker_id)


def _file_and_name(raw: str) -> tuple[Path, str]:
    """`FILE [NAME]` split by what EXISTS: the longest leading run of
    tokens naming a real file is the file, the rest is the rename — so
    both a path with spaces and a multi-word name read correctly. Nothing
    matching falls through whole, for `read_bytes` to refuse honestly."""
    tokens = raw.split()
    for i in range(len(tokens), 0, -1):
        candidate = existing_file(" ".join(tokens[:i]))
        if candidate is not None:
            return candidate, " ".join(tokens[i:]).strip()
    return Path(raw).expanduser(), ""


def _ask_persona(session: Session, default: str) -> str:
    """Who the player is in this story — `{{user}}` in every card text.
    Enter takes the default; a non-tty stdin never blocks on the ask. The
    echoed ask joins the typed rows, so the block echo replaces it along
    with the typed line — including the dispatch window's lead blank,
    taken by hand here: `input()` writes its prompt through the wrapped
    stdout, and a blank the wrapper slipped in uncounted would leave the
    erase one row short."""
    if not sys.stdin.isatty():
        return default
    if session.screen.take_lead_blank():
        print()
        session.screen.typed_rows += 1
    prompt = f"User name for the card [{default}]: "
    answer = input(prompt).strip()
    session.screen.typed_rows += measure(prompt + answer + "\n", terminal_width())
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
