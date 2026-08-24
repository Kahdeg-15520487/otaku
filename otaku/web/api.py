"""What the page asks for, as plain data — this frontend's whole surface
over an open session, one table per kind of request.

`READS` is everything under `/api/read/`: one function per thing the
browser fetches, taking the session and returning something `json` can
write, each row adapting the request's query onto its function so the
query-string names live here and nowhere else. `ACTIONS` is every write
a screen performs; `FLOWS` the writes whose result outlives their
request (`Pending` is where it waits); `ANSWERS` the command lines this
frontend answers with a sentence. `play` and `regenerate` return the
reply's event stream and `event` names each event on the wire. What is
NOT here is HTTP: `web.server` looks a request up in these tables and
carries the result, and nothing else.

Nothing here decides how any of it LOOKS — where a paragraph breaks,
what a slash token is drawn as, how a count is worded — because that is
the page's business and the page is the only caller. And nothing here
reaches past `backend`: the facts come from `backend.api.reports`, the
language from `backend.commands`, so the web says exactly what the
terminal says.

Bodies cross VERBATIM, exactly as they were typed or as they streamed.
The web is the second reader of the same store, not a second author of
its text.
"""

import base64
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from typing import Any

from otaku import __version__
from otaku.backend import Message, commands, meminfo
from otaku.backend.api import cards as api_cards
from otaku.backend.api import lore as api_lore
from otaku.backend.api import play as api_play
from otaku.backend.api import providers as api_providers
from otaku.backend.api import reports
from otaku.backend.api import settings as api_settings
from otaku.backend.api import stories as api_stories
from otaku.backend.api import transfer as api_transfer
from otaku.backend.api.cards import PreparedCard
from otaku.backend.api.lore import Field, LoreView, WorkerRun
from otaku.backend.api.play import Declined, Done, Failed, PlayEvent, Recorded, Text, Thinking
from otaku.backend.api.providers import Engine
from otaku.backend.commands import (
    COMMANDS,
    GROUP_LABELS,
    PROSE_DESCRIPTION,
    PROSE_GROUP,
    PROSE_LABEL,
)
from otaku.backend.session import KNOWN_PARAMS, THINK_MENU, Refused, Session
from otaku.formatting import format_context, format_size

__all__ = [
    "ACTIONS",
    "ANSWERS",
    "FLOWS",
    "READS",
    "Pending",
    "add_card",
    "answering",
    "balance",
    "commands_table",
    "context",
    "event",
    "export_document",
    "facts",
    "import_document",
    "info",
    "lore",
    "play",
    "prepare_card",
    "providers",
    "regenerate",
    "search",
    "settings",
    "start_extract",
    "stories",
    "story_messages",
    "turns",
    "usage",
]

# ---------- the command surface ----------

# One OPERATION command: the raw argument text in, the sentence out —
# the shared table's enforceable contract, wired generically so a new
# operation is a row there and an entry here.
_Operation = Callable[[Session, str], str]

ANSWERS: dict[str, _Operation] = {
    # The shared table's OPERATION rows, wired generically — the
    # contract is exactly this call shape, so a new operation is a row
    # there and a row here.
    "/fork": api_stories.fork,
    # `/new` is an operation here where the terminal keeps a handler: it
    # swaps the story under the screen, and a page simply asks again.
    "/new": api_stories.new,
    "/title": api_stories.set_title,
    "/merge": api_lore.merge,
    # Text verbatim: the terminal resolves its `/system FILE`
    # affordance on its own side, because a path over HTTP would
    # name a file on the server.
    "/system": api_stories.set_system,
    "/set think": api_settings.set_think,
    "/set parameter": api_settings.set_parameter,
    "/set verbose": api_settings.set_verbose,
    "/set autocorrect": api_settings.set_autocorrect,
    "/set notification": api_settings.set_notification,
    # INTERACTIVE rows whose TYPED form is a plain call, answered here
    # while the bare token opens a screen — exactly as the terminal's
    # `/model PROVIDER/MODEL` switches and its bare `/model` opens the
    # picker.
    "/model": api_providers.switch_spec,
    "/undo": lambda session, raw: _undo(session),
}


def answering(line: str) -> Callable[[Session], dict[str, str]] | None:
    """The call a command line names — resolved WITHOUT the session, so
    the server answers an unknown token on its own thread, before
    anything queues. None for a line no wired row matches; what the call
    itself raises (Refused above all — a refusal IS the answer) stays
    the caller's to answer."""
    spec = commands.find(line)
    operation = ANSWERS.get(spec.token) if spec else None
    if spec is None or operation is None:
        return None
    argument = _argument(line, spec.token)
    call = operation
    return lambda session: {"notice": call(session, argument)}


def _argument(line: str, token: str) -> str:
    """Everything after the spec's token, verbatim from the first
    non-space character — the terminal's own rule
    (`terminal.chat.bindings._argument`), because a fixed-width slice
    disagrees with it the moment a line is typed untidily: "/set  think
    medium" would hand the backend "k  medium"."""
    rest = line
    for _ in token.split():
        _, _, rest = rest.lstrip().partition(" ")
    return rest.lstrip()


def _undo(session: Session) -> str:
    """Take back the trailing exchange — the popped rows are the page's
    cue to redraw, and the sentence says what happened. Nothing to take
    is a refusal like every other, so the page reads the `refused` flag
    the server marks them with and never the wording."""
    popped = api_play.undo(session)
    if not popped:
        raise Refused("Nothing to undo.")
    return f"Took back the last exchange ({len(popped)} messages)."


# ---------- what the page reads ----------


def facts(session: Session) -> dict[str, Any]:
    """The header's line and what else the page must know about the
    session it is drawing. Best-effort like the terminal's own opening:
    a cloud catalog is never asked for its context window here."""
    window = session.context_size()
    return {
        "version": __version__,
        "model": session.model or "(no model)",
        "engine": session.engine,
        "context": format_context(window) if window else "",
        "story": api_stories.headline(session),
        "story_id": session.story_id,
        "turns": len(session.messages),
        # The story's premise, as the screen that edits it opens on.
        "system": session.system,
        "think": session.think or "default",
        "verbose": session.verbose,
        "autocorrect": session.autocorrect,
        "notification": session.notification,
    }


def turns(session: Session) -> list[dict[str, Any]]:
    """The open story, one row per stored turn, oldest first."""
    return [_turn(message) for message in session.messages]


def commands_table() -> dict[str, Any]:
    """The shared table — the rows the help page lists, the page's menus
    offer, and its buttons carry. A command exists once.

    `groups` names them and `prose` is the row that is not a command:
    both decide what the help page SAYS, which is why neither is the
    page's to invent. Where each lands, and what it is drawn as, is the
    page's alone."""
    return {
        "prose": {
            "label": PROSE_LABEL,
            "group": PROSE_GROUP,
            "description": PROSE_DESCRIPTION,
        },
        "groups": GROUP_LABELS,
        # What this frontend can answer — the shared rows it wires. A
        # page reading this needs no table of its own to know whether a
        # click is a call or a screen.
        "answers": sorted(ANSWERS),
        "rows": [
            {
                "token": spec.token,
                "args": spec.args,
                "description": spec.description,
                "group": spec.group,
                "kind": spec.kind.value,
            }
            for spec in COMMANDS
        ],
    }


def stories(session: Session) -> list[dict[str, Any]]:
    """The story browser's rows, most recently played first. `label` is
    the listing's own fallback rule — title, then the newest rollup,
    then the first prompt — resolved in its one home, never here."""
    open_id = session.story_id
    return [
        {
            "id": row.id,
            "label": row.label,
            "title": row.title,
            "story_so_far": row.story_so_far,
            "first_user": row.first_user,
            "model": row.model,
            "updated_at": row.updated_at.isoformat(),
            "messages": row.num_messages,
            "open": row.id == open_id,
        }
        for row in api_stories.listing(session)
    ]


def search(session: Session, query: str) -> list[int]:
    """Ids of the stories whose CURRENT CHAIN contains `query` — the
    browser's content filter, one call per keystroke. Served from the
    session's own index, so a keystroke never re-reads the library."""
    return api_stories.search(session, query)


def story_messages(session: Session, story_id: int) -> list[dict[str, Any]]:
    """One story's current chain — the browser's drill-in."""
    return [_turn(message) for message in api_stories.messages_of(session, story_id)]


def lore(session: Session) -> dict[str, Any]:
    """The memory as the browser shows it: both lenses, and the field
    list each row opens into. The fields carry their own address
    (`kind`, `target`), which is what an edit names — a row of display
    state never travels back."""
    view = api_lore.view(session)
    return {
        "scenes": [
            {
                "id": scene.id,
                "label": view.scene_label(scene.id),
                # Its own field, from the view's own data: the label is
                # display text, and a scene whose span cannot be
                # computed drops it, which would make a title read as a
                # message range.
                "span": view.scene_span(scene.id),
                "title": scene.title,
                "summary": scene.summary,
                "present": [
                    character.name
                    for character in view.cast
                    if any(
                        journal.scene_id == scene.id and journal.character_id == character.id
                        for journal in view.journals
                    )
                ],
                "fields": [_field(f) for f in view.scene_fields(scene.id)],
            }
            for scene in view.scenes
        ],
        "cast": [
            {
                "id": character.id,
                "name": character.name,
                "aliases": list(character.aliases),
                "description": character.description,
                "now": _latest_state(view, character.id),
                "fields": [_field(f) for f in view.char_fields(character.id)],
            }
            for character in view.cast
        ],
    }


def providers(session: Session) -> dict[str, Any]:
    """The model picker: every reachable provider's models under their
    engine captions, and the panel's field rows. An api key's VALUE is
    never sent — only whether one is set.

    Every CONFIGURED provider, not only the engines otaku ships a client
    for: a section somebody added by hand is a provider they play on,
    and the terminal lists those after the engines, by name. A picker
    that hides the model the session is using is a picker with no way
    back to it."""
    engines = api_providers.engines(session)
    rows, reachable = api_providers.get_providers(session)
    # Seeded from what is CONFIGURED, not from what answered: a provider
    # whose server is down is exactly the one a reader opens the picker
    # to fix, and `get_providers` returns only the reachable.
    models: dict[str, list[dict[str, Any]]] = {
        name: [] for name in {engine.name for engine in engines} | api_providers.configured(session)
    }
    for row in rows:
        models.setdefault(row.config.name, []).extend(
            {
                "name": model.name,
                "loaded": model.loaded if row.can_load_unload else True,
                "can_load_unload": row.can_load_unload,
                "size": format_size(model.size) if model.size else "",
                "context": format_context(model.context) if model.context else "",
            }
            for model in row.models
        )
    known = {engine.name: engine for engine in engines}
    # The engines in their own order, then whatever else is configured,
    # by name — the terminal's `order.get(name, len(order))`.
    named = [engine.name for engine in engines]
    named += sorted(name for name in models if name not in known)
    return {
        "current": session.full_model_name,
        # The one machine fact a picker needs: loading a model is what
        # fills a machine up. Said below both frontends, so the terminal's
        # gauge and the page's are one sentence (`backend.meminfo`).
        "memory": meminfo.gauge(),
        "engines": [_engine(session, name, known.get(name), models, reachable) for name in named],
    }


def _engine(
    session: Session,
    name: str,
    engine: Engine | None,
    models: dict[str, list[dict[str, Any]]],
    reachable: set[str] | frozenset[str],
) -> dict[str, Any]:
    """One provider as the picker draws it. A configured section that is
    not one of the engines has no catalog entry to describe it, so it
    speaks for itself: its own name, and what its config says."""
    section = api_providers.section(session, name)
    return {
        "name": name,
        "label": engine.label if engine is not None else name,
        "local": engine.local if engine is not None else True,
        "connected": name in reachable,
        "url": section.url,
        "has_key": bool(section.api_key),
        "models": models.get(name, []),
    }


def settings(session: Session) -> dict[str, Any]:
    """The /set family as values — what each knob stands at, and where
    it persists, which is a real distinction: the toggles are
    session-wide, the parameters per model."""
    return {
        "think": session.think or "default",
        # The ladder in its one shared order (`backend.session`) — the
        # segmented control draws it, never re-sorts it.
        "think_levels": THINK_MENU,
        "verbose": session.verbose,
        "autocorrect": session.autocorrect,
        "notification": session.notification,
        "model": session.model,
        "parameters": [
            {"name": name, "value": str(session.params.get(name, "")), "type": kind.__name__}
            for name, kind in KNOWN_PARAMS.items()
        ],
    }


def context(session: Session) -> dict[str, Any]:
    """The next request: the shape the window diagram is drawn from, the
    summary, and one part per message. Nothing is rewritten — the page
    draws the role markers as the design draws them, around the report's
    own text."""
    report = reports.context(session)
    return {
        "shape": asdict(report.shape),
        "lede": report.summary,
        "parts": [asdict(part) for part in report.parts],
    }


def usage(session: Session, raw: str = "") -> dict[str, Any]:
    """What the tokens were spent on, as the table's rows — and every
    scope the report can be asked for, because the page draws a tab per
    scope and needs them all to draw any.

    Refused — no story, nothing recorded, an argument that is not "all"
    — reaches the page as the sentence it is, BESIDE the scopes rather
    than instead of them: the scope that refused is the one the reader
    is on, and the other tab is how they get out of it."""
    scopes = [{"key": key, "label": label} for key, label in reports.USAGE_SCOPES]
    try:
        report = reports.usage(session, raw)
    except Refused as refusal:
        return {"notice": str(refusal), "scopes": scopes}
    return {
        "scope": report.scope,
        "scopes": scopes,
        "rows": [asdict(row) for row in report.rows],
        "requests": report.requests,
        "prompt_tokens": report.prompt_tokens,
        "completion_tokens": report.completion_tokens,
        "total_tokens": report.total_tokens,
    }


def balance(session: Session) -> dict[str, Any]:
    """What each cloud account has left. The VALUE is the provider's own
    string — a currency, a credit, a word — never a number to format."""
    return {"rows": [asdict(row) for row in reports.balances(session).rows]}


def info(session: Session) -> dict[str, Any]:
    """Everything otaku knows about this session, in the blocks the
    report is built from — labelled facts, or the sentence that stands
    where a block's facts would be."""
    return {
        "sections": [
            {"rows": [list(row) for row in section.rows], "note": section.note}
            for section in reports.info(session).sections
        ]
    }


def export_document(session: Session) -> dict[str, str]:
    """The story as one Markdown document, and the name to save it
    under. Writing the file is the page's — a browser saves where the
    reader says, and the server never learns where."""
    return {"name": api_transfer.export_name(session), "text": api_transfer.export(session)}


# One READ: the session and the request's query (one value per name),
# the payload out. Rows adapt onto the view functions' own signatures,
# so the one place a query-string name exists is beside the read it
# parameterizes.
_Read = Callable[[Session, Mapping[str, str]], Any]

# What the page may READ, by name — served under `/api/read/`, the
# prefix that says which lane a request takes (see `web.server`). The
# one read that is not a row is `extract`: it never touches the session
# (a run's `poll` is channel-safe by contract, and asking must never
# queue), so the server answers it from `Pending` itself.
READS: dict[str, _Read] = {
    "session": lambda session, query: facts(session),
    "turns": lambda session, query: turns(session),
    "commands": lambda session, query: commands_table(),
    "stories": lambda session, query: stories(session),
    "search": lambda session, query: search(session, query.get("q", "")),
    "story": lambda session, query: story_messages(session, int(query.get("id", ""))),
    "lore": lambda session, query: lore(session),
    "providers": lambda session, query: providers(session),
    "settings": lambda session, query: settings(session),
    "context": lambda session, query: context(session),
    "usage": lambda session, query: usage(session, query.get("scope", "")),
    "balance": lambda session, query: balance(session),
    "info": lambda session, query: info(session),
    "export": lambda session, query: export_document(session),
}


# ---------- what a popup writes ----------
#
# One row of ACTIONS each, and nothing else: the table below is the whole
# list, and a function here that is not in it would be a row nobody can
# reach.

# One popup action: the request's JSON body in, the sentence out. Every
# write a screen performs goes through one of these — the frontend owns
# the sequence, never the state.
_Action = Callable[[Session, dict[str, Any]], str]


def _land(session: Session, body: dict[str, Any]) -> str:
    action: Any = str(body.get("action", "resume"))
    if action not in ("resume", "fork", "truncate"):
        raise Refused(f"Unknown action {action!r}.")
    return api_stories.land(session, int(body["story"]), int(body["message"]), action)


def _set_system(session: Session, body: dict[str, Any]) -> str:
    """The story's premise, from the screen that edits it. A body rather
    than a command line: a premise is paragraphs, and a command line is
    one."""
    return api_stories.set_system(session, str(body["text"]))


def _rename_story(session: Session, body: dict[str, Any]) -> str:
    """Title the story the browser is on — any of them, not only the
    open one."""
    return api_stories.set_title(session, str(body["title"]), int(body["story"]))


def _delete_story(session: Session, body: dict[str, Any]) -> str:
    api_stories.delete(session, int(body["story"]))
    return "Story deleted."


def _edit_message(session: Session, body: dict[str, Any]) -> str:
    api_stories.edit_message(session, int(body["message"]), str(body.get("text", "")))
    return "Message edited."


def _edit_lore(session: Session, body: dict[str, Any]) -> str:
    return api_lore.edit(session, body["kind"], int(body["target"]), str(body.get("text", "")))


def _switch_model(session: Session, body: dict[str, Any]) -> str:
    return api_providers.switch_model(session, str(body["provider"]), str(body["model"]))


def _load_model(session: Session, body: dict[str, Any]) -> str:
    provider, model = str(body["provider"]), str(body["model"])
    if body.get("loaded"):
        api_providers.load(session, provider, model)
        return f"Loaded {model}."
    api_providers.unload(session, provider, model)
    return f"Unloaded {model}."


def _save_field(session: Session, body: dict[str, Any]) -> str:
    attr: Any = str(body["field"])
    if attr not in ("url", "api_key"):
        raise Refused(f"Unknown field {attr!r}.")
    warning = api_providers.save_field(session, str(body["provider"]), attr, str(body["value"]))
    return warning or f"Saved {attr.replace('_', ' ')} for {body['provider']}."


ACTIONS: dict[str, _Action] = {
    "land": _land,
    "set-system": _set_system,
    "rename-story": _rename_story,
    "delete-story": _delete_story,
    "edit-message": _edit_message,
    "edit-lore": _edit_lore,
    "switch-model": _switch_model,
    "load-model": _load_model,
    "save-field": _save_field,
}


# ---------- the flows that span two requests ----------
#
# A file arrives, is read and vetted, and only then lands — with a
# question in between. `Pending` keeps what waits between the halves,
# because a request is over before the next one starts.

# How long a card waits on its persona answer before the next prepare
# sweeps it — long enough to read the question, short enough that a
# cancelled import is not still in memory an hour later.
_CARD_PATIENCE = 600.0


class Pending:
    """What the web holds between requests on behalf of the session —
    the state a terminal keeps on its call stack, forced off it here
    because a request ends before the question it opened is answered.

    Two things span requests by design: the extraction pass the page
    polls, and cards read and vetted, waiting on their persona answer —
    keyed, because two tabs preparing at once must not swap each other's:
    the answer would bind the wrong character to the wrong persona.

    Touched on the session's one thread (every flow runs there), with
    one exception: `extraction` is also READ from a handler thread by
    the poll, which is safe because rebinding an attribute is atomic and
    a run's `poll` is channel-safe by contract."""

    def __init__(self) -> None:
        self.extraction: WorkerRun | None = None
        self._cards: dict[str, tuple[PreparedCard, float]] = {}

    def hold_card(self, prepared: PreparedCard) -> str:
        """Keep a prepared card for its persona answer; returns the
        token the page hands back. A persona ask that was cancelled,
        reloaded past, or closed never comes back for its card — nothing
        else would ever drop it, so each new one sweeps what has gone
        stale."""
        now = time.monotonic()
        for token, (_, asked) in list(self._cards.items()):
            if now - asked > _CARD_PATIENCE:
                del self._cards[token]
        token = secrets.token_hex(8)
        self._cards[token] = (prepared, now)
        return token

    def take_card(self, token: str) -> PreparedCard | None:
        """The card a token names, forgotten in the taking — None for a
        page that asked twice, or a reload between the two halves."""
        held = self._cards.pop(token, None)
        return held[0] if held else None


# One flow: an action that also reaches `Pending`, answered with a
# payload of its own rather than a bare sentence.
_Flow = Callable[[Session, Pending, dict[str, Any]], dict[str, Any]]


def import_document(session: Session, pending: Pending, body: dict[str, Any]) -> dict[str, Any]:
    """Import an uploaded document — an otaku export, a SillyTavern
    chat, or plain text. Content-shaped by contract: a path over HTTP
    would name a file on the SERVER, so the page sends what it read. The
    extraction pass the memoryless shapes start is kept where a forced
    pass is kept, so the page polls one place for both; a native export
    arrives with its memory and runs none — `watching` says so, which is
    what stops the page polling for a report that is never coming."""
    landed = api_transfer.import_file(session, str(body["text"]), str(body["name"]))
    pending.extraction = landed.extraction
    return {"notice": " ".join(landed.notices), "watching": landed.extraction is not None}


def prepare_card(session: Session, pending: Pending, body: dict[str, Any]) -> dict[str, Any]:
    """Everything before the persona ask. The prepared card is OPAQUE —
    it waits in `Pending` and the page hands back only the token and the
    answer. Bytes-shaped for the same reason as the import: the web
    uploads."""
    prepared = api_cards.prepare(
        session,
        base64.b64decode(str(body["data"])),
        str(body["name"]),
        str(body.get("rename", "")),
    )
    return {
        "token": pending.hold_card(prepared),
        "card": {
            "name": prepared.card.name,
            "notes": list(prepared.notes),
            "tokens": prepared.block_tokens,
            "large": prepared.large,
            "persona": api_cards.remembered_persona(session),
        },
    }


def add_card(session: Session, pending: Pending, body: dict[str, Any]) -> dict[str, Any]:
    """Everything after it. Nothing waiting is not an error: a page that
    asked twice, or a reload between the two halves."""
    prepared = pending.take_card(str(body.get("token", "")))
    if prepared is None:
        return {"notice": "No card is waiting."}
    return {"notice": api_cards.add(session, prepared, str(body.get("persona", ""))).report}


def start_extract(session: Session, pending: Pending, body: dict[str, Any]) -> dict[str, Any]:
    """Force an extraction pass now and keep the run, so the page can
    ask for its report without ever holding the session's one thread. A
    second pass would overwrite the run the page is polling, and the
    first one's report would never be read."""
    running = pending.extraction
    if running is not None and running.poll() is None:
        return {"notice": "A pass is already running.", "watching": True}
    pending.extraction = api_lore.extract(session)
    return {"notice": "Extracting lore from the recent messages…", "watching": True}


# The writes whose result outlives their request, one row each under
# `/api/do/` exactly as ACTIONS — the extra hand is `Pending`, where
# what waits between the halves lives.
FLOWS: dict[str, _Flow] = {
    "import": import_document,
    "prepare-card": prepare_card,
    "add-card": add_card,
    "extract": start_extract,
}


# ---------- the reply stream ----------


def play(session: Session, line: str) -> Iterator[PlayEvent]:
    """One submitted story line. Validation is eager, so a Refused
    reaches the caller before any of this is streamed — and before
    anything is recorded."""
    return api_play.submit(session, line)


def regenerate(session: Session) -> Iterator[PlayEvent]:
    """Sibling the standing reply and stream the fresh take. Eager like
    `play`: without a model, or with nothing to regenerate, it refuses
    before anything is dropped."""
    return api_play.regenerate(session)


def event(happened: PlayEvent) -> dict[str, Any]:
    """One play event as the page reads it. The union is closed and the
    match is exhaustive: a new event kind is a type error here, not a
    silence on the wire."""
    match happened:
        case Recorded():
            return {"type": "recorded", "turn": _turn(happened.message)}
        case Thinking():
            return {"type": "thinking", "text": happened.text}
        case Text():
            return {"type": "text", "text": happened.text}
        case Declined():
            return {"type": "declined", "reason": happened.reason}
        case Failed():
            return {"type": "failed", "reason": happened.reason}
        case Done():
            return {"type": "done", "stats": happened.stats}


# ---------- shared shapes ----------


def _field(field: Field) -> dict[str, Any]:
    """One editable row of a detail view, with the address an edit names."""
    return {
        "label": field.label,
        "kind": field.kind,
        "text": field.text,
        "target": field.target,
        "editable": field.editable,
        "pivot": field.pivot,
        "scene_no": field.scene_no,
    }


def _latest_state(view: LoreView, character_id: int) -> str:
    """The character's newest state row — the one line the cast list
    shows beside a name, and the only state ever read again."""
    states = [f for f in view.char_fields(character_id) if f.kind == "state"]
    return states[-1].text if states else ""


def _turn(message: Message) -> dict[str, Any]:
    return {"id": message.id, "role": message.role, "body": message.body}
