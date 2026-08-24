"""Story operations: what the browser and the story commands do.

Every story-level write a frontend may ask for lives here and keeps the
session in sync — the reason a frontend never edits or deletes through
the store itself. (Chain-changing writes exist in play/cards/transfer
too; ALL of them go through the session's own primitives, which carry
the sync and the search-index invalidation.)
"""

from dataclasses import replace
from typing import Literal

from otaku.backend.session import Refused, Session
from otaku.formatting import flatten, truncate_label
from otaku.store.ops.stories import StoryListing
from otaku.store.schema import Message

# What picking an earlier turn settles to: continue in a copy (the
# default), rewind the head (later turns stay as siblings), or stay.
LandAction = Literal["resume", "fork", "truncate"]

# A label INSIDE a backend sentence (the landed line, a fork notice, the
# info report) is cut here, as part of the wording — an unbounded name
# breaks a one-line sentence on any medium. `headline` itself stays
# uncut: raw material for surfaces that own their width (the banner cuts
# to this same number via `formatting.truncate_label`).
LABEL_WIDTH = 50


def listing(session: Session) -> list[StoryListing]:
    """Every story, most recently played first."""
    return session._store.stories.list()


def messages_of(session: Session, story_id: int) -> list[Message]:
    """One story's current chain, for the browser's drill-in."""
    return session._store.stories.get_messages(story_id)


def search(session: Session, query: str) -> list[int]:
    """Ids of the stories that match `query`, case-insensitive — the ONE
    filter rule both browsers promise, one call per keystroke: a story
    matches on its buried content (the CURRENT CHAIN's text) or on the
    face its listing row shows (label, arc summary, first prompt,
    model). Declared here because two frontends filtering by different
    halves would be two browsers finding different stories.

    The content half is served from the session-held index
    (`_search_index`), built on the first search and invalidated by the
    SESSION's write primitives — where every chain-changing write
    already funnels (play, undo, cards, imports, this module) — so a
    keystroke never re-decrypts the library and the corpus never crosses
    the boundary. Best-effort throughout: a filter is never worth a
    failure, so a store hiccup narrows the match rather than raising."""
    if session._search_index is None:
        try:
            session._search_index = session._store.stories.get_texts()
        except Exception:
            session._search_index = {}
    needle = query.strip().lower()
    if not needle:
        return list(session._search_index)
    ids = {sid for sid, text in session._search_index.items() if needle in text}
    try:
        rows = session._store.stories.list()
    except Exception:
        rows = []
    for row in rows:
        if needle in f"{row.label} {row.story_so_far} {row.first_user} {row.model}".lower():
            ids.add(row.id)
    return sorted(ids)


def land(session: Session, story_id: int, upto_message_id: int, action: LandAction) -> str:
    """Execute what the browser settled — resume as-is, fork at the
    picked turn, or truncate to it — switch the session there, and return
    the landing line ("Story: …. Resumed at message 14.")."""
    store = session._store
    messages = store.stories.get_messages(story_id)
    position = next((i for i, m in enumerate(messages) if m.id == upto_message_id), None)
    if position is None:
        raise Refused("That message is not on the story's current chain.")
    if action == "fork":
        forked = store.stories.fork(story_id, from_message_id=upto_message_id)
        session._search_index = None
        session._switch_to(forked)
        label = truncate_label(headline(session), LABEL_WIDTH)
        lead = f"Forked to: {label}." if label else "Forked."
        return f"{lead} Continued from message {len(session.messages)}."
    if action == "truncate":
        store.stories.set_head(story_id, upto_message_id)
        session._search_index = None
        session._switch_to(story_id, messages[: position + 1])
        return _landed(session, verb="Truncated")
    # Resume attaches to the story as-is — the tail was picked, so the
    # chain and the pick agree and nothing changes in the store.
    session._switch_to(story_id)
    return _landed(session)


def fork(session: Session, raw: str = "") -> str:
    """Continue in a copy of this story from here; the original stays.
    `raw` is the optional TITLE — "" inherits a numbered one ("<title>
    - N", or none when the story has none). Returns the notice. Raises
    Refused when there is nothing to fork."""
    if session.story_id is None or not session.messages:
        raise Refused("Nothing to fork yet — send a message first.")
    forked = session._store.stories.fork(session.story_id, title=raw.strip() or None)
    session._search_index = None
    session._switch_to(forked)
    # Named the way the browser's fork names it.
    label = truncate_label(headline(session), LABEL_WIDTH)
    return f"Forked to: {label}." if label else "Forked."


def new(session: Session, raw: str = "") -> str:
    """Start a brand-new story, created AT ONCE — it is in the browser
    and carries its title before its first turn, not after. `raw` is the
    optional TITLE. Returns the notice."""
    title = raw.strip()
    session._switch_to(session._store.stories.add(title=title or None))
    session._search_index = None
    if not title:
        return "Started a new story."
    return f'Started a new story: "{truncate_label(title, LABEL_WIDTH)}".'


def set_title(session: Session, raw: str, story_id: int | None = None) -> str:
    """Title a story: the open one, or the one `story_id` names — a
    browser can reach every story, and a title is how a reader finds one
    again. Returns the confirmation.

    An empty title means two different things, and both are answered:
    asked of the OPEN story it is the bare command, which reports the
    title instead; asked of a NAMED one it is a rename that emptied the
    field, and it is refused rather than applied — a story with no title
    falls back to its own opening text, and clearing a title is a
    different decision from giving one."""
    title = raw.strip()
    if not title:
        if story_id is not None:
            raise Refused("A story needs a title — or leave the one it has.")
        story = (
            session._store.stories.get(session.story_id) if session.story_id is not None else None
        )
        current = story.title if story else ""
        return f'Title: "{current}"' if current else "Usage: /title NEW-TITLE"
    session._store.stories.set_title(story_id or session._ensure_story(), title)
    return f'Story title set to "{title}".'


def set_system(session: Session, text: str) -> str:
    """Set this story's system prompt (the premise) to `text` verbatim;
    "" reports the current one. It lives on the story, never on the
    model. The terminal's file affordance (`/system FILE`) resolves the
    file to text on ITS side — over HTTP a path must never name a
    server-side file. Returns the confirmation (or the report)."""
    if not text:
        return f'System: "{session.system}"' if session.system else "System: (none)"
    session._set_system(text)
    return f"System prompt set ({len(text)} chars)."


def delete(session: Session, story_id: int) -> None:
    """Drop a story and everything it owns — the one destructive act,
    and the user's. A session attached to it detaches."""
    session._store.stories.delete(story_id)
    session._search_index = None
    if session.story_id == story_id:
        session._story_id = None
        session._system = ""
        session._messages = []
        session._update_state()


def edit_message(session: Session, message_id: int, body: str) -> None:
    """The author's correction of one message — the session's in-memory
    copy follows the store. Raises Refused on an empty body."""
    if not body.strip():
        raise Refused("A message cannot be emptied — undo the exchange instead.")
    session._store.messages.update(message_id, body)
    session._search_index = None
    for i, m in enumerate(session._messages):
        if m.id == message_id:
            session._messages[i] = replace(m, body=body)
            break


def headline(session: Session) -> str:
    """The loaded story's name — `StoryListing.label`'s fallback rule
    applied to the loaded story (the rule has that ONE home), flattened
    to one line, UNCUT (display width is the frontend's). "" when
    nothing exists to name."""
    if session.story_id is None:
        return ""
    story = session._store.stories.get(session.story_id)
    if story is None:
        return ""
    label = story.title
    if not label:
        label = session._store.scenes.get_story_so_far(
            session.story_id, [m.id for m in session.messages]
        )
    if not label:
        label = next((m.body for m in session.messages if m.role == "user"), "")
    return flatten(label)


def landed_line(session: Session) -> str:
    """The one line a session prints when it lands in a story at launch
    ("Story: …. Resumed at message 14."). `land` composes its own line —
    the verb follows the action, and no frontend injects wording."""
    return _landed(session)


def _landed(session: Session, *, verb: str = "Resumed") -> str:
    """The landing line, `verb` naming what the pick settled. An unnamed
    story drops the first half rather than show an empty name."""
    label = truncate_label(headline(session), LABEL_WIDTH)
    head = f"Story: {label}. " if label else ""
    return f"{head}{verb} at message {len(session.messages)}."
