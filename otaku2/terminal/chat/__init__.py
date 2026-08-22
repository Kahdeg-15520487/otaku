"""The conversation surface — the terminal's main floor: the namesake
`Chat`, the loop (`run` — what cli hands an open session to), the
bindings, the stream renderer, and the screen ledger."""

from otaku2.terminal.chat.loop import run

__all__ = ["run"]
