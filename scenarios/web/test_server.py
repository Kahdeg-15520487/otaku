"""The page over a real session: what the browser asks for, and gets.

One thread serves, the test's own stands in for the browser. The stories
here are the ones a person plays through the page — open it, read the
story, play a line, run a command — asserted on the wire and in the
store, never on the screen.
"""

import base64
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from otaku.backend import commands
from otaku.backend.session import THINK_MENU
from scenarios.support.server import ModelServer
from scenarios.web.conftest import Page

SERAPHINA = Path(__file__).parent.parent / "fixtures" / "seraphina.png"


class TestServing:
    def test_the_page_and_everything_it_needs_are_served(self, page: Page) -> None:
        assert b"<title>otaku</title>" in page.get("/")
        for asset in ("/app.css", "/overrides.css", "/app.js", "/js/stories.js"):
            assert page.status(asset) == 200, asset

    def test_nothing_is_cached_and_the_fonts_are(self, page: Page) -> None:
        # The rule the whole frontend is built on: what is on disk is
        # what the browser has. The fonts carry their version in the name.
        for asset in ("/", "/app.css", "/app.js", "/custom.css"):
            assert "no-store" in page.headers(asset)["cache-control"], asset
        assert "immutable" in page.headers("/fonts/IBMPlexSans-400.woff2")["cache-control"]

    def test_a_missing_stylesheet_of_the_reader_s_own_is_an_empty_one(self, page: Page) -> None:
        # Absent is the normal case: a red line in the console is not a
        # state to design for.
        assert page.get("/custom.css") == b""

    def test_only_the_table_may_be_served(self, page: Page) -> None:
        # A path is looked up, never joined onto a directory.
        for escape in ("/../pyproject.toml", "/../../etc/passwd", "/configs/providers.toml"):
            assert page.status(escape) == 404, escape

    def test_an_unknown_path_is_not_found(self, page: Page) -> None:
        assert page.status("/api/read/nonesuch") == 404
        assert page.status("/api/nonesuch") == 404
        assert page.status("/api/do/nonesuch", method="POST") == 404

    def test_the_watch_stream_opens_and_names_its_retry(self, page: Page) -> None:
        # The page holds this one open for as long as the tab is, so it
        # is read a frame at a time and never to the end. The first
        # frame is the retry — how soon a browser comes back after a
        # restart, which is what makes the tab reload itself.
        opened = page.stream("/api/watch")
        assert opened.headers["Content-Type"] == "text/event-stream"
        assert opened.readline().startswith(b"retry:")
        opened.close()


class TestTheHeartbeat:
    """`/api/alive` is how a tab that is asking for nothing else learns
    that otaku stopped — and what the background worker is doing while
    nobody asked. It is in neither lane, and the difference shows
    exactly when the session's thread is not free."""

    def test_it_answers_what_can_be_answered_off_the_session_s_thread(self, page: Page) -> None:
        beat = page.get("/api/alive")
        assert beat == {"status": "", "notices": []}

    def test_it_answers_while_a_reply_is_streaming(self, page: Page, server: ModelServer) -> None:
        # The one moment the session's thread is unavailable: it is
        # holding a reply, chunk by chunk. The heartbeat never asks for
        # that thread, which is what makes it an answer about the SERVER
        # — so it comes back with the reply still going.
        server.chunk_delay = 1.0
        replying = threading.Thread(target=page.play, args=("A long look at the water.",))
        replying.start()
        try:
            time.sleep(0.5)
            assert page.status("/api/alive") == 200
            assert replying.is_alive(), "the reply was over — the story proves nothing"
        finally:
            replying.join(timeout=30)


class TestReading:
    def test_the_session_facts_name_the_model(self, page: Page) -> None:
        facts = page.get("/api/read/session")
        # The bare model in the header, the provider beside it — the
        # banner's own split, which the page draws in two places.
        assert facts["model"] == "test-model"
        assert facts["engine"]

    def test_the_turns_are_the_story_as_the_store_has_it(self, page: Page) -> None:
        page.play("I listen at the culvert mouth.")
        story = page.get("/api/read/session")["story_id"]
        assert [turn["body"] for turn in page.get("/api/read/turns")] == [
            message.body for message in page.store.stories.get_messages(story)
        ]

    def test_the_command_table_is_the_shared_one(self, page: Page) -> None:
        table = page.get("/api/read/commands")
        assert {row["token"] for row in table["rows"]} >= {"/fork", "/set think", "… /cue"}
        assert table["prose"]["group"] in table["groups"]

    def test_a_read_that_refuses_answers_with_the_sentence(self, page: Page) -> None:
        # A refusal IS the answer — 200 and a notice, not an error page.
        assert page.get("/api/read/usage")["notice"].startswith("No story yet")

    def test_the_settings_read_carries_the_shared_effort_ladder(self, page: Page) -> None:
        # The order is declared ONCE, below both frontends — the page
        # draws it, never re-sorts it.
        assert page.get("/api/read/settings")["think_levels"] == list(THINK_MENU)

    def test_the_search_matches_buried_content_and_the_row_s_face(self, page: Page) -> None:
        """One filter rule for both browsers: a story is found by the
        text of its chain AND by what its listing row shows — here the
        title, which is never a message."""
        page.play("I listen at the culvert mouth.")
        story = page.get("/api/read/session")["story_id"]
        page.post("/api/command", {"line": "/title The Beached Ferry"})
        assert story in page.get("/api/read/search?q=culvert")  # chain text
        assert story in page.get("/api/read/search?q=beached")  # the row's face
        assert story not in page.get("/api/read/search?q=zeppelin")

    def test_a_malformed_read_argument_is_a_bad_request(self, page: Page) -> None:
        assert page.status("/api/read/story?id=abc") == 400


class TestPlaying:
    def test_a_line_plays_and_lands_in_the_store(self, page: Page) -> None:
        events = page.play("I unroll the county survey.")
        kinds = [event["type"] for event in events]
        assert kinds[0] == "recorded"
        assert "text" in kinds
        assert kinds[-1] == "done"
        story = page.get("/api/read/session")["story_id"]
        stored = page.store.stories.get_messages(story)
        assert stored[-2].body == "I unroll the county survey."
        assert stored[-1].role == "assistant"

    def test_the_wire_carries_what_the_page_typed(self, page: Page, server: ModelServer) -> None:
        page.play("I mark the river's true course.")
        assert server.requests[-1]["messages"][-1]["content"] == "I mark the river's true course."

    def test_a_refusal_arrives_before_a_byte_of_the_stream(self, page: Page) -> None:
        # Eager validation: invalid syntax leaves the story untouched and
        # the usage line is the whole answer.
        answer = page.play("/you")
        assert answer[0]["refused"] is True
        assert answer[0]["notice"]


class TestCommands:
    def test_a_command_line_is_answered_with_its_sentence(self, page: Page) -> None:
        page.play("I listen at the culvert mouth.")
        answer = page.post("/api/command", {"line": "/title The Beached Ferry"})
        assert "The Beached Ferry" in answer["notice"]
        story = page.get("/api/read/session")["story_id"]
        assert page.store.stories.get(story).title == "The Beached Ferry"

    def test_a_write_a_screen_performs_goes_through_the_actions_table(self, page: Page) -> None:
        page.play("I listen at the culvert mouth.")
        story = page.get("/api/read/session")["story_id"]
        first = page.store.stories.get_messages(story)[0]
        answer = page.post("/api/do/edit-message", {"message": first.id, "text": "I listen."})
        assert answer["notice"]
        assert page.store.stories.get_messages(story)[0].body == "I listen."

    def test_a_malformed_body_is_the_page_s_fault_not_a_crash(self, page: Page) -> None:
        # A field the page did not send is a bad request, not a 500.
        assert page.status("/api/do/edit-message", method="POST") == 400

    def test_a_refusal_is_marked_so_the_page_never_reads_the_wording(self, page: Page) -> None:
        # Nothing to undo is an expected answer: 200, the sentence, and
        # the FLAG — the wire contract that keeps sentence-sniffing out
        # of the page.
        answer = page.post("/api/command", {"line": "/undo"})
        assert answer["refused"] is True
        assert answer["notice"]

    def test_an_unknown_command_is_refused_with_the_shared_sentence(self, page: Page) -> None:
        # Both frontends refuse a typo with the same words: the wire
        # carries exactly what the terminal composes — the /set family's
        # answer being the usage line built from the table.
        answer = page.post("/api/command", {"line": "/frobnicate"})
        assert answer["refused"] is True
        assert answer["notice"] == commands.unknown_notice("/frobnicate")
        family = page.post("/api/command", {"line": "/set bogus on"})
        assert family["notice"] == commands.unknown_notice("/set bogus on")

    def test_the_composer_history_is_the_store_s(self, page: Page) -> None:
        # The page records what was submitted and reads it back most
        # recent first — the same lines the terminal prompt walks, so a
        # reload starts with the history it left.
        page.post("/api/do/record-history", {"line": "I listen at the culvert mouth."})
        page.post("/api/do/record-history", {"line": "/stories"})
        recent = page.get("/api/read/history")
        assert recent[:2] == ["/stories", "I listen at the culvert mouth."]


class TestTheFlows:
    """The writes whose result outlives their request: a forced pass the
    page polls for, and a card import split around its persona ask."""

    def test_a_forced_extraction_is_started_and_its_report_polled(self, page: Page) -> None:
        page.play("I listen at the culvert mouth.")
        page.play("I wade into the dark after the voice.")
        started = page.post("/api/do/extract")
        assert started["watching"] is True
        report = _polled(page)
        assert report  # the scripted server closes a scene; the report says so
        story = page.get("/api/read/session")["story_id"]
        ids = [m.id for m in page.store.stories.get_messages(story)]
        assert page.store.scenes.get_current(story, ids)

    def test_a_card_lands_through_the_prepare_and_add_halves(self, page: Page) -> None:
        page.play("I listen at the culvert mouth.")
        prepared = page.post(
            "/api/do/prepare-card",
            {"data": base64.b64encode(SERAPHINA.read_bytes()).decode(), "name": "seraphina.png"},
        )
        assert prepared["card"]["name"] == "Seraphina"
        answer = page.post("/api/do/add-card", {"token": prepared["token"], "persona": "Maren"})
        assert "Seraphina" in answer["notice"]
        story = page.get("/api/read/session")["story_id"]
        names = {c.name for c in page.store.characters.list(story)}
        assert "Seraphina" in names

    def test_a_token_nobody_holds_adds_nothing(self, page: Page) -> None:
        # A reload between the halves, or a page that asked twice: an
        # ordinary answer, and the cast is untouched.
        page.play("I listen at the culvert mouth.")
        answer = page.post("/api/do/add-card", {"token": "gone", "persona": "Maren"})
        assert answer["notice"]
        story = page.get("/api/read/session")["story_id"]
        assert page.store.characters.list(story) == []

    def test_an_imported_document_starts_the_pass_the_page_watches(self, page: Page) -> None:
        landed = page.post(
            "/api/do/import",
            {"text": "A lantern swings on the pier.\n\nNobody holds it.", "name": "pier.txt"},
        )
        assert landed["watching"] is True  # memoryless shape: memory builds now
        assert _polled(page)
        story = page.get("/api/read/session")["story_id"]
        assert [m.body for m in page.store.stories.get_messages(story)] == [
            "A lantern swings on the pier.",
            "Nobody holds it.",
        ]


def _polled(page: Page, timeout: float = 30.0) -> str:
    """The report as the page's own poll would read it — None until the
    pass returns, then the sentence."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        report = page.get("/api/read/extract")["report"]
        if report is not None:
            return str(report)
        time.sleep(0.1)
    raise AssertionError("the pass never reported")


class TestWhoIsAsking:
    """The page has no login, and it does not need one — but a page on
    another origin, in the same browser, must not be able to drive it.
    A write can do its damage without ever reading the answer."""

    def test_a_cross_site_write_is_refused(self, page: Page) -> None:
        # What an auto-submitting form on another site sends. It cannot
        # forge `Sec-Fetch-Site`, and a form's content type is never
        # application/json without a preflight this server never answers.
        page.play("I listen at the culvert mouth.")
        story = page.get("/api/read/session")["story_id"]
        assert (
            page.status(
                "/api/command",
                method="POST",
                headers={
                    "Sec-Fetch-Site": "cross-site",
                    "Origin": "http://evil.example",
                    "Content-Type": "text/plain;charset=UTF-8",
                },
                data=b'{"line": "/title Pwned"}',
            )
            == 403
        )
        assert page.store.stories.get(story).title != "Pwned"

    def test_a_cross_origin_write_is_refused_without_the_fetch_metadata(self, page: Page) -> None:
        assert (
            page.status(
                "/api/do/save-field",
                method="POST",
                headers={"Origin": "http://evil.example"},
                data=b'{"provider":"test","field":"url","value":"http://attacker.example/v1"}',
            )
            == 403
        )

    def test_the_page_s_own_writes_are_let_through(self, page: Page) -> None:
        # What the page itself sends — same-origin fetch metadata.
        assert (
            page.status(
                "/api/command",
                method="POST",
                headers={"Sec-Fetch-Site": "same-origin", "Origin": page.url},
                data=b'{"line": "/title The Lock"}',
            )
            == 200
        )

    def test_a_request_addressed_to_another_name_is_misdirected(self, page: Page) -> None:
        # DNS rebinding is the one attack a loopback bind does not stop:
        # the name in the request is what gives it away.
        assert page.status("/api/read/turns", headers={"Host": "attacker.example"}) == 421
        assert page.status("/api/read/turns", headers={"Host": "localhost"}) == 200

    def test_a_malformed_length_is_a_bad_request_not_a_crash(self, page: Page) -> None:
        import socket
        from urllib.parse import urlsplit

        where = urlsplit(page.url)
        with socket.create_connection((where.hostname, where.port), timeout=5) as scanner:
            scanner.sendall(
                b"POST /api/command HTTP/1.1\r\nHost: localhost\r\nContent-Length: abc\r\n\r\n{}"
            )
            answered = scanner.recv(64)
        assert answered.startswith(b"HTTP/1.")


class TestThePicker:
    def test_a_provider_configured_by_hand_is_in_the_picker(self, page: Page) -> None:
        # The scenario's own provider is a hand-written section named
        # `test` — not one of the engines otaku ships a client for. The
        # session is PLAYING on it, so a picker without it is a picker
        # with no way back to the story's own model.
        panel = page.get("/api/read/providers")
        mine = next(engine for engine in panel["engines"] if engine["name"] == "test")
        assert [model["name"] for model in mine["models"]] == ["test-model"]
        assert panel["current"] == "test/test-model"
        assert mine["connected"] is True


class TestOpenToTheNetwork:
    """`[web] host = 0.0.0.0` is the documented way to reach otaku from
    another machine. The rebinding guard must not be what stops it: a
    wildcard bind has already decided to answer everyone, and the
    address a LAN client names is one otaku cannot know."""

    def test_a_wildcard_bind_answers_to_any_name(self, wide: Page) -> None:
        assert wide.status("/", headers={"Host": "192.168.178.21:9600"}) == 200
        assert wide.status("/api/read/turns", headers={"Host": "otaku.lan"}) == 200

    def test_a_write_from_the_app_one_port_over_is_still_refused(self, wide: Page) -> None:
        # The neighbour this guard is for: another app on the same host,
        # which shares the name but not the origin.
        assert (
            wide.status(
                "/api/do/save-field",
                method="POST",
                headers={"Host": "otaku.lan:9600", "Origin": "http://otaku.lan:8080"},
                data=b'{"provider":"test","field":"url","value":"http://attacker.example/v1"}',
            )
            == 403
        )

    def test_the_page_s_own_write_is_let_through(self, wide: Page) -> None:
        assert (
            wide.status(
                "/api/command",
                method="POST",
                headers={"Host": "otaku.lan:9600", "Origin": "http://otaku.lan:9600"},
                data=b'{"line": "/title From the page itself"}',
            )
            == 200
        )


class TestStopping:
    def test_a_request_that_outlives_the_serving_is_answered(self, page: Page) -> None:
        """A browser holds its connection open, so a request can arrive
        after the serving is over. Not a crash and not a wait: the
        reader stopped otaku, which is an answer a request can get."""
        where = urlsplit(page.url)
        held = HTTPConnection(where.hostname, where.port, timeout=10)
        held.request("GET", "/api/read/turns")
        held.getresponse().read()  # kept alive
        page.stop()
        held.request("GET", "/api/read/turns")
        answered = held.getresponse()
        answered.read()
        held.close()
        assert answered.status == 503
