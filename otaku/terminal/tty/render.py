"""How a turn looks — decided once, used by the prompt's live coloring,
the played block, the resume echo, and the story browser alike. A
request has its commands picked out; a reply is typeset the way it
streamed — one or the other, never both: they are counterparts, not
layers. The reply goes through the very typesetter it arrived on, run
to the end in one pass, so a turn echoed on resume is the same text
that was on screen when it played. The vocabulary comes from
`backend.commands`, so what counts as a command is never guessed from
a slash.
"""

import io
import re

from otaku.backend import Message
from otaku.backend.commands import COMMANDS
from otaku.terminal.tty import user_block
from otaku.terminal.tty.typography import Streamer, highlight_commands

# A command as a spec's token writes it: a slash and a word, nothing
# else — rules out the `…` the inliner rows ride behind.
_COMMAND_WORD = re.compile(r"^/[a-z]+$")


def message(text: str, role: str) -> str:
    """One body styled for display: highlighted (user) or typeset
    (assistant). Takes no settings — the user's colors reached the theme
    at launch, so a caller only has to say WHAT it is drawing."""
    if role == "user":
        return highlight_commands(text, command_tokens())
    out = io.StringIO()
    streamer = Streamer(out)
    streamer.feed(text)
    streamer.flush()
    return out.getvalue()


def turn(item: Message) -> str:
    """One turn exactly as the echoes print it: a user turn as the grey
    block, a model turn as it streamed — the trailing newline normalized
    away, the caller joining and terminating lines. One renderer for
    showing AND measuring, so the ledger can never disagree with the
    echo."""
    styled = message(item.body, item.role)
    if item.role == "user":
        return user_block(styled)
    return "\n".join(styled.splitlines())


def last_turns(messages: list[Message], count: int) -> str:
    """The last `count` turns, echoed the way they played, one blank line
    between turns, bodies verbatim."""
    out: list[str] = []
    for item in messages[-count:]:
        out.append("")
        out.append(turn(item))
    return "\n".join(out).lstrip("\n")


def command_tokens() -> tuple[str, ...]:
    """Every slash word the app answers to, in table order — the commands
    typed at a line's start and the inliners typed inside one. What
    display reads to tell a command from prose: `/me` is one, `and/or`
    is not, so a highlighter never has to guess from the slash alone."""
    found = (word for spec in COMMANDS for word in spec.token.split())
    return tuple(dict.fromkeys(word for word in found if _COMMAND_WORD.match(word)))
