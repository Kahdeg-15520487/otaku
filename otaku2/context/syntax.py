"""The story's typed language, and what each stored turn sends.

Two questions, one vocabulary. Reading: `read(line)` binds a typed line
to whatever opened it — a direction (/me, /you, /ooc) or prose when
nothing did — and `is_command` answers the other side of the same coin
(a slash word that is not story syntax belongs to the command table).
Writing: `to_wire` is the ONE dispatch turning a stored turn into wire
text, whatever its kind — prose parses for its syntax, a direction's
stored template fills, a card row takes the block composed from its
archive, a recap row IS its text.

A line is stored exactly as typed and read again whenever the turn is
used. Templates are data on the turn (`Message.template`); at RECORD
time the caller resolves `Line.template_field` against its prompts —
this module reads no settings.

Why this lives in `context`, not `backend`: what a stored turn sends is
context composition — the assembler runs `to_wire` for every row it puts
on the wire, and the worker's extraction composes rows the same way
(`numbered_chat`); both sit BELOW backend and may not reach up. And
reading and writing are one vocabulary — the same Line classes that
parse a typed line define how its stored turn composes — so splitting
them across packages would put one language in two homes. `backend.commands`
re-exports `is_command` — the one piece of this module frontends may
call; the language itself lives at the lowest package everything that
speaks it can reach.

Vocabulary: syntax = this language; directions (/me /you /ooc) OPEN a
line, inliners (/ooc /cue) CLOSE one, told apart by position (an
inliner's slash must follow whitespace, which keeps `and/or` and URLs
prose); framing = a direction's template; command = a slash word that
acts, and none of this module's business. A typed line is deliberately
NOT called a prompt — that word is already spent three ways
(`settings.prompts.Prompts` the templates, `AssembledPrompt` the full
request, the input prompt the terminal draws), and the most overloaded
word must not name the most precise concept.
"""

import re
from typing import ClassVar

from otaku2.store.schema import Message

# The out-of-character enclosure an inliner's text is wrapped in — the
# extraction prompt reads "out of character" off this exact shape.
OOC_FRAME = "((OOC: {body}))"

# The inliners a line may close with.
INLINERS: tuple[str, ...] = ("/ooc", "/cue")

# An inliner is a whole token whose slash follows whitespace — never at
# the start of the line, which is where a direction lives. That single
# rule keeps prose out of the syntax: `and/or`, `he/she`, `24/08/2026`
# and `https://x.co/cue` all carry a slash that follows a non-space.
_INLINERS_REGEX = re.compile(r"(?<=\s)(" + "|".join(INLINERS) + r")(?=\s|$)")


class Line:
    """One typed line, read. The base class is prose — playing the story,
    no name, no template — and answering with it when no direction opened
    the line keeps every caller branchless. Bound at construction:
    `name`/`text` are the argument split this direction's way,
    `inliner`/`tail` the closing inliner and what followed it."""

    token: ClassVar[str] = ""
    args: ClassVar[str] = ""  # the argument shape, as /help spells it ("NAME: PROMPT")
    request_kind: ClassVar[str] = "dialogue"  # the row the writer's line becomes
    reply_kind: ClassVar[str] = "dialogue"  # the answer it asks for
    # The side the named character speaks: "request" (/me — the line IS
    # their words), "reply" (/you — it asks them to answer), "" for none.
    speaks: ClassVar[str] = ""
    needs_name: ClassVar[bool] = False
    needs_text: ClassVar[bool] = False
    template_field: ClassVar[str] = ""  # the prompts.toml key; "" = none

    line: str
    name: str
    text: str
    inliner: str | None
    tail: str

    def __init__(self, line: str) -> None:
        self.line = line
        head, self.inliner, self.tail = _split_inliner(line)
        self.name, self.text = self.split_name(head[len(self.token) :].strip())

    @property
    def usage(self) -> str:
        """The usage sentence, derived from `args` — the shape is the
        declaration, the sentence its rendering."""
        return f"Usage: {self.token} {self.args}".rstrip()

    def check(self) -> str | None:
        """The usage line to print when the line is not valid syntax,
        None when it is. The inliner is checked first because it belongs
        to no direction; what the direction itself needs is declared, not
        tested here. Nothing else validates: a line opening with an
        unknown `/word` is the command table's to report."""
        if self.inliner is not None and not self.tail:
            return f"Usage: … {self.inliner} TEXT"
        if (self.needs_name and not self.name) or (self.needs_text and not self.text):
            return self.usage
        return None

    def update_name(self, name: str) -> str:
        """This line with its name replaced (the cast's own spelling),
        everything else exactly as typed — the closing inliner and its
        text included. Only the cast's own spelling is ever passed in, so
        what comes back names the same character the writer did."""
        if not self.name:
            return self.line
        head = f"{self.token} {self.join_name(name, self.text)}".strip()
        return f"{head} {self.inliner} {self.tail}" if self.inliner else head

    def split_name(self, rest: str) -> tuple[str, str]:
        """This direction's argument as (name, text); prose is all text."""
        return "", rest

    def join_name(self, name: str, text: str) -> str:
        """`split_name` backwards — the argument written the way this
        direction writes it. Prose carries no name, so it is all text."""
        return text

    def compose(self, filled: str | None) -> str:
        """This line's own text and its framing — `filled` is the
        template, `{name}` already in — as ONE wire part; what follows an
        inliner is `to_wire`'s to append after it."""
        return _join(self.text, filled)


class _Me(Line):
    """`/me NAME: PROMPT` — the writer speaks as NAME. The only direction
    carrying both a name and prose, so the only one that splits."""

    token = "/me"
    args = "NAME: PROMPT"
    speaks = "request"
    needs_name = True
    needs_text = True
    template_field = "me_framing"

    def split_name(self, rest: str) -> tuple[str, str]:
        name, _, text = rest.partition(":")
        return name.strip(), text.strip()

    def join_name(self, name: str, text: str) -> str:
        return f"{name}: {text}"


class _You(Line):
    """`/you NAME[: HINT]` — the model plays NAME. It instructs (an
    out-of-character row) but asks for the scene (an in-character reply):
    the one direction whose two kinds differ. The HINT is a standing
    direction for how to play them, sent whenever the turn is — the /cue
    inliner stays the one-shot form. It goes out as its own /ooc-style
    aside unless the template takes {body} into its own wording."""

    token = "/you"
    args = "NAME[: HINT]"
    request_kind = "ooc"
    speaks = "reply"
    needs_name = True
    template_field = "you_framing"

    def split_name(self, rest: str) -> tuple[str, str]:
        name, _, text = rest.partition(":")
        return name.strip(), text.strip()

    def join_name(self, name: str, text: str) -> str:
        return f"{name}: {text}" if text else name

    def compose(self, filled: str | None) -> str:
        # The hint is direction, not story. A {body} slot takes it into
        # the template's own wording; a template without one — the
        # shipped default — sends it as its own /ooc-style aside. Never
        # joined bare, because direction is never story.
        if not self.text or (filled and "{body}" in filled):
            return _join(self.text, filled)
        aside = OOC_FRAME.replace("{body}", self.text)
        return f"{filled} {aside}" if filled else aside


class _Ooc(Line):
    """`/ooc PROMPT` — a word with the model, not the story; both sides
    out of character, and no name to carry, so the base's split stands."""

    token = "/ooc"
    args = "PROMPT"
    request_kind = "ooc"
    reply_kind = "ooc"
    needs_text = True
    template_field = "ooc_framing"


# Every direction, keyed by the token that opens it — the one registry;
# iterating it yields exactly the tokens the menus may offer.
DIRECTIONS: dict[str, type[Line]] = {cls.token: cls for cls in (_Me, _You, _Ooc)}


def read(line: str) -> Line:
    """The line, read as whatever direction opened it — prose when none
    did, so every caller gets an answer instead of a None to test."""
    return DIRECTIONS.get(line.split(" ", 1)[0], Line)(line)


def is_command(line: str) -> bool:
    """Whether the line belongs to the command table instead of the
    story: it opens with a slash word that is not a direction."""
    return line.startswith("/") and not read(line).token


def to_wire(message: Message, *, is_last: bool, card_block: str | None = None) -> str:
    """What one stored turn sends. A card row sends `card_block` (the
    caller owns the archive lookup and composition; a row with no
    reachable archive sends its body). Every other row parses its stored
    line and fills its stored template. Two body shapes reach this, and
    the body tells them apart: turns written before the syntax existed
    hold prose with their prefix already stripped and their name already
    baked into the framing (v1); turns written since hold the line
    exactly as typed, so the syntax comes off here (v2) — the
    direction's prefix drops away, the name it carried fills `{name}`,
    what remains fills `{body}`, and an inliner's text follows as its
    own enclosure, a /cue only while its turn is the newest (`is_last`).
    Only STORED rows come through here; the recap is the assembler's own
    synthesized wire text."""
    if message.kind == "card":
        return card_block if card_block is not None else message.body
    body, template = message.body, message.template
    if template and not body.startswith("/"):
        # A v2 template on a direction-less body means the direction was
        # edited away — its framing goes with it: better the plain prose
        # than a literal `{name}` on the wire. A v1 framing (its name
        # baked in, no placeholder) still joins.
        return body if "{name}" in template else _join(body, template)
    frame = read(body)
    parts = [frame.compose(_fill_name(template, frame.name))]
    # Each inliner named, so a new one sends nothing until it is named
    # here too — silence being the safe default for text nobody has
    # decided the lifetime of.
    if frame.tail and (frame.inliner == "/ooc" or (frame.inliner == "/cue" and is_last)):
        parts.append(OOC_FRAME.replace("{body}", frame.tail))
    return " ".join(part for part in parts if part)


def _split_inliner(line: str) -> tuple[str, str | None, str]:
    """`(head, inliner, text)` — the line up to its FIRST inliner, which
    one it was, and everything after it. No inliner leaves the line whole."""
    found = _INLINERS_REGEX.search(line)
    if found is None:
        return line, None, ""
    return line[: found.start()].rstrip(), found.group(1), line[found.end() :].strip()


def _fill_name(template: str | None, name: str) -> str | None:
    """`{name}` filled from the line itself — no cast lookup, so a turn's
    wire text depends on that turn alone and never shifts when the cast
    does. A v1 framing has the name baked in already and no placeholder
    to fill, which makes this a no-op on it."""
    if template is None:
        return None
    return template.replace("{name}", name)


def _join(text: str, template: str | None) -> str:
    """Text and framing into one turn. A `{body}` placeholder takes the
    text (via `str.replace`, never `str.format`, so other braces stay
    literal); otherwise the framing leads and a blank line separates
    them — or stands alone when the direction carried no text of its own."""
    if not template:
        return text
    if "{body}" in template:
        # An absent body takes its separator space with it, so a template
        # ending "… {body}))" reads clean when there is nothing to say —
        # and a bare /you sends the exact wire it sent before the slot.
        if not text:
            return template.replace(" {body}", "").replace("{body}", "")
        return template.replace("{body}", text)
    if not text:
        return template
    return f"{template}\n\n{text}"
