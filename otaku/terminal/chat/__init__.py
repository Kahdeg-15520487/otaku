"""The conversation surface — the terminal's main floor: the namesake
`Chat`, the loop (`run` — what cli hands an open session to), the
bindings, the stream renderer, the screen ledger, and the `/help` page
(text in, text out, beside the bindings whose table it lays out)."""

from otaku.terminal.chat.loop import run

__all__ = ["run"]
