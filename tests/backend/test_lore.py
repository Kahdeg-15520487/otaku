"""The lore view's label arithmetic — the parts both frontends print
beside a scene, promised as DATA (`scene_no`, `scene_span`) so neither
ever has to fish them back out of the display label — and its field
lists: which rows a detail view shows, in what order, and which of them
a hand may correct."""

from otaku.backend.api.lore import LoreView
from otaku.store.schema import Character, Journal, Scene


class TestSceneParts:
    def test_the_span_is_the_chain_positions_of_the_scene_ends(self) -> None:
        view = _view(Scene(id=1, start_message_id=61, end_message_id=84, title="The Crossing"))
        assert view.scene_span(1) == "61-84"

    def test_a_scene_with_an_end_off_the_chain_has_no_span(self) -> None:
        # An edit moved the head past the scene: its positions cannot be
        # said, and the empty span is the promise — not a guessed range.
        view = _view(Scene(id=1, start_message_id=61, end_message_id=999))
        assert view.scene_span(1) == ""

    def test_an_unknown_scene_has_no_span(self) -> None:
        view = _view(Scene(id=1, start_message_id=61, end_message_id=84))
        assert view.scene_span(7) == ""

    def test_scenes_are_numbered_in_story_order_from_one(self) -> None:
        view = _view(
            Scene(id=5, start_message_id=61, end_message_id=62),
            Scene(id=3, start_message_id=63, end_message_id=64),
        )
        assert view.scene_no(5) == 1
        assert view.scene_no(3) == 2
        assert view.scene_no(99) == 0

    def test_the_label_is_composed_from_the_parts(self) -> None:
        view = _view(Scene(id=1, start_message_id=61, end_message_id=84, title="The Crossing"))
        assert view.scene_label(1) == "1  61-84  The Crossing"

    def test_the_label_drops_a_span_it_cannot_say(self) -> None:
        # Number and title alone — which is exactly why a frontend must
        # take the parts as data: a title can look like a range.
        view = _view(Scene(id=1, start_message_id=61, end_message_id=999, title="Chapter 3-4"))
        assert view.scene_label(1) == "1  Chapter 3-4"


class TestFieldLists:
    def test_the_scene_history_sits_after_the_summary_in_every_scene(self) -> None:
        # Read-only in each: the scene's history is the extractor's own,
        # and the row exists even before a pass has written it — an
        # empty text, not an absent field.
        view = _view(
            Scene(id=1, start_message_id=1, end_message_id=2, summary="A.", history="Arc."),
            Scene(id=2, start_message_id=3, end_message_id=4, summary="B."),
        )
        for scene_id in (1, 2):
            kinds = [f.kind for f in view.scene_fields(scene_id)]
            assert kinds[:3] == ["scene-title", "scene-summary", "scene-history"]
            assert not view.scene_fields(scene_id)[2].editable
        assert view.scene_fields(1)[2].text == "Arc."
        assert view.scene_fields(2)[2].text == ""

    def test_states_are_never_editable_and_entries_always_are(self) -> None:
        # Through both parents, the newest row included: a state is
        # superseded by the next scene's, so no hand corrects any of
        # them, while the entry stays the writable primitive.
        view = _peopled_view()
        for fields in (view.scene_fields(1), view.scene_fields(2), view.char_fields(7)):
            states = [f for f in fields if f.kind == "state"]
            assert states
            assert all(not f.editable for f in states)
        entries = [f for f in view.char_fields(7) if f.kind == "entry"]
        assert entries
        assert all(f.editable for f in entries)

    def test_the_character_history_row_is_derived(self) -> None:
        view = _peopled_view()
        history = [f for f in view.char_fields(7) if f.kind == "history"]
        assert history
        assert not history[0].editable


def _view(*scenes: Scene) -> LoreView:
    """A view over a 100-message chain whose message ids ARE their
    positions — spans read directly against it."""
    return LoreView(
        story_id=1,
        total_messages=100,
        scenes=scenes,
        cast=(),
        journals=(),
        _ordinal={mid: mid for mid in range(1, 101)},
    )


def _peopled_view() -> LoreView:
    """Two scenes, one character, a journal row in each — the smallest
    memory where 'the newest state' differs from 'an older one'."""
    return LoreView(
        story_id=1,
        total_messages=4,
        scenes=(
            Scene(id=1, start_message_id=1, end_message_id=2),
            Scene(id=2, start_message_id=3, end_message_id=4),
        ),
        cast=(Character(id=7, name="Keeper"),),
        journals=(
            Journal(id=11, scene_id=1, character_id=7, entry="e1", state="s1", history="h1"),
            Journal(id=12, scene_id=2, character_id=7, entry="e2", state="s2", history="h2"),
        ),
        _ordinal={n: n for n in range(1, 5)},
    )
