"""The /set vocabulary constants the frontends read off
`backend.session` — pinned to the file vocabulary they order, because
the two live in different layers and only this keeps them one thing."""

from otaku.backend.session import THINK_MENU
from otaku.settings.state import THINK_DEFAULT, THINK_LEVELS


class TestThinkVocabulary:
    def test_the_menu_offers_exactly_the_file_s_vocabulary(self) -> None:
        # A menu offering a level the file refuses would Refuse on
        # click; one missing a level would make that level typed-only.
        assert set(THINK_MENU) == THINK_LEVELS | {THINK_DEFAULT}

    def test_default_leads_the_menu(self) -> None:
        # The way out comes first, as the docstring promises.
        assert THINK_MENU[0] == THINK_DEFAULT
