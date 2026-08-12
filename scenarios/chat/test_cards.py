"""/card — a character card imported into the story.

An import is three writes and no model call: the composed card block
(`kind='card'`), the cast row carrying the card TOML, and the greeting —
the character's own words, a user-role turn with the speaker set. The
extraction never reads a card (a story holding only one extracts
nothing, and a forced pass summarizes around it), and the next request
carries the block and the greeting on the wire. The fixtures are
SillyTavern's own bundled Seraphina (a real PNG card) and a minimal
JSON one.
"""

import tomllib
from pathlib import Path

from scenarios.support.harness import App

SERAPHINA = Path(__file__).parent.parent / "fixtures" / "seraphina.png"
MINIMAL = Path(__file__).parent.parent / "fixtures" / "spec_v2_minimal.json"


class TestImport:
    def test_an_import_is_the_block_the_cast_row_and_the_greeting(self, app: App) -> None:
        app.play(f"/card {SERAPHINA}")
        rows = app.store.stories.get_messages(app.session.story_id)
        assert [(m.role, m.kind) for m in rows] == [("user", "card"), ("user", "dialogue")]
        block, greeting = rows
        assert "Seraphina" in block.body and block.template is None
        (character,) = app.store.characters.list(app.session.story_id)
        assert character.name == "Seraphina"
        assert (greeting.speaker, greeting.speaker_id) == ("Seraphina", character.id)
        assert "{{" not in block.body and "{{" not in greeting.body  # macros bound

    def test_the_archive_records_the_bindings(self, app: App) -> None:
        app.play(f"/card {SERAPHINA} Warden")
        (character,) = app.store.characters.list(app.session.story_id)
        data = tomllib.loads(character.card)
        assert (data["name"], data["user"]) == ("Warden", "you")
        assert data["file_name"] == "seraphina.png"

    def test_a_card_without_a_greeting_imports_the_block_alone(self, app: App) -> None:
        app.play(f"/card {MINIMAL}")
        rows = app.store.stories.get_messages(app.session.story_id)
        assert [m.kind for m in rows] == ["card"]

    def test_a_duplicate_name_is_refused_untouched(self, app: App) -> None:
        app.play(f"/card {SERAPHINA}")
        before = len(app.store.stories.get_messages(app.session.story_id))
        app.play(f"/card {SERAPHINA}")
        assert len(app.store.stories.get_messages(app.session.story_id)) == before
        assert len(app.store.characters.list(app.session.story_id)) == 1

    def test_the_import_calls_no_model(self, app: App) -> None:
        app.play(f"/card {SERAPHINA}")
        assert app.server.requests == []

    def test_the_block_and_the_greeting_ride_the_next_request(self, app: App) -> None:
        app.play(f"/card {SERAPHINA}")
        app.play("I sit up slowly.")
        wire = "\n".join(str(m["content"]) for m in app.server.requests[-1]["messages"])
        assert "Seraphina joins the story" in wire
        assert "You wake with a start" in wire


class TestExtraction:
    def test_a_story_of_one_card_extracts_nothing(self, app: App) -> None:
        # A card is not story: alone (this fixture has no greeting) there
        # is nothing to close a scene over, however many characters of
        # text the block holds — even forced.
        app.play(f"/card {MINIMAL}")
        app.play("/extract")
        assert (
            app.store.scenes.get_current(
                app.session.story_id, app.store.stories.get_messages_ids(app.session.story_id)
            )
            == []
        )

    def test_a_forced_pass_summarizes_around_the_card(self, app: App) -> None:
        app.play(f"/card {SERAPHINA}")
        for i in range(3):
            app.play(f"Turn number {i}.")
        app.play("/extract")
        story_id = app.session.story_id
        ids = app.store.stories.get_messages_ids(story_id)
        scenes = app.store.scenes.get_current(story_id, ids)
        assert scenes  # played turns closed as a scene
        extraction = next(
            str(r["messages"][-1]["content"])
            for r in app.server.requests
            if "story analyst" in str(r["messages"][-1]["content"])
        )
        # The card BLOCK never reaches the pass — but the greeting does:
        # the character's first words are the story's first beat, and the
        # scene rightly remembers them.
        assert "Seraphina joins the story" not in extraction
        assert "You wake with a start" in extraction
