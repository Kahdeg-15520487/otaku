"""The local server: HTTP, and nothing else — bind, route, frame, reply.

One user on loopback, traffic close to zero — so the stdlib's threading
server is the whole of it, and every asset is read from disk per request
rather than held in memory, which is what makes an edit visible without
a restart. `/api/watch` is the other half of that promise: the page
holds it open and reloads itself when a file it is made of changes, so
an edit to the packaged page or to the reader's own `custom.css` shows
up without a restart and without a reload anybody has to remember.

What a request MEANS is `web.api`'s: a handler looks a path up — in the
asset table below, or in `api`'s own tables — and carries the result.
The thread that owns the session is `web.runner`; everything above HTTP
(the banner, the tail, Ctrl+C, the wiring of all three) is `web.run`,
which is also the only place anything is printed: the serving is handed
one line per request worth showing (`Hooks`) and knows nothing about
where it appears. What the stdlib would have put in the terminal on its
own — an access line per font, a traceback per closed tab — is answered
instead, in `_Handler.log_request` and `_Server.handle_error`.

What may be served is a CLOSED table: a request path is looked up, never
joined onto a directory, so no request can compose its way to
`configs/providers.toml`.

The API is two prefixes, and the prefix IS the lane. `/api/read/…` only
reads the session and is answered on the read queue — during a reply as
well as between them, which is what keeps every screen answerable while
the model talks. `/api/do/…`, `/api/command` and `/api/play` move the
story and take the one thread in turn, in the order they arrived.

The document, the stylesheet and the scripts are `no-store` — they are
small, they are local, and a stale one costs more than the bytes ever
will; the fonts are immutable and long-lived, which is why they carry
version numbers in their names instead.

`custom.css` is the one asset that is NOT packaged: it comes from the
state dir (`web/custom.css`), is absent by default, and is loaded last so
that anything in it wins. The token contract it writes against is
`docs/web_tokens.md`.
"""

import contextlib
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from otaku.backend import commands
from otaku.backend.api.play import PlayEvent
from otaku.backend.session import Refused, Session
from otaku.settings.config import WebSettings
from otaku.web import api
from otaku.web.runner import SessionRunner, StoppingError

__all__ = ["LOOPBACK", "Hooks", "bind"]


# The packaged assets, read per request — and the same directory as a
# plain path, which is what a watcher can stat: a Traversable promises no
# mtime.
_STATIC = files("otaku.web") / "static"
_STATIC_PATH = Path(__file__).parent / "static"

_HTML = "text/html; charset=utf-8"
_CSS = "text/css; charset=utf-8"
_JS = "text/javascript; charset=utf-8"
_EVENT_STREAM = "text/event-stream"
_JSON = "application/json; charset=utf-8"
_WOFF2 = "font/woff2"

# The two lanes, spelled in the URL. Everything under `/api/read/` only
# READS the session and is answered on the read queue — during a reply as
# well as between them; everything under `/api/do/` (and `/api/command`,
# and `/api/play`) moves the story and waits its turn. A handler that
# needed the other lane would be in the wrong prefix, which is the point
# of having two.
_READ = "/api/read/"
_DO = "/api/do/"

# A local page is never worth a stale byte; the fonts change about once
# per Plex release and their names change with them.
_NO_STORE = "no-store, no-cache, must-revalidate, max-age=0"
_IMMUTABLE = "public, max-age=31536000, immutable"

_SCRIPTS = (
    "app.js",
    "js/api.js",
    "js/browser.js",
    "js/commands.js",
    "js/composer.js",
    "js/dom.js",
    "js/format.js",
    "js/help.js",
    "js/lore.js",
    "js/models.js",
    "js/reports.js",
    "js/settings.js",
    "js/shell.js",
    "js/stories.js",
    "js/system.js",
    "js/table.js",
    "js/transcript.js",
    "js/transfer.js",
    "js/watch.js",
)

_FONTS = (
    "IBMPlexMono-400.woff2",
    "IBMPlexMono-500.woff2",
    "IBMPlexMono-600.woff2",
    "IBMPlexSans-400.woff2",
    "IBMPlexSans-500.woff2",
    "IBMPlexSans-600.woff2",
)

# request path -> (packaged file, content type, cache policy). Adding an
# asset means adding a row: that is the point.
_ASSETS: dict[str, tuple[str, str, str]] = {
    "/": ("index.html", _HTML, _NO_STORE),
    "/app.css": ("app.css", _CSS, _NO_STORE),
    "/overrides.css": ("overrides.css", _CSS, _NO_STORE),
    **{f"/{name}": (name, _JS, _NO_STORE) for name in _SCRIPTS},
    **{f"/fonts/{name}": (f"fonts/{name}", _WOFF2, _IMMUTABLE) for name in _FONTS},
}

# The page's beat. Neither lane, because it never takes the session's
# THREAD: the handler answers it itself, from what can be read from
# anywhere — that the server is up, what the background worker is doing,
# and what it has said. A session busy with a reply is still a running
# otaku, and this is how the page knows.
_ALIVE = "/api/alive"

# The other request the page makes that nobody asked for: held open for
# as long as the tab is, and answered a filename at a time as the files
# the page is made of change.
_WATCH = "/api/watch"

# What is never worth a line in the terminal: a page load is the
# document and the twenty files that came with it, and only the document
# is news — and neither is the page's own housekeeping, which is a beat
# every few seconds and one stream that never ends.
_QUIET = (set(_ASSETS) | {"/custom.css", _ALIVE, _WATCH}) - {"/"}

# How a request ENDS when the reader closes a tab, reloads mid-reply or
# stops otaku while the page is still streaming. Every one of these is
# ordinary here, and none of them is a crash to report.
_DISCONNECTED = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)

# The spellings of "this machine" — all of them reachable as `localhost`,
# which is what the printed address READS as (`web.run.address`, this
# tuple's other reader and the reason it is public).
LOOPBACK = ("127.0.0.1", "0.0.0.0", "::", "::1", "localhost", "")

# The spellings of "every interface": a bind that is not this machine
# alone, and so not a name anything can be checked against.
_WILDCARD = ("0.0.0.0", "::", "")

# The watch: how long a browser waits before reopening the stream (the
# SSE `retry` field), and how often the files behind it are looked at.
# A second is under the time it takes to alt-tab back to the browser,
# and a stat of thirty files costs nothing next to that.
_RETRY_MS = 2000
_WATCH_INTERVAL = 1.0


@dataclass(frozen=True)
class Hooks:
    """What the serving reaches outside HTTP, injected at composition
    (`web.run.serve`) like every other frontend hook: where a request
    line worth showing goes, where a contained crash is recorded, the
    background worker's voice for the beat — its one-line status, and
    the sentences it has said since anybody last asked — and the ring a
    landed reply calls the reader back with. All are callable from any
    thread; nothing here prints conversation."""

    show: Callable[[str], None]
    record: Callable[[str, BaseException], str]
    working: Callable[[], str]
    sayings: Callable[[], list[str]]
    ring: Callable[[], None]


def bind(
    config: WebSettings,
    runner: SessionRunner,
    pending: api.Pending,
    custom_web_dir: Path,
    hooks: Hooks,
) -> "_Server":
    """The socket, and everything a handler needs behind it. What it
    raises is the socket's own OSError — turning the address that could
    not be honoured into a sentence is `web.run`'s, which is also why
    this is a separate function: the caller catches exactly the
    binding."""
    return _Server(
        (config.host, config.port),
        _Handler,
        runner=runner,
        pending=pending,
        custom_web_dir=custom_web_dir,
        hooks=hooks,
    )


class _Server(ThreadingHTTPServer):
    """The threading server plus what a handler needs: the runner that
    reaches the session, the state that spans requests, where the
    reader's own files live, and the hooks. Daemon threads because a
    held-open event stream must never outlive the interrupt that stopped
    the server."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        bound: tuple[str, int],
        handler: Any,
        *,
        runner: SessionRunner,
        pending: api.Pending,
        custom_web_dir: Path,
        hooks: Hooks,
    ) -> None:
        super().__init__(bound, handler)
        self.runner = runner
        self.pending = pending
        self.custom_web_dir = custom_web_dir
        self.hooks = hooks
        # The names this server answers to: the configured one, and every
        # spelling of the machine it runs on. A request addressed to
        # anything else did not come from a reader typing an address.
        #
        # Empty for a WILDCARD bind, which means every name: a reader who
        # set `0.0.0.0` asked to be reachable from the network, where the
        # address is the machine's own and otaku cannot know it. There is
        # nothing left for a rebinding guard to protect there — the port
        # is already open to everyone who can route to it.
        named = bound[0].strip("[]")
        self.answers_to = (
            frozenset() if named in _WILDCARD else frozenset({named, *LOOPBACK} - {""})
        )
        # Set when the reader asks otaku to stop. Ctrl+C is the USER
        # SPEAKING, not a crash: raising it where it lands would tear
        # open whatever the session thread is doing — most likely a
        # reply, mid-sentence, inside the provider's own generator,
        # where the backend's cancel-and-keep can no longer run and the
        # words already on the reader's screen are lost. So the FIRST
        # one asks: the stream closes itself at the next frame, the
        # partial is recorded exactly as when a browser goes away, and
        # the loop ends after the turn it was in.
        #
        # The first one also hands SIGINT back to Python, so the SECOND
        # is fatal in the ordinary way. A request can only be noticed
        # between events, and a provider that has not reached its first
        # token yields none — without the escalation, pressing it again
        # would do nothing and the only way out of a wedged engine would
        # be `kill`.
        self.stopping = threading.Event()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """What escaped a handler. The stdlib prints a traceback per
        connection to stderr — three screens of socketserver frames,
        under a banner trying to stay six lines tall, for something that
        is usually not a fault at all: a closed tab, a reload mid-reply,
        a Ctrl+C while the page was streaming. Those are the NORMAL end
        of a request here. Anything else is a real bug, and goes where
        every contained crash goes."""
        error = sys.exc_info()[1]
        if error is None or isinstance(error, _DISCONNECTED):
            return
        self.crashed("web request", error)

    def crashed(self, context: str, exc: BaseException) -> str:
        """One contained crash into the day's error log, and one line
        where the reader is. Returns the log's pretty path — "" if even
        the logging failed, which is not a reason to raise again."""
        path = self.hooks.record(context, exc)
        self.hooks.show(f"{context} — {type(exc).__name__}, in {path}" if path else context)
        return path


class _Handler(BaseHTTPRequestHandler):
    server: _Server  # narrowed from BaseServer, so the fields above are visible
    # Whether a reply's headers have gone out: after them there is no
    # status left to send, and a failure can only be logged.
    _streaming = False
    server_version = "otaku"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ---------- routing ----------

    def do_GET(self) -> None:
        if not self._from_this_machine():
            return
        path = self._path()
        if path == _ALIVE:
            self._beat()
        elif path.startswith(_READ):
            self._reading(path[len(_READ) :])
        elif path in _ASSETS:
            name, content_type, cache = _ASSETS[path]
            self._send(self._asset(name), content_type, cache)
        elif path == "/custom.css":
            self._send(self._custom_css(), _CSS, _NO_STORE)
        elif path == _WATCH:
            self._watch_stream()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if not self._from_this_machine() or not self._from_our_page():
            return
        path = self._path()
        body = self._body()
        if path == "/api/play":
            self._play(str(body.get("line", "")), regenerate=bool(body.get("regenerate")))
        elif path == "/api/command":
            self._command(str(body.get("line", "")))
        elif path.startswith(_DO):
            self._doing(path[len(_DO) :], body)
        else:
            self.send_error(404)

    def _beat(self) -> None:
        """The page's "are you still there", and what it can be told
        without asking for the session's thread: what the background
        worker is doing, and anything it has said since the last beat.
        Reaching this at all is the first answer — an otaku deep in a
        reply is still a running otaku — and the other two ride along
        because a reader with the page open should learn that a pass ran
        the same way a terminal does, rather than finding the lore there
        later."""
        self._json({"status": self.server.hooks.working(), "notices": self.server.hooks.sayings()})

    def _reading(self, name: str) -> None:
        """Everything under the read prefix — one lane, which is what
        lets any of these be answered while a reply streams. A read
        takes its argument as a query, never a path segment: what it
        names is a value, not a place."""
        if name == "extract":
            # The one read that is not a row: it must not queue for the
            # session's thread (the answer may be "the pass that owns
            # that thread is still running"), and a run's `poll` is
            # channel-safe by contract, so the handler answers it here.
            run = self.server.pending.extraction
            self._json({"report": run.poll() if run is not None else None})
            return
        read = api.READS.get(name)
        if read is None:
            self.send_error(404)
            return
        query = self._query()
        self._answer(lambda session: read(session, query), reading=True)

    def _doing(self, name: str, body: dict[str, Any]) -> None:
        """One write a screen performed — a flow when its result must
        outlive the request, a plain action otherwise. Both are rows;
        which table answers is this method's whole decision."""
        flow = api.FLOWS.get(name)
        if flow is not None:
            pending = self.server.pending
            self._answer(lambda session: flow(session, pending, body))
            return
        action = api.ACTIONS.get(name)
        if action is None:
            self.send_error(404, f"no action {name}")
            return
        self._answer(lambda session: {"notice": action(session, body)})

    def _command(self, line: str) -> None:
        """One command line the page routed here. Which rows this
        frontend answers, and what each returns, is `api.answering`'s —
        resolved before anything queues, so a line no row matches is
        answered from this thread: with the shared unknown-command
        sentence (`backend.commands.unknown_notice`), as the refusal it is —
        the page shows it verbatim, exactly as the terminal does."""
        call = api.answering(line)
        if call is None:
            self._json({"notice": commands.unknown_notice(line), "refused": True})
            return
        self._answer(call)

    # ---------- who is asking ----------

    def _from_this_machine(self) -> bool:
        """Whether the request came to an address this server answers to.

        The reader's own browser sends the address they typed; a page
        that got here by pointing its own hostname at 127.0.0.1 — DNS
        rebinding, the one attack a loopback bind does not stop — sends
        that hostname instead. Checking it costs nothing and is the only
        thing standing between a story library and any tab in the
        browser. A request with no Host at all is HTTP/1.0 or a script:
        allowed, because neither is a page."""
        answers_to = self.server.answers_to
        host = self.headers.get("Host", "")
        if not answers_to or not host or _named(host) in answers_to:
            return True
        self.send_error(421, "Misdirected Request")
        return False

    def _from_our_page(self) -> bool:
        """Whether a WRITE came from otaku's own page.

        A cross-origin form can POST here without a preflight, and a
        write needs no answer to do its damage: repointing a provider at
        an attacker sends the reader's api key with the next turn. So a
        write must prove where it came from — `Sec-Fetch-Site:
        same-origin`, which no page can forge, or an `Origin` that is
        exactly the one this request was addressed to.

        The Origin arm carries the weight, because fetch metadata is
        only sent for a TRUSTWORTHY url: `http://localhost` is one,
        `http://192.168.1.5:9600` is not — and that is the very
        configuration where another app, one port over on the same host,
        can reach this port. So the whole origin is compared, scheme and
        port included.

        A request with neither header is not a browser (curl, a script
        on this machine); the bind is what guards those."""
        site = self.headers.get("Sec-Fetch-Site")
        if site in ("same-origin", "none"):
            return True
        origin = self.headers.get("Origin")
        if site is None and origin is None:
            return True
        addressed = self.headers.get("Host", "")
        if origin in (f"http://{addressed}", f"https://{addressed}"):
            return True
        self.send_error(403, "Cross-origin request")
        return False

    # ---------- what the terminal is told ----------

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """One line per request the reader ASKED for — a page load's
        twenty assets are not news, so they are dropped here rather than
        drawn and scrolled away."""
        if self._path() in _QUIET:
            return
        self.server.hooks.show(f"{self._asked()} {getattr(code, 'value', code)}")

    def log_error(self, format: str, *args: Any) -> None:
        """What the stdlib reports without ever sending a status: a
        request line too broken to parse, a connection that timed out
        mid-request. Everything else it reports here — `send_error`'s
        own "code %d, message %s" — is already on its way through
        `log_request`, and saying it twice would read as two requests."""
        if args and isinstance(args[0], int):
            return
        self.server.hooks.show(f"{self._asked()} {format % args}")

    def log_message(self, format: str, *args: Any) -> None:
        """Silence. Both of the base class's callers are answered above;
        this is the sink for anything that finds a third way here."""

    def _path(self) -> str:
        """What was asked for, without the query. Read defensively: a
        request line malformed enough to be refused before it is parsed
        never set one."""
        return str(getattr(self, "path", "")).split("?", 1)[0]

    def _asked(self) -> str:
        """The request as one phrase, for the line the terminal shows —
        or "?" for a request line that never parsed into either half.
        The raw line is deliberately NOT shown: it is bytes off a
        socket, and this ends up in a terminal."""
        return f"{self.command} {self._path()}".strip() if self.command else "?"

    # ---------- answering ----------

    def _answer(self, produce: Callable[[Session], object], *, reading: bool = False) -> None:
        """Run on the session's thread and reply with what came back.
        `reading` declares that `produce` only READS the session — it is
        what lets the job run between the frames of a reply, and every
        screen in the app is one of those. A Refused is an ANSWER —
        "Nothing to export yet" is the sentence to show — so it comes
        back 200 as a notice, marked so the page never has to read the
        wording; only a bug is a 500, and its traceback goes where the
        reader is."""
        try:
            payload = self.server.runner.run(produce, reading=reading)
        except StoppingError:
            # The reader stopped otaku while this was in the queue. An
            # ordinary end, not a fault: no traceback, nothing recorded.
            self.send_error(503, "otaku is stopping")
        except Refused as e:
            self._json({"notice": str(e), "refused": True})
        except (KeyError, ValueError) as e:
            # A field the page did not send, or one it sent wrong: a
            # malformed request wherever it came from.
            self.send_error(400, f"{type(e).__name__}: {e}")
        except Exception as e:
            self.server.crashed(f"web {self.command} {self._path()}", e)
            self.send_error(500, f"{type(e).__name__}: {e}")
        else:
            self._json(payload)

    # ---------- the reply stream ----------

    def _play(self, line: str, *, regenerate: bool = False) -> None:
        """One story line, its reply streamed as it arrives — or a fresh
        take on the standing one, which streams the same way.

        The whole turn is ONE job on the session's thread: the line is
        recorded and its reply streamed without the thread going free in
        between, so nothing — another tab landing a story, a `/new` — can
        move the story out from under a line already accepted. The
        handler thread only waits, so the two never write at once. A
        browser that goes away breaks the write, which closes the
        generator: the backend's cancel-and-keep, reached by the same
        door Ctrl+C uses in the terminal."""
        produce = api.regenerate if regenerate else (lambda session: api.play(session, line))
        self._streaming = False
        try:
            self.server.runner.run(lambda session: self._pump(produce(session), session))
        except StoppingError:
            self.send_error(503, "otaku is stopping")
        except Refused as e:
            # Checked before it plays, so this arrives before a byte of
            # the stream: invalid syntax leaves the story untouched, and
            # the usage line is the whole answer.
            self._json({"notice": str(e), "refused": True})
        except Exception as e:
            # Every other POST reaches this through `_answer`; this one
            # cannot, because its answer is a stream. Once a frame has
            # gone out there is no status left to send — the page reads
            # the short stream as a finished reply — so the log is the
            # only place left to say what happened.
            self.server.crashed(f"web {self.command} {self._path()}", e)
            if not self._streaming:
                self.send_error(500, f"{type(e).__name__}: {e}")

    def _pump(self, events: Iterator[PlayEvent], session: Session) -> None:
        """Write the stream out, on the session's thread. Whatever ends
        it — the last event, a closed tab, a failure — the generator is
        closed, which is what records a partial reply."""
        self._streaming = True
        self.send_response(200)
        self.send_header("Content-Type", _EVENT_STREAM)
        self.send_header("Cache-Control", _NO_STORE)
        # A stream has no length to declare, so the close IS the end of
        # it: on a keep-alive connection the reader would sit waiting for
        # a next turn that never comes, and the reply would never look
        # finished.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            for happened in events:
                # Asked to stop: leaving the loop closes the generator
                # below, which is the backend's cancel-and-keep door —
                # the same one a vanished browser goes through.
                if self.server.stopping.is_set():
                    return
                self._frame(json.dumps(api.event(happened)))
                # A reply is the longest job there is, and it owns the
                # session's thread for all of it. Between two frames is
                # where the reads waiting on that thread get answered —
                # a rail button pressed mid-reply opens its screen now,
                # not when the model stops.
                self.server.runner.drain()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            events.close()  # type: ignore[attr-defined]
        # The turn ran to its natural end and the reader has the whole
        # reply — the moment the screen wants them back. Not on a Stop or
        # a closed tab (the returns above): whoever cut it either acted
        # or left — the terminal's own "not after a Ctrl+C" rule.
        if session.notification:
            self.server.hooks.ring()

    # ---------- the watch stream ----------

    def _watch_stream(self) -> None:
        """Name each file the page is made of as it changes, for as long
        as the tab is open — the page reloads itself on the name, or
        swaps its stylesheets when the name is one.

        Held open by design, which is why the retry is sent first: a
        server that goes away gets the browser back at the interval this
        names rather than at its own, and the reopened stream is how the
        page finds out that a restarted otaku is serving a different
        build."""
        self.send_response(200)
        self.send_header("Content-Type", _EVENT_STREAM)
        self.send_header("Cache-Control", _NO_STORE)
        # Framed like the reply stream, and for the same reason: no
        # length to declare, so the close is the end of it.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self._frame(None, retry=_RETRY_MS)
        try:
            for name in _changes(_STATIC_PATH, self.server.custom_web_dir):
                self._frame(name)
        except (BrokenPipeError, ConnectionResetError):
            return

    # ---------- what goes on the wire ----------

    @staticmethod
    def _asset(name: str) -> bytes:
        """One packaged file, read now — which is why editing it needs no
        restart. The name comes from the table, never from the request."""
        target = _STATIC
        for part in name.split("/"):
            target = target / part
        return target.read_bytes()

    def _custom_css(self) -> bytes:
        """The reader's own stylesheet, or nothing. Absent is the normal
        case, so it answers with an empty stylesheet rather than a 404 —
        a red line in the console is not a state to design for."""
        try:
            return (self.server.custom_web_dir / "custom.css").read_bytes()
        except OSError:
            return b""

    def _query(self) -> dict[str, str]:
        """The request's query, one value per name — a read's argument
        is a value, never a list."""
        parsed = parse_qs(urlsplit(self.path).query)
        return {name: values[0] for name, values in parsed.items() if values}

    def _body(self) -> dict[str, Any]:
        """The request's JSON object, or an empty one — a malformed body
        is a missing field, which every caller already handles. That
        includes a malformed LENGTH: anything that scans this port can
        send one, and a crash here would answer nothing and file a
        traceback in the day's error log for something that is not a
        bug."""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            parsed = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _json(self, payload: object) -> None:
        self._send(json.dumps(payload).encode(), _JSON, _NO_STORE)

    def _frame(self, data: str | None, *, retry: int | None = None) -> None:
        """One server-sent event, flushed — a stream nobody flushes is a
        stream nobody sees."""
        head = f"retry: {retry}\n" if retry is not None else ""
        body = f"data: {data}\n" if data is not None else ""
        self.wfile.write(f"{head}{body}\n".encode())
        self.wfile.flush()

    def _send(self, body: bytes, content_type: str, cache: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)


def _named(host: str) -> str:
    """The name half of a Host header — the port dropped, brackets off.
    `[::1]:9600` and a bare `[::1]` are the same machine."""
    name = host.rsplit(":", 1)[0] if ":" in host.rsplit("]", 1)[-1] else host
    return name.strip("[]")


# ---------- the watch poller ----------


def _changes(*watched: Path) -> Iterator[str]:
    """Each file of the page's that changed, forever — written, added or
    removed. A deletion counts: the browser would otherwise keep running
    a script that is no longer there.

    Polled rather than watched, because a dependency on a file watcher
    buys nothing here: a browser reload is slower than the interval, and
    the two directories hold about thirty files between them."""
    seen = _stamps(watched)
    while True:
        time.sleep(_WATCH_INTERVAL)
        now = _stamps(watched)
        for path in now.keys() | seen.keys():
            if now.get(path) != seen.get(path):
                # The NAME, not where it lives: all the page does with it
                # is tell a stylesheet from everything else, and a
                # server's own paths are nothing to hand a browser.
                yield path.name
        seen = now


def _stamps(watched: tuple[Path, ...]) -> dict[Path, float]:
    """Every file under the watched directories and when it was written.
    A file that goes away between the listing and the stat is simply
    absent from this one — an editor saving atomically does exactly
    that, and it must not take the stream down with it. So is a whole
    directory that is not there: the reader's own is absent until they
    make it."""
    stamps: dict[Path, float] = {}
    for directory in watched:
        with contextlib.suppress(OSError):
            for path in directory.rglob("*"):
                with contextlib.suppress(OSError):
                    if path.is_file():
                        stamps[path] = path.stat().st_mtime
    return stamps
