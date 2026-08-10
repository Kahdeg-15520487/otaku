"""How a message looks: the one place that decision is made.

A reply is typeset the way it streamed — dialogue color, emphasis,
blocks — and a request has its commands picked out instead. One or the
other, never both: they are counterparts, not layers.

A LEAF of `chat` (it reads only `chat.help`, itself a leaf), because the
callers sit at every level: the prompt highlights the line being typed,
the session renders stored turns for the resume echo, inference streams a
reply through `streamer`, and the story browser is handed `message`
outright — `tui` may not read chat at all. Anywhere but here, some of
them could not reach it.
"""

import io
from typing import TextIO

from otaku.chat.help import command_tokens
from otaku.settings.config import Config
from otaku.terminal.typography import Typesetter, highlight_commands


def message(text: str, role: str, *, config: Config) -> str:
    """A message as it is shown, wherever it is shown — the grey played
    block, the line being typed into it, the turns a resume echoes, a row
    in the story browser and its preview.

    A reply goes through the very typesetter it streamed through, run to
    the end in one pass: that is what makes a turn echoed on resume the
    same text that was on screen when it played, rather than two renderers
    that merely agree today."""
    if role != "assistant":
        return highlight_commands(text, command_tokens())
    out = io.StringIO()
    typesetter = streamer(out, config=config)
    typesetter.feed(text)
    typesetter.flush()
    return out.getvalue()


def streamer(out: TextIO, *, config: Config) -> Typesetter:
    """What a reply is typeset through as it arrives, chunk by chunk.
    `message` runs one of these over a whole stored reply, so the live
    stream and every later echo of it are the same renderer."""
    return Typesetter(out, speech_color=config.dialogue_color, speech_bold=config.dialogue_bold)
