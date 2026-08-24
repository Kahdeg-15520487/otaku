"""The lore view's label arithmetic — the parts both frontends print
beside a scene, promised as DATA (`scene_no`, `scene_span`) so neither
ever has to fish them back out of the display label."""

from otaku.backend.api.lore import LoreView
from otaku.store.schema import Scene


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
