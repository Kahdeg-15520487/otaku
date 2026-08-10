"""Meta commands: /help and /bye — about the app, not the story."""

from otaku.chat.help import HELP_TEXT
from otaku.chat.session import Session
from otaku.store import Store


def cmd_bye(session: Session, store: Store, args: list[str]) -> None:
    session.should_quit = True


def cmd_help(session: Session, store: Store, args: list[str]) -> None:
    print(HELP_TEXT)
