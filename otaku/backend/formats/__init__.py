"""The story document and the foreign formats — every wild file otaku
reads is decoded in this package: the export document, SillyTavern
chats, plain text, and character-card files (`cards`).

This package owns the story document, and the round-trip is a law:
`imports.parse_story(exports.render_story(x))` returns `x` exactly. The
reader reads every format version ever written; a newer declared format
is refused with directions, never guessed at.

The document is one Markdown file, readable as prose and parseable as
data — a metadata comment (recognition + versions), the optional
`# title` heading, a `## Story` section (story so far, system, cast — an
imported card's archive TOML as a `#### Name` block under the roster),
`## Scenes` (span, summary, per-character journals), and `## Messages` —
one `### n · role (kind) · speaker · "template"` header per message, the
kind, speaker, and JSON-quoted template present only when they exist,
with the verbatim body starting on the very next line. Empty parts are
simply absent, an untitled story has no heading, and message bodies keep
their interior blank lines. Body text is structure-proof: a content line
that would read as a heading (or as this escape itself) is written with
one extra leading backslash, and the parser strips exactly one — so
bodies, summaries, and the rest survive byte-exact whatever Markdown
they hold.

This module holds the data model every reader and writer shares and the
two facts that recognize a file; the parsers are the sibling modules
(`exports`, `imports`, `sillytavern`, `plaintext`, `cards`)."""

from dataclasses import dataclass

# Bumped when the layout changes in a way an older reader would misread.
EXPORT_FORMAT_VERSION = 2  # 2: `card` message kind; cast carries card archives

# What recognizes the document — the first line of its metadata block.
EXPORT_MARKER = "<!-- otaku export"


@dataclass(frozen=True)
class ExportedCharacter:
    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    card: str = ""  # the /card archive TOML


@dataclass(frozen=True)
class ExportedJournal:
    character: str
    entry: str = ""
    state: str = ""
    history: str = ""


@dataclass(frozen=True)
class ExportedScene:
    title: str = ""
    span: tuple[int, int] | None = None  # (first, last) message ordinal, 1-based
    summary: str = ""
    journals: tuple[ExportedJournal, ...] = ()


@dataclass(frozen=True)
class ExportedMessage:
    role: str  # 'user' | 'assistant'
    body: str
    kind: str = "dialogue"
    speaker: str | None = None
    template: str | None = None


@dataclass(frozen=True)
class StoryExport:
    """One story's transferable whole — what the document holds."""

    title: str = ""
    system: str = ""
    story_so_far: str = ""
    cast: tuple[ExportedCharacter, ...] = ()
    scenes: tuple[ExportedScene, ...] = ()
    messages: tuple[ExportedMessage, ...] = ()
