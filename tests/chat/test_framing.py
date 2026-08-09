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

from otaku.chat.framing import framing, prompt_to_wire
from otaku.settings.prompts import Prompts

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
        assert framing("/you").check() == "Usage: /you NAME"

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

    def test_an_inliner_becomes_its_own_enclosure(self) -> None:
        got = prompt_to_wire("She looks up /ooc make her nervous", None, is_last=True)
        assert got == "She looks up ((OOC: make her nervous))"

    def test_a_command_and_an_inliner_compose_together(self) -> None:
        got = prompt_to_wire("/me Elara: I step in /ooc nervous", ME, is_last=True)
        assert got == "<<Elara speaks>>\nI step in ((OOC: nervous))"

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

    # Prose keeps its slashes.
    def test_a_slash_inside_a_word_is_prose(self) -> None:
        got = prompt_to_wire("She looks up and/or down", None, is_last=True)
        assert got == "She looks up and/or down"

    def test_a_url_spelling_an_inliner_is_prose(self) -> None:
        got = prompt_to_wire("Read https://x.co/ooc now", None, is_last=True)
        assert got == "Read https://x.co/ooc now"


def _kinds(line: str) -> tuple[str, str]:
    """`(request_kind, reply_kind)` — read together, since the point is
    where they differ."""
    return framing(line).request_kind, framing(line).reply_kind
