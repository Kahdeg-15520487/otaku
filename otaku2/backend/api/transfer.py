"""Import/export operations — the `api.transfer` tag; the document and
its parsers live in `backend.formats`.

An import writes the file's records into a fresh story, switches the
session onto it, and then triggers the extraction exactly like a forced
close — one path builds the memory whether the messages came from play
or from a file. A full export that carries its memory needs no
extraction; the pass simply finds nothing to do.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath

from otaku2 import __version__
from otaku2.backend.api import lore
from otaku2.backend.api.lore import WorkerRun
from otaku2.backend.formats import EXPORT_FORMAT_VERSION, EXPORT_MARKER, exports, imports
from otaku2.backend.formats.plaintext import parse_plaintext
from otaku2.backend.formats.sillytavern import parse_sillytavern
from otaku2.backend.session import Refused, Session


@dataclass(frozen=True)
class ImportedStory:
    """What an import landed: the notices to show (counts, detected
    format), and — for the memoryless shapes — the forced extraction pass
    to wait on; a native export arrives with its memory and runs none."""

    notices: tuple[str, ...]
    extraction: WorkerRun | None


def import_file(session: Session, text: str, file_name: str) -> ImportedStory:
    """Import a story from a file's TEXT and NAME: an otaku export
    document (.md, its memory applied verbatim, no model calls), a
    SillyTavern chat (.jsonl), or plain text (.txt) dismantled into
    verbatim messages. The format is detected — never declared — and the
    file's name and contents must agree; a file that matches a format
    but fails its parser is refused, not degraded into prose.
    Content-shaped on purpose: reading a path is the frontend's, the web
    uploads. Writes a fresh story and switches the session onto it.
    Raises Refused with the exact reason (unknown format, a newer
    export — run `otaku update`)."""
    suffix = PurePath(file_name).suffix.lower()
    notices: list[str] = []
    native = False
    if suffix == ".md" and EXPORT_MARKER in text:
        try:
            export = imports.parse_story(text)
        except imports.NewerFormatError as e:
            raise Refused(
                f"This export was written by a newer otaku (format {e.declared}; this version "
                f"reads up to {EXPORT_FORMAT_VERSION}) — run 'otaku update' first."
            ) from e
        if export is None:
            raise Refused("This looks like an otaku export, but it does not parse.")
        native = True
    elif suffix == ".jsonl" and text.lstrip().startswith("{"):
        export = parse_sillytavern(text)
        if export is None:
            raise Refused("This looks like JSON, but not a SillyTavern chat (.jsonl).")
        notices.append(f"SillyTavern chat: {len(export.messages)} message(s).")
    elif suffix == ".txt":
        export = parse_plaintext(text)
        if export is None:
            raise Refused("The file contains no text to import.")
    else:
        raise Refused("Cannot detect file format.")
    if not export.messages:
        raise Refused("The file contains no messages to import.")

    story_id = imports.write_story(session._store, export)
    applied = f", {len(export.scenes)} scene(s) applied verbatim" if export.scenes else ""
    notices.append(f"Imported {len(export.messages)} message(s) → story {story_id}{applied}.")
    session._search_index = None
    session._switch_to(story_id)
    # A native export carries its whole extraction state — including a
    # legitimately unextracted tail — so the story arrives exactly as it
    # was and extraction resumes its normal idle-gated life. The
    # memoryless shapes get their memory built now: the same forced pass,
    # waited on the same way, as a manual close. Without a model the
    # import still stands; the refusal joins the notices.
    run: WorkerRun | None = None
    if not native:
        try:
            run = lore.extract(session)
        except Refused as e:
            notices.append(str(e))
    return ImportedStory(notices=tuple(notices), extraction=run)


def export(session: Session) -> str:
    """The current story as the one Markdown document: the story-so-far,
    system, and cast, the scenes with their journals, then every message
    verbatim (template included) — importable back losslessly. Raises
    Refused when there is nothing to export. Writing the file — and
    asking about overwrites — is the frontend's."""
    if not session.messages:
        raise Refused("Nothing to export yet.")
    story_id = session._ensure_story()
    return exports.render_story(
        exports.read_story(session._store, story_id),
        otaku_version=__version__,
        model=session.full_model_name,
        exported=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
    )


def export_name(session: Session) -> str:
    """`the-long-road.md` from the story title; `story.md` untitled."""
    story = session._store.stories.get(session.story_id) if session.story_id is not None else None
    stem = re.sub(r"[^\w\s-]", "", (story.title if story else "").lower())
    slug = re.sub(r"[\s_-]+", "-", stem).strip("-")
    return f"{slug or 'story'}.md"
