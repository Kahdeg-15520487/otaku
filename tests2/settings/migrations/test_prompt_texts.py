"""The refreshed-template move: a superseded shipped default follows the
built-in; anything the user touched stays theirs. Pure text in, text out —
the promise is convergence, so the cases parse the result back and compare
values, never the spelling."""

import tomllib

from otaku2.formatting import toml_string
from otaku2.settings.migrations.prompt_texts import EXTRACT_0_2_2, refresh_template
from otaku2.settings.migrations.surgery import apply_migrations
from otaku2.settings.prompts import EXTRACT_DEFAULT


class TestRefreshTemplate:
    def test_a_stale_shipped_default_follows_the_built_in(self) -> None:
        text = stub("extract_prompt", EXTRACT_0_2_2)
        migrated = apply_migrations(text, [refresh()])
        assert tomllib.loads(migrated)["extract_prompt"] == EXTRACT_DEFAULT

    def test_an_edited_template_is_never_touched(self) -> None:
        edited = EXTRACT_0_2_2.replace("story analyst", "harsh critic")
        text = stub("extract_prompt", edited)
        assert apply_migrations(text, [refresh()]) == text

    def test_other_keys_ride_along_untouched(self) -> None:
        text = stub("me_framing", "((OOC: I am {name}.))") + stub("extract_prompt", EXTRACT_0_2_2)
        migrated = apply_migrations(text, [refresh()])
        parsed = tomllib.loads(migrated)
        assert parsed["me_framing"] == "((OOC: I am {name}.))"
        assert parsed["extract_prompt"] == EXTRACT_DEFAULT

    def test_a_file_without_the_key_is_untouched(self) -> None:
        text = stub("me_framing", "((OOC: I am {name}.))")
        assert apply_migrations(text, [refresh()]) == text

    def test_the_move_is_idempotent(self) -> None:
        once = apply_migrations(stub("extract_prompt", EXTRACT_0_2_2), [refresh()])
        assert apply_migrations(once, [refresh()]) == once


def refresh():
    return refresh_template("extract_prompt", EXTRACT_0_2_2, EXTRACT_DEFAULT)


def stub(key: str, value: str) -> str:
    """A prompts.toml block the way `write_stub` writes one."""
    return f"{key} = {toml_string(value)}\n\n"
