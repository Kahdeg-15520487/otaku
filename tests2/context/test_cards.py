"""Cards as context material: the wire block composed from the archive
(`card_to_wire`), bound at wire time."""

import tomllib

from otaku2.context.cards import Card, bind, card_to_wire, card_toml


class TestCardToWire:
    TEMPLATE = (
        "((OOC: You are joined by {name}.\n"
        "Description: {description}\n"
        "Personality: {personality}\n"
        "Scenario: {scenario}\n"
        "How they speak: {examples}\n"
        "Note: {depth_note}))"
    )

    def test_fills_and_binds_in_one_pass(self) -> None:
        card = Card(name="Elara", description="{{char}} guards {{user}}", personality="stern")
        got = card_to_wire(card_toml(card, user="Alex"), self.TEMPLATE)
        assert "You are joined by Elara." in got
        assert "Description: Elara guards Alex" in got
        assert "Personality: stern" in got

    def test_a_line_of_empty_placeholders_is_dropped(self) -> None:
        card = Card(name="Elara", description="warden")
        got = card_to_wire(card_toml(card, user="A"), self.TEMPLATE)
        assert "Scenario:" not in got
        assert "Note:" not in got
        assert "How they speak:" not in got  # no examples — the label goes with them

    def test_the_examples_join_as_blocks(self) -> None:
        card = Card(name="E", examples=("a: hi", "b: yo"))
        got = card_to_wire(card_toml(card, user="U"), "X:\n{examples}")
        assert "a: hi\n\nb: yo" in got

    def test_braces_inside_card_text_are_never_placeholders(self) -> None:
        # One pass over the TEMPLATE only: values are not re-scanned.
        card = Card(name="E", description="use {personality} literally")
        got = card_to_wire(card_toml(card, user="U"), "D: {description}\nP: {personality}")
        assert "D: use {personality} literally" in got
        assert "\nP:" not in got  # personality itself is empty -> line dropped

    def test_an_unknown_placeholder_is_left_as_written(self) -> None:
        got = card_to_wire(card_toml(Card(name="E"), user="U"), "hello {nonsense}")
        assert got == "hello {nonsense}"


class TestBind:
    def test_both_names_in_any_case(self) -> None:
        text = "{{char}} met {{USER}}; {{ Char }} smiled at {{user}}"
        assert bind(text, char="Elara", user="Alex") == "Elara met Alex; Elara smiled at Alex"

    def test_the_tavern_era_spellings(self) -> None:
        assert bind("<BOT> waves to <USER>", char="Elara", user="Alex") == "Elara waves to Alex"

    def test_unknown_macros_stay_written(self) -> None:
        assert bind("roll {{roll:d20}}", char="E", user="U") == "roll {{roll:d20}}"

    def test_a_backslash_in_a_name_survives(self) -> None:
        assert bind("{{char}}!", char=r"El\ara", user="U") == r"El\ara!"


class TestCardToml:
    def test_round_trips_field_for_field(self) -> None:
        card = Card(
            name="Elara",
            description="line one\nline 'two'",
            personality="it's complicated",
            greeting='she says "hi"\nand waits',
            alternate_greetings=("a", "b"),
            examples=("x: 1", "y: 2"),
        )
        data = tomllib.loads(card_toml(card, user="Alex"))
        assert data["name"] == "Elara"
        assert data["user"] == "Alex"
        assert data["description"] == card.description
        assert data["personality"] == card.personality
        assert data["greeting"] == card.greeting
        assert data["alternate_greetings"] == ["a", "b"]
        assert data["examples"] == ["x: 1", "y: 2"]

    def test_empty_fields_are_omitted(self) -> None:
        text = card_toml(Card(name="E"), user="U")
        assert "description" not in text and "examples" not in text

    def test_macros_are_archived_unbound(self) -> None:
        # The archive keeps the source; the bindings ride as data.
        card = Card(name="Elara", description="{{char}} waits for {{user}}")
        data = tomllib.loads(card_toml(card, user="Alex"))
        assert data["description"] == "{{char}} waits for {{user}}"

    def test_a_triple_quote_in_card_text_still_round_trips(self) -> None:
        card = Card(name="E", description="she said '''no'''")
        data = tomllib.loads(card_toml(card, user="U"))
        assert data["description"] == "she said '''no'''"
