"""The framing syntax.

`check` returns the usage line for a malformed prompt and None for a
good one — an unknown `/word` is prose, not an error.
`framing(line)` answers with the command the line opened with, prose
included, so nothing has to test for its absence: `template` gives the
named template with both placeholders still in it, and `request_kind` and
`reply_kind` mark the two rows — disagreeing for `/you`, which instructs
out of character but asks for the scene in character.

`prompt_to_wire` composes what the model reads. Two shapes reach it: a
turn stored before the syntax existed, whose prose was already stripped of
its prefix and whose framing already names its character (v1), and a turn
stored since, which holds the line exactly as typed (v2). An inliner's
text becomes its own enclosure; a cue is there only while its turn is the
newest.
"""

from otaku.chat.framing import card_to_wire, framing, prompt_to_wire
from otaku.settings.prompts import Prompts
from otaku.transfer.card import Card, card_toml

PROMPTS = Prompts(
    me_framing="<<{name} speaks>>\n{body}",
    you_framing="<<now play {name}>>",
    ooc_framing="<<aside: {body}>>",
)

# What a v2 turn stores: the template, placeholders intact.
ME = PROMPTS.me_framing
YOU = PROMPTS.you_framing
OOC = PROMPTS.ooc_framing


class TestCheck:
    def test_prose_is_always_valid(self) -> None:
        assert framing("She looks up.").check() is None

    def test_an_unknown_command_is_prose(self) -> None:
        assert framing("/shrug at it").check() is None

    def test_a_well_formed_me_passes(self) -> None:
        assert framing("/me Elara: I step in.").check() is None

    def test_me_needs_a_colon(self) -> None:
        assert framing("/me Elara I step in").check() == "Usage: /me NAME: PROMPT"

    def test_me_needs_prose_after_the_colon(self) -> None:
        assert framing("/me Elara:").check() == "Usage: /me NAME: PROMPT"

    def test_me_needs_a_name(self) -> None:
        assert framing("/me : I step in.").check() == "Usage: /me NAME: PROMPT"

    def test_you_needs_a_name(self) -> None:
        assert framing("/you").check() == "Usage: /you NAME[: HINT]"

    def test_you_takes_an_optional_hint_after_a_colon(self) -> None:
        assert framing("/you Elara: be cold").check() is None
        assert framing("/you Elara:").check() is None  # an empty hint is the bare form

    def test_ooc_needs_prose(self) -> None:
        assert framing("/ooc").check() == "Usage: /ooc PROMPT"

    def test_an_inliner_needs_text_after_it(self) -> None:
        assert framing("She looks up /cue").check() is not None

    def test_a_command_and_an_inliner_can_share_a_line(self) -> None:
        assert framing("/me Elara: I step in /cue keep it tense").check() is None


class TestTemplate:
    def test_prose_names_no_template(self) -> None:
        assert framing("She looks up.").template(PROMPTS) is None

    def test_each_command_names_its_own(self) -> None:
        assert framing("/me Elara: hi").template(PROMPTS) == ME
        assert framing("/you Elara").template(PROMPTS) == YOU
        assert framing("/ooc What genre?").template(PROMPTS) == OOC

    def test_the_template_is_taken_verbatim(self) -> None:
        # Both holes survive: the name is filled at wire time, from the
        # line itself, and the body with it.
        got = framing("/me Elara: hi").template(PROMPTS)
        assert got is not None
        assert "{name}" in got and "{body}" in got

    def test_the_templates_come_from_the_prompts_given(self) -> None:
        assert framing("/me Elara: hi").template(Prompts(me_framing="X{name}")) == "X{name}"


class TestKinds:
    def test_prose_plays_the_story(self) -> None:
        assert _kinds("She looks up.") == ("dialogue", "dialogue")

    def test_me_plays_the_story(self) -> None:
        assert _kinds("/me Elara: hi") == ("dialogue", "dialogue")

    def test_ooc_asks_and_answers_out_of_character(self) -> None:
        assert _kinds("/ooc What genre?") == ("ooc", "ooc")

    def test_you_instructs_out_of_character_but_wants_the_scene(self) -> None:
        # The one place the two disagree. Inferring the reply from the row
        # would answer a character switch out of character.
        assert _kinds("/you Elara") == ("ooc", "dialogue")

    def test_an_inliner_changes_neither(self) -> None:
        assert _kinds("She looks up /ooc nervous") == ("dialogue", "dialogue")


class TestPromptToWire:
    def test_prose_goes_out_as_it_is(self) -> None:
        assert prompt_to_wire("She looks up.", None, is_last=True) == "She looks up."

    def test_a_command_prefix_never_reaches_the_model(self) -> None:
        got = prompt_to_wire("/me Elara: I step in.", ME, is_last=True)
        assert got == "<<Elara speaks>>\nI step in."

    def test_a_bodyless_command_sends_its_framing_alone(self) -> None:
        assert prompt_to_wire("/you Elara", YOU, is_last=True) == "<<now play Elara>>"

    def test_ooc_slots_its_prose_into_the_template(self) -> None:
        got = prompt_to_wire("/ooc What genre?", OOC, is_last=True)
        assert got == "<<aside: What genre?>>"

    def test_the_name_comes_from_the_line_not_the_cast(self) -> None:
        # No lookup anywhere: the spelling typed is the spelling sent, so a
        # turn's wire text never shifts when the cast changes.
        got = prompt_to_wire("/me elara: I bow.", ME, is_last=True)
        assert got == "<<elara speaks>>\nI bow."

    def test_an_edited_away_command_drops_its_template(self) -> None:
        # The browser edit can strip a row's leading command; the framing
        # goes with it — never a literal `{name}` on the wire. A v1
        # framing, its name baked in and no placeholder, still joins.
        assert prompt_to_wire("Just prose now.", ME, is_last=True) == "Just prose now."
        v1 = "((OOC: The user writes as Elara.))\n{body}"
        got = prompt_to_wire("Edited prose.", v1, is_last=True)
        assert got == "((OOC: The user writes as Elara.))\nEdited prose."

    def test_an_inliner_becomes_its_own_enclosure(self) -> None:
        got = prompt_to_wire("She looks up /ooc make her nervous", None, is_last=True)
        assert got == "She looks up ((OOC: make her nervous))"

    def test_a_command_and_an_inliner_compose_together(self) -> None:
        got = prompt_to_wire("/me Elara: I step in /ooc nervous", ME, is_last=True)
        assert got == "<<Elara speaks>>\nI step in ((OOC: nervous))"

    def test_a_cue_on_a_me_line_is_spent_like_any_cue(self) -> None:
        kept = prompt_to_wire("/me Elara: I bow /cue whisper", ME, is_last=True)
        assert kept == "<<Elara speaks>>\nI bow ((OOC: whisper))"
        later = prompt_to_wire("/me Elara: I bow /cue whisper", ME, is_last=False)
        assert later == "<<Elara speaks>>\nI bow"

    def test_a_cue_on_an_ooc_line_rides_beside_the_aside(self) -> None:
        got = prompt_to_wire("/ooc what now /cue short", OOC, is_last=True)
        assert got == "<<aside: what now>> ((OOC: short))"

    def test_a_spent_cue_leaves_no_trace_on_a_bodyless_line(self) -> None:
        # Empty parts drop: no dangling space where the cue was.
        got = prompt_to_wire("/you Elara /cue whisper", "<<play {name}. {body}>>", is_last=False)
        assert got == "<<play Elara.>>"

    def test_the_first_inliner_owns_the_rest_of_the_line(self) -> None:
        # The line is split at its FIRST inliner; a second spelling after
        # it is text inside the first one's enclosure.
        got = prompt_to_wire("She waits /ooc slow down /cue whisper", None, is_last=False)
        assert got == "She waits ((OOC: slow down /cue whisper))"

    def test_a_newline_bounds_an_inliner_like_a_space(self) -> None:
        # Inside a \"\"\" block an inliner may open its own line.
        text = "She waits.\n/cue whisper"
        assert prompt_to_wire(text, None, is_last=True) == "She waits. ((OOC: whisper))"
        assert prompt_to_wire(text, None, is_last=False) == "She waits."

    def test_a_me_line_keeps_its_interior_newlines(self) -> None:
        # A \"\"\" block is an ordinary prompt: the layout inside is prose.
        got = prompt_to_wire("/me Elara: I bow.\nThe hall is cold.", ME, is_last=True)
        assert got == "<<Elara speaks>>\nI bow.\nThe hall is cold."

    def test_an_unknown_command_goes_out_verbatim(self) -> None:
        assert prompt_to_wire("/shrug at it", None, is_last=True) == "/shrug at it"

    def test_the_writers_own_braces_are_never_placeholders(self) -> None:
        # {name} fills into the TEMPLATE before the text joins it, and the
        # text is never scanned again — typed braces survive literally.
        got = prompt_to_wire("/me Elara: I read {name} aloud.", ME, is_last=True)
        assert got == "<<Elara speaks>>\nI read {name} aloud."
        got = prompt_to_wire("/me Elara: literally {body} here", ME, is_last=True)
        assert got == "<<Elara speaks>>\nliterally {body} here"

    def test_a_you_hint_slots_into_the_templates_body(self) -> None:
        got = prompt_to_wire("/you Elara: be cold", "<<play {name}. {body}>>", is_last=False)
        assert got == "<<play Elara. be cold>>"

    def test_a_bare_you_takes_the_empty_slot_and_its_space_out(self) -> None:
        # So a template ending "… {body}))" sends, bare, the exact wire it
        # sent before the slot existed.
        got = prompt_to_wire("/you Elara", "<<play {name}. {body}>>", is_last=False)
        assert got == "<<play Elara.>>"

    def test_a_you_hint_without_a_slot_becomes_its_own_aside(self) -> None:
        # A template from before the slot existed still carries the hint —
        # enclosed, never joined bare: direction is never story.
        got = prompt_to_wire("/you Elara: be cold to the guest", YOU, is_last=True)
        assert got == "<<now play Elara>> ((OOC: be cold to the guest))"

    def test_a_you_hint_is_never_spent(self) -> None:
        # The hint is the standing form — /cue is the one-shot one, and
        # both may ride the same line.
        got = prompt_to_wire("/you Elara: be cold /cue whisper", YOU, is_last=False)
        assert got == "<<now play Elara>> ((OOC: be cold))"

    def test_a_you_hint_and_an_inline_aside_share_a_line(self) -> None:
        got = prompt_to_wire(
            "/you Elara: be cold /ooc keep it brief", "<<play {name}. {body}>>", is_last=False
        )
        assert got == "<<play Elara. be cold>> ((OOC: keep it brief))"

    # A cue is spent; an ooc aside is not.
    def test_a_cue_goes_out_while_its_turn_is_newest(self) -> None:
        got = prompt_to_wire("She looks up /cue keep it tense", None, is_last=True)
        assert got == "She looks up ((OOC: keep it tense))"

    def test_a_cue_is_gone_from_every_later_turn(self) -> None:
        got = prompt_to_wire("She looks up /cue keep it tense", None, is_last=False)
        assert got == "She looks up"

    def test_an_ooc_aside_is_never_spent(self) -> None:
        got = prompt_to_wire("She looks up /ooc nervous", None, is_last=False)
        assert got == "She looks up ((OOC: nervous))"

    # v1: turns written before the syntax existed must compose unchanged.
    def test_a_legacy_framed_turn_slots_its_bare_body(self) -> None:
        # Stored back then: the prose alone, the name already in the
        # framing. Nothing here may strip or re-fill anything.
        assert prompt_to_wire("I step in.", "<<Elara speaks>>\n{body}", is_last=True) == (
            "<<Elara speaks>>\nI step in."
        )

    def test_a_legacy_bodyless_turn_sends_its_framing(self) -> None:
        assert prompt_to_wire("", "<<now play Elara>>", is_last=True) == "<<now play Elara>>"

    def test_a_legacy_plain_turn_is_untouched(self) -> None:
        assert prompt_to_wire("I step in.", None, is_last=True) == "I step in."

    def test_a_legacy_body_is_never_read_as_syntax(self) -> None:
        # Its prefix was stripped before storing, so a slash inside it is
        # prose — and a framing with no placeholder leads its body.
        assert prompt_to_wire("and/or it", "<<note>>", is_last=True) == "<<note>>\n\nand/or it"

    def test_a_legacy_body_keeps_an_inliner_spelling_literally(self) -> None:
        # The legacy branch composes before any syntax is read: text that
        # LOOKS like an inliner is prose there, and never spent.
        got = prompt_to_wire("I bow /cue whisper", "<<note>>\n{body}", is_last=False)
        assert got == "<<note>>\nI bow /cue whisper"

    # Prose keeps its slashes.
    def test_a_slash_inside_a_word_is_prose(self) -> None:
        got = prompt_to_wire("She looks up and/or down", None, is_last=True)
        assert got == "She looks up and/or down"

    def test_a_url_spelling_an_inliner_is_prose(self) -> None:
        got = prompt_to_wire("Read https://x.co/ooc now", None, is_last=True)
        assert got == "Read https://x.co/ooc now"


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


# ---------- building card files in memory ----------


def _kinds(line: str) -> tuple[str, str]:
    """`(request_kind, reply_kind)` — read together, since the point is
    where they differ."""
    return framing(line).request_kind, framing(line).reply_kind
