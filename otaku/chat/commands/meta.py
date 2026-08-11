"""Meta commands: /help and /bye — about the app, not the story."""

from otaku.chat.help import HELP_TEXT, command_tokens
from otaku.chat.session import Session
from otaku.store import Store
from otaku.terminal.typography import highlight_commands


def cmd_bye(session: Session, store: Store, args: list[str]) -> None:
    session.should_quit = True


def cmd_help(session: Session, store: Store, args: list[str]) -> None:
    # Colored at print time, never at build: the table's column math runs
    # on plain text (escapes would count into the padding), and the theme
    # is only settled once the launch has asked the terminal.
    print(highlight_commands(HELP_TEXT, command_tokens()))
