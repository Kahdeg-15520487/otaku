"""The prompt assembler — composes what the model sees each turn.

The shape is deliberately story-like, because injected structure breaks a
roleplay model's prose. The system message is the user's own text,
untouched. Then the transcript as HEAD + RECAP + TAIL:

- the first `head_messages` verbatim (the opening carries the story's
  voice),
- the closed scenes between head and tail as their summaries, in order,
  rendered as one recap interlude opened by `recap_header` — prose and
  nothing else; journals stay in the store, never in the prompt,
- the tail verbatim, aligned to a scene boundary: it starts right after
  the last summarized scene's end, targeting the most recent
  `tail_messages`.

Card rows (`kind='card'`) are the one exception to the middle's
replacement: a card is never summarized and never evicted. One inside a
summarized region rides the recap verbatim, in front of its scene's
summary — position deliberately does not matter for reference text, its
retention does — charged to the whole budget, never the recap's fraction,
and immune to the trim.

Inside the assembler every part is a row: the header, the rollup, and
each summary are synthesized user turns (`kind="recap"` — wire-only,
such a row is never stored), so the recap is joined by the one merge in
`_wire_turns` — nothing is hand-glued. Card and recap rows ARE their
wire text and never go through `prompt_to_wire`: a card row stores the
`/card` line as typed and its block is composed from the character's
CURRENT archive as the request assembles (`assemble_story`), a summary
is prose, and neither is a typed prompt to parse for syntax.

The recap is capped at `_RECAP_FRACTION` of the budget: beyond it the
oldest summaries drop out and the story-so-far rollup takes their place at
the front, so the story never outgrows its own recap. A short story — or
one with no covering scene — goes out all-verbatim.

Message bodies go out exactly as stored — never rewritten, no `Name:`
prefixes, no turn-taking guards: prose carries its own attribution, and
the wire promise is that the code adds NOTHING but the recap (`/context`
and the request log show it holding). The `/me`, `/you`, and `/ooc`
directions live in a turn's `template` and are filled with its body
(`chat.framing.prompt_to_wire`) only at wire time.

The wire unit is the exchange: consecutive same-role rows (a `/me`
direction beside its line, the recap beside the tail) merge into one turn,
blank-line separated, so the wire alternates the way a chat API expects.
Roles are fixed as stored — nothing relabels them.

Token counts are estimated at ~4 chars/token — close enough for budgeting
without a tokenizer dependency. When the window still overflows, the
tail's oldest messages drop first, and the cut is snapped to a
`_TRIM_BLOCK` boundary so the same message starts the tail for many turns
in a row instead of sliding every turn (a rolling cut would invalidate the
server's prompt cache on every request).
"""

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from otaku.chat.framing import card_to_wire, prompt_to_wire
from otaku.store import Store
from otaku.store.schema import Message, Scene

_DEFAULT_CONTEXT = 8_192  # when the backend doesn't expose the loaded window
_RESPONSE_RESERVE = 1_024  # tokens left for the model's reply
_MIN_KEEP = 2  # never trim the transcript below this many messages
_TRIM_SLACK = 0.1  # over-budget trims aim this far below budget (headroom)
# The trim's cut is snapped to a multiple of this, so the tail starts at
# the same message for this many turns instead of sliding every turn.
_TRIM_BLOCK = 10
# The recap may take at most this share of the budget. Beyond it, the
# OLDEST scene summaries drop out and the story-so-far rollup is prepended
# in their place.
_RECAP_FRACTION = 0.25


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class AssembledPrompt:
    """The wire-ready request plus the numbers behind it."""

    messages: list[Message]  # [system?] + the wire turns
    context_max: int
    system_tokens: int
    transcript_tokens: int  # head + recap + tail estimate
    head_count: int  # verbatim opening messages on the wire
    scenes_summarized: int  # scene summaries standing in for the middle
    recap: str  # the recap text, "" when none (/context's preview keys on it)
    transcript_kept: int  # verbatim messages on the wire (head + tail)
    transcript_total: int

    @property
    def total_tokens(self) -> int:
        return self.system_tokens + self.transcript_tokens


class StoryView(Protocol):
    """What `assemble_story` reads off a session or a worker job: the
    story, its transcript, and the shaping settings."""

    @property
    def story_id(self) -> int | None: ...
    @property
    def system(self) -> str: ...
    @property
    def messages(self) -> list[Message]: ...
    @property
    def recap_header(self) -> str: ...
    @property
    def card_framing(self) -> str: ...
    @property
    def head_messages(self) -> int: ...
    @property
    def tail_messages(self) -> int: ...


@dataclass
class _Chapter:
    """One covered scene of the recap: its summary and the card rows its
    span held — paired so the cap can drop a summary without losing what
    must float (`_recap_rows`)."""

    cards: list[Message]
    summary: str


def assemble_story(store: Store, view: StoryView, context_max: int | None) -> AssembledPrompt:
    """`assemble` over the story's current scenes — the one wrapper every
    call site (the turn, /context, the warm-up) goes through, so none can
    disagree on what the next request looks like. Card rows compose HERE,
    from the cast's CURRENT archives: the stored row is the line as
    typed, and what it sends follows the TOML wherever `/lore` took it."""
    scenes = _current_scenes(store, view.story_id, view.messages)
    return assemble(
        view.system,
        _composed_cards(store, view),
        context_max,
        scenes=scenes,
        recap_header=view.recap_header,
        head_messages=view.head_messages,
        tail_messages=view.tail_messages,
    )


def assemble(
    system: str,
    messages: list[Message],
    context_max: int | None,
    *,
    scenes: Sequence[Scene] = (),
    recap_header: str = "",
    head_messages: int = 20,
    tail_messages: int = 150,
) -> AssembledPrompt:
    """Compose the next request from the session's transcript and the
    story's current scenes (see `current_scenes`). With no covering scene —
    or a transcript short enough — this degrades to the raw prompt a plain
    chat would send. `recap_header`, when given, opens the recap block; it
    is sent, so `/context` needs no heading of its own."""
    window = context_max or _DEFAULT_CONTEXT
    system_tokens = estimate_tokens(system) if system else 0
    budget = max(0, window - _RESPONSE_RESERVE - system_tokens)

    head, chapters, tail = _split_transcript(messages, scenes, head_messages, tail_messages)
    recap_rows, kept_summaries = _recap_rows(chapters, scenes, recap_header, budget)
    # The recap's cost and /context's marker are its merged text — the
    # join `_wire_turns` will make of these rows.
    recap = "\n\n".join(_wire_text(m) for m in recap_rows)

    used = (
        sum(_wire_tokens(m) for m in head)
        + (estimate_tokens(recap) if recap else 0)
        + sum(_wire_tokens(m, is_last=i == len(tail) - 1) for i, m in enumerate(tail))
    )
    if used > budget:
        used, head, tail = _trim_overflow(used, head, tail, budget)

    wire: list[Message] = []
    if system:
        wire.append(Message(role="system", body=system))
    wire.extend(_wire_turns(head + recap_rows + tail))
    return AssembledPrompt(
        messages=wire,
        context_max=window,
        system_tokens=system_tokens,
        transcript_tokens=used,
        head_count=len(head),
        scenes_summarized=kept_summaries,
        recap=recap,
        transcript_kept=len(head) + len(tail),
        transcript_total=len(messages),
    )


# ---------- assembly internals ----------


def _current_scenes(store: Store, story_id: int | None, messages: list[Message]) -> list[Scene]:
    if story_id is None or not messages:
        return []
    return store.scenes.get_current(story_id, [m.id for m in messages])


def _composed_cards(store: Store, view: StoryView) -> list[Message]:
    """The transcript with each card row's wire text composed from its
    character's archive (`framing.card_to_wire`), found through the
    row's speaker link. A row with no reachable archive — the body
    predates the typed-row shape, or the link is gone — sends its body as
    it stands."""
    if view.story_id is None or all(m.kind != "card" for m in view.messages):
        return view.messages
    archives = {c.id: c.card for c in store.characters.list(view.story_id) if c.card}
    out: list[Message] = []
    for m in view.messages:
        toml = archives.get(m.speaker_id) if m.kind == "card" and m.speaker_id else None
        out.append(replace(m, body=card_to_wire(toml, view.card_framing)) if toml else m)
    return out


def _split_transcript(
    messages: list[Message],
    scenes: Sequence[Scene],
    head_messages: int,
    tail_messages: int,
) -> tuple[list[Message], list[_Chapter], list[Message]]:
    """HEAD + the covered scenes as chapters + TAIL. The tail is
    scene-aligned: it starts right after the last summarized scene's end,
    targeting the most recent `tail_messages`. Scenes ending inside the
    head or the tail stay verbatim there and are not summarized.

    A card row in the replaced region is never replaced with it: it joins
    the chapter of the first covered scene ending at or after it — the
    summary it will stand in front of. A card's position deliberately
    does not matter, its retention does. Falls back to
    everything-verbatim when the transcript is short or no scene summary
    covers the middle."""
    if len(messages) <= head_messages + tail_messages:
        # Everything verbatim — but split the head off anyway: a story can
        # be short by count and still overflow the window, and the trim
        # drops the tail's oldest first. The opening must never be what
        # overflows: the head is always sent verbatim.
        return messages[:head_messages], [], messages[head_messages:]
    position = {m.id: i for i, m in enumerate(messages)}
    head_end = head_messages - 1
    tail_target = len(messages) - tail_messages
    covered = [
        s
        for s in scenes
        if s.summary and head_end < position.get(s.end_message_id, -1) < tail_target
    ]
    if not covered:
        # Everything verbatim — but split the head off anyway: under
        # overflow the tail trims oldest-first, and the opening must
        # never be what overflows (the head is always sent verbatim).
        return messages[:head_messages], [], messages[head_messages:]
    boundary = position[covered[-1].end_message_id]
    chapters = [_Chapter(cards=[], summary=s.summary) for s in covered]
    ends = [position[s.end_message_id] for s in covered]
    for m in messages[head_messages : boundary + 1]:
        if m.kind == "card":
            chapters[bisect_left(ends, position[m.id])].cards.append(m)
    return messages[:head_messages], chapters, messages[boundary + 1 :]


def _recap_rows(
    chapters: list[_Chapter],
    scenes: Sequence[Scene],
    recap_header: str,
    budget: int,
) -> tuple[list[Message], int]:
    """The recap as wire-ready rows, plus how many scene summaries ride
    it: each chapter's cards in front of its summary, oldest chapter
    first — capped at `_RECAP_FRACTION` of the budget, the oldest
    summaries dropping out and the story-so-far rollup (the newest scene
    history) taking their place.

    The cap weighs summaries alone: card rows are charged to the WHOLE
    budget, never to the recap's fraction — one large card would
    otherwise keep the cap permanently overflowed and silently evict
    every summary — and they never drop: a dropped chapter's cards float
    to the front, above the rollup that replaced their summary."""
    if not chapters:
        return [], 0
    recap_budget = int(budget * _RECAP_FRACTION)
    kept = list(chapters)
    used = sum(estimate_tokens(ch.summary) for ch in kept)
    floated: list[Message] = []
    while len(kept) > 1 and used > recap_budget:
        dropped = kept.pop(0)
        used -= estimate_tokens(dropped.summary)
        floated.extend(dropped.cards)

    rows: list[Message] = []
    if recap_header:
        rows.append(_recap_row(recap_header))
    rows.extend(floated)
    if len(kept) < len(chapters):
        story_so_far = next((s.history for s in reversed(scenes) if s.history), "")
        if story_so_far:
            rows.append(_recap_row(story_so_far))
    for chapter in kept:
        rows.extend(chapter.cards)
        rows.append(_recap_row(chapter.summary))
    return rows, len(kept)


def _recap_row(text: str) -> Message:
    """A synthesized user turn of the recap — marked wire-only, its body
    already wire text (see `_wire_text`)."""
    return Message(role="user", body=text, kind="recap")


def _trim_overflow(
    used: int, head: list[Message], tail: list[Message], budget: int
) -> tuple[int, list[Message], list[Message]]:
    """Over budget: drop the tail's oldest messages, aiming `_TRIM_SLACK`
    below budget, then snap the cut FORWARD to a `_TRIM_BLOCK` multiple so
    the boundary stays put across turns — unless the window is so tight the
    block would eat half of what fits, where the cache is a lost cause
    anyway and context wins. The head is sent verbatim while anything else
    can give: only when the tail is down to its floor does the head's own
    start trim — a window the whole opening cannot fit beats no request.
    Card rows are never dropped from either end: never-evicted is the
    card promise, and a window they alone overflow is the user's call
    (the import warned)."""
    target = budget - int(budget * _TRIM_SLACK)
    dropped = 0
    while dropped < len(tail) - 1 and len(head) + len(tail) - dropped > _MIN_KEEP:
        if used <= target:
            break
        used -= _wire_tokens(tail[dropped])
        dropped += 1
    affordable = len(tail) - dropped
    snapped = min(
        -(-dropped // _TRIM_BLOCK) * _TRIM_BLOCK,
        max(0, len(tail) - 1),
        max(0, len(head) + len(tail) - _MIN_KEEP),
    )
    if len(tail) - snapped >= max(_MIN_KEEP, affordable // 2):
        used -= sum(_wire_tokens(m) for m in tail[dropped:snapped])
        dropped = snapped
    # A card is never evicted: the cut passes over card rows and they stay
    # on the wire wherever it lands, their tokens restored to the count.
    rescued = [m for m in tail[:dropped] if m.kind == "card"]
    used += sum(_wire_tokens(m) for m in rescued)
    tail = rescued + tail[dropped:]
    lost = 0
    while used > target and lost < len(head) and len(head) - lost + len(tail) > _MIN_KEEP:
        if head[lost].kind == "card":
            break  # the head's own trim stops at a card rather than skip it
        used -= _wire_tokens(head[lost])
        lost += 1
    return used, head[lost:], tail


def _wire_text(message: Message, *, is_last: bool = False) -> str:
    """One row's wire text. A card or recap row's body IS its wire text —
    composed at import, or synthesized here — and never goes through
    `prompt_to_wire`: card prose that happens to spell an inliner
    (` /cue …` in an example) would be split as syntax, and summary prose
    is not a typed prompt either."""
    if message.kind in ("card", "recap"):
        return message.body
    return prompt_to_wire(message.body, message.template, is_last=is_last)


def _wire_tokens(message: Message, *, is_last: bool = False) -> int:
    """Tokens one row costs on the wire. `is_last` defaults to False for
    the trim, which only ever weighs rows it is dropping — and the newest
    row is never dropped (the two-message floor keeps it)."""
    return estimate_tokens(_wire_text(message, is_last=is_last))


def _wire_turns(kept: list[Message]) -> list[Message]:
    """Transcript rows → wire turns: each turn's own text and nothing else.
    Consecutive same-role rows rejoin into one turn — storage granularity is
    otaku's bookkeeping; the model sees one prompt per exchange."""
    out: list[Message] = []
    for position, message in enumerate(kept):
        # Newest = the LAST POSITION, never object identity: two turns can
        # hold the same text, and only where a row sits decides whether its
        # cue is still live.
        text = _wire_text(message, is_last=position == len(kept) - 1)
        if out and out[-1].role == message.role:
            out[-1] = Message(role=message.role, body=out[-1].body + "\n\n" + text)
        else:
            out.append(Message(role=message.role, body=text))
    return out
