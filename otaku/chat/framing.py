"""The framing syntax: what a typed line may say, and what it sends.

Framing exists to spare the writer the wire's punctuation. Instead of
typing `xxx ((OOC: yyy))` they type `xxx /ooc yyy`; instead of spelling out
who is speaking they open with `/me NAME:`. A line is stored EXACTLY as
typed, and it is read again whenever the turn is used.

`framing(line)` is that reading: it returns the line bound to the command
that opened it, already split into a name, its prose, and any inliner's
text. `update_name` is the one thing that writes a line back — the cast's own
spelling of a name the writer typed loosely (see `repl`, and `/set
autocorrect`), settled before the line is stored so that everything after
reads one text. Everything that varies between commands lives on the class — the
usage line, the two kinds, the template it names, how the argument splits
and how its text composes — as data, or an override where the shape
differs. Prose — a line that opens with no command —
is the base class itself, so no caller ever tests for one.

The commands OPEN a line and the inliners CLOSE it; `/ooc` is both, told
apart by position. An inliner's slash must follow whitespace, and that
single rule is what keeps prose out of the syntax: `and/or`, `he/she`,
`24/08/2026` and `https://x.co/cue` all carry a slash that follows a
non-space.

This module is a LEAF of `chat`: it imports nothing from its own package,
which is what lets `lore` depend on it (see the architecture note in
CLAUDE.md) without a cycle. It must stay that way.
"""

import re
import tomllib
from dataclasses import fields

from otaku.settings.prompts import Prompts
from otaku.transfer.card import Card, bind

# The inliners a line may close with.
FRAMING_INLINERS = ("/ooc", "/cue")

# An inliner is a whole token whose slash follows whitespace — never at the
# start of the line, which is where the command lives.
_FRAMING_INLINERS_REGEX = re.compile(r"(?<=\s)(" + "|".join(FRAMING_INLINERS) + r")(?=\s|$)")
# The card template's `{field}` holes (`card_to_wire`).
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# The out-of-character enclosure an inliner's text is wrapped in. Not a
# prompts.toml template: it carries no wording to tune, and the extraction
# prompt reads "out of character" off this exact shape.
OOC_FRAME = "((OOC: {body}))"


class Framing:
    """One line, read: a line that opens with no command is plain prose,
    playing the story, and that is this class.

    It is also the base every command specialises, and answering with it
    when no command opened the line is what keeps the callers branchless —
    prose names no template, needs nothing, and is all text.

    Bound at construction, so nothing has to be passed back in: `name` and
    `text` are the argument split the way this command splits it, `inliner`
    and `tail` are the closing inliner and what followed it.

    `request_kind` marks the row the writer's line becomes; `reply_kind`
    marks the answer it asks for. They are separate attributes because for
    one command they disagree."""

    token = ""
    usage = ""
    request_kind = "dialogue"
    reply_kind = "dialogue"
    # The side of the exchange the named character speaks: "request" when
    # the line IS their words (/me), "reply" when it asks them to answer
    # (/you), "" when the name names nobody's line. Attribution follows
    # this, not the command, so a new command only has to declare it.
    speaks = ""
    needs_name = False
    needs_text = False
    template_field = ""

    def __init__(self, line: str) -> None:
        self.line = line
        head, self.inliner, self.tail = _split_inliner(line)
        self.name, self.text = self.split_name(head[len(self.token) :].strip())

    def split_name(self, rest: str) -> tuple[str, str]:
        """This command's argument as `(name, text)`."""
        return "", rest

    def join_name(self, name: str, text: str) -> str:
        """`split_name` backwards — the argument written the way this
        command writes it. Prose carries no name, so it is all text."""
        return text

    def compose(self, filled: str | None) -> str:
        """This line's own text and its framing — `filled` is the template,
        `{name}` already in — as ONE wire part; what follows an inliner is
        `prompt_to_wire`'s to append after it."""
        return _join(self.text, filled)

    def update_name(self, name: str) -> str:
        """This line with its name replaced, everything else exactly as
        typed — the closing inliner and its text included. Only the cast's
        own spelling is ever passed in (see repl), so what comes back names
        the same character the writer did."""
        if not self.name:
            return self.line
        head = f"{self.token} {self.join_name(name, self.text)}".strip()
        return f"{head} {self.inliner} {self.tail}" if self.inliner else head

    def template(self, prompts: Prompts) -> str | None:
        """The prompts.toml template this command names, verbatim — both
        `{name}` and `{body}` still in it. None for prose.

        A subclass declares WHICH template by name and never overrides
        this, so reading `Prompts` happens in exactly one place."""
        if not self.template_field:
            return None
        template: str = getattr(prompts, self.template_field)
        return template

    def check(self) -> str | None:
        """The usage line to print when the line is not valid syntax, or
        None when it is. The inliner is checked first because it belongs to
        no command; what the command itself needs is declared, not tested
        here. Nothing else validates: a line opening with an unknown
        `/word` is prose, because the command table reports those."""
        if self.inliner is not None and not self.tail:
            return f"Usage: … {self.inliner} TEXT"
        if (self.needs_name and not self.name) or (self.needs_text and not self.text):
            return self.usage
        return None


class _Me(Framing):
    """`/me NAME: PROMPT` — the writer speaks as NAME. The only command
    carrying both a name and prose, so the only one that splits."""

    token = "/me"
    usage = "Usage: /me NAME: PROMPT"
    speaks = "request"
    needs_name = True
    needs_text = True
    template_field = "me_framing"

    def split_name(self, rest: str) -> tuple[str, str]:
        name, _, text = rest.partition(":")
        return name.strip(), text.strip()

    def join_name(self, name: str, text: str) -> str:
        return f"{name}: {text}"


class _You(Framing):
    """`/you NAME[: HINT]` — the model plays NAME. It instructs rather than
    plays, hence an out-of-character row; but what it asks for is the
    scene, so its reply is in character. The one command whose two kinds
    differ.

    The optional HINT is a standing direction for how to play them, sent
    whenever the turn is — the /cue inliner stays the one-shot form. It
    goes out as its own /ooc-style aside; a you_framing template carrying
    a {body} slot takes it into its own wording instead."""

    token = "/you"
    usage = "Usage: /you NAME[: HINT]"
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
        # The hint is direction, not story. A {body} slot takes it into the
        # template's own wording; a template without one — the shipped
        # default — sends it as its own /ooc-style aside. Never joined
        # bare, because direction is never story.
        if not self.text or (filled and "{body}" in filled):
            return _join(self.text, filled)
        aside = OOC_FRAME.replace("{body}", self.text)
        return f"{filled} {aside}" if filled else aside


class _Ooc(Framing):
    """`/ooc PROMPT` — a word with the model, not the story. Both sides out
    of character, and no name to carry, so the base's split stands."""

    token = "/ooc"
    usage = "Usage: /ooc PROMPT"
    request_kind = "ooc"
    reply_kind = "ooc"
    needs_text = True
    template_field = "ooc_framing"


# Every command, keyed by the token that opens it — the one registry, so
# iterating it yields exactly the tokens the menu may offer.
FRAMING_COMMANDS: dict[str, type[Framing]] = {
    command.token: command for command in (_Me, _You, _Ooc)
}


def framing(line: str) -> Framing:
    """The line, read as whatever command opened it — prose when none did,
    so every caller gets an answer instead of a None to test."""
    return FRAMING_COMMANDS.get(line.split(" ", 1)[0], Framing)(line)


def prompt_to_wire(body: str, template: str | None, *, is_last: bool) -> str:
    """What one stored turn sends to the model.

    Two shapes reach this, and the body tells them apart. Turns written
    before the syntax existed hold prose with their prefix already stripped
    and their name already baked into the framing (v1). Turns written since
    hold the line exactly as typed, so the syntax comes off here (v2): the
    command's prefix drops away, the name it carried fills `{name}`, what
    remains fills `{body}`, and an inliner's text follows as its own
    enclosure.

    A cue is the exception that makes it one-time: it goes out only while
    its turn is the newest, and from the next turn onward it is not there.
    """
    if template and not body.startswith("/"):
        return _join(body, template)
    frame = framing(body)
    parts = [frame.compose(_fill_name(template, frame.name))]
    # Each inliner named, so a new one sends nothing until it is named
    # here too — silence being the safe default for text nobody has
    # decided the lifetime of.
    if frame.tail and (frame.inliner == "/ooc" or (frame.inliner == "/cue" and is_last)):
        parts.append(OOC_FRAME.replace("{body}", frame.tail))
    return " ".join(part for part in parts if part)


def card_to_wire(toml_text: str, template: str) -> str:
    """What a `kind='card'` turn sends: the card template's `{field}`
    placeholders filled from the character's archived TOML, every text
    bound to its recorded `name`/`user` on the way — at WIRE time, so a
    `/lore` correction to the archive reaches every future request. The
    same dualism as every command here, composed from the archive instead
    of the line. One pass, so braces inside card text are never re-read
    as placeholders; a template line whose placeholders ALL came up empty
    is dropped — a card without a scenario ships no dangling `Scenario:`
    label."""
    data = tomllib.loads(toml_text)
    char, user = str(data.get("name", "")), str(data.get("user", ""))
    # Every card field answers, empty when the archive omitted it — an
    # absent scenario must drop its template line, not survive as a
    # literal `{scenario}`. Only names outside the card's vocabulary are
    # left as written.
    values: dict[str, str] = {field.name: "" for field in fields(Card)}
    values["user"] = user
    for key, value in data.items():
        if isinstance(value, str):
            values[key] = bind(value, char=char, user=user)
        elif isinstance(value, list):
            joined = "\n\n".join(str(item) for item in value)
            values[key] = bind(joined, char=char, user=user)
    out = []
    for line in template.split("\n"):
        holes = _PLACEHOLDER.findall(line)
        known = [name for name in holes if name in values]
        if known and all(not values[name].strip() for name in known):
            continue
        out.append(_PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), line))
    return "\n".join(out)


def _split_inliner(line: str) -> tuple[str, str | None, str]:
    """`(head, inliner, text)` — the line up to its FIRST inliner, which
    one it was, and everything after it. No inliner leaves the line whole."""
    found = _FRAMING_INLINERS_REGEX.search(line)
    if found is None:
        return line, None, ""
    return line[: found.start()].rstrip(), found.group(1), line[found.end() :].strip()


def _fill_name(template: str | None, name: str) -> str | None:
    """`{name}` filled from the line itself — no cast lookup, so a turn's
    wire text depends on that turn alone and never shifts when the cast
    does. A v1 framing has the name baked in already and no placeholder to
    fill, which makes this a no-op on it."""
    if template is None:
        return None
    return template.replace("{name}", name)


def _join(text: str, template: str | None) -> str:
    """Text and framing into one turn. A `{body}` placeholder takes the
    text (via `str.replace`, never `str.format`, so other braces stay
    literal); otherwise the framing leads and a blank line separates them —
    or stands alone when the command carried no text of its own."""
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
