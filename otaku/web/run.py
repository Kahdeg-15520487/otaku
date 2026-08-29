"""The web frontend's life — everything `otaku web` is, above HTTP.

`run` is the whole of it over an open session, as `chat.run` is the
terminal's: what the launch has to say, where the page is, and the tail
of requests until the reader stops it. Everything `otaku web` prints is
printed HERE, into the terminal it was launched from — `web.server`
below prints nothing and is handed one line per request worth showing.

`serve` is the composition root under `run`: the thread that owns the
session's thread, the state that spans requests, the hooks the server
answers the beat from, and the signal that makes Ctrl+C an orderly stop
are all wired here — so `server` stays HTTP and `thread` stays a queue.

`settings` is where this frontend listens: the session's own `[web]`
slice, with the development port override laid over it. The address is
the medium, like a key binding or a column width — so a frontend reads
one slice and only its own, and gets it the way the terminal gets its
looks, off the session rather than out of the file.
"""

import contextlib
import os
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from otaku import __version__
from otaku.backend import WebSettings
from otaku.backend.session import Session
from otaku.console import banner, sound, ticker
from otaku.web import api
from otaku.web.server import LOOPBACK, Hooks, bind
from otaku.web.thread import SessionRunner

__all__ = ["ServeError", "address", "run", "serve", "settings"]

# For working ON otaku, and deliberately unadvertised (`settings`).
# There is no host variable to match — which interface a server answers
# on is a decision, and a decision belongs in the file.
_PORT_VAR = "OTAKU_WEB_PORT"


class ServeError(Exception):
    """The address in the config cannot be listened on — a port another
    program already holds, a host this machine does not answer to, a
    privileged port. Raised instead of the socket's own OSError so the
    caller has a sentence to print rather than a traceback to dump."""


def run(
    session: Session, *, full: bool = True, host: str | None = None, port: int | None = None
) -> None:
    """This frontend's whole life over an open session, as `chat.run` is
    the terminal's: what the launch has to say, where the page is, and
    the tail of requests until the reader stops it. Everything printed
    by `otaku web` is printed here — into the terminal it was launched
    from, which is the only part of that terminal this frontend has.
    Closing the session stays the caller's, as it is for the other
    frontend.

    FULL is a terminal this frontend opens: `otaku web`, with the launch
    to report and a mark to draw. Without it the session came from
    `/web`, into a chat already in progress — the reports were read when
    it opened and the mark drawn then, so all this owes the reader is the
    address.

    `host` and `port` are a caller overriding where it listens for this
    run — the command line's own, laid over the configured address."""
    config = settings(session.web, host=host, port=port)
    if full:
        # The launch's own reports have nowhere to go in a browser that
        # is not open yet, so they go where the reader is: the terminal
        # they typed in. A chat handing its session over has none left —
        # it printed them when it opened.
        for report in session.notices:
            print(report)
        session.notices.clear()
    # Said before the socket is bound, because the address is the
    # configuration's and not the socket's answer: a reader can be
    # opening the page while the first request is still arriving. The
    # banner is the same mark a chat session opens with and answers to
    # the same setting; without it, one line saying the same things.
    url = address(config)
    if session.terminal.show_banner:
        print(banner.render_web(__version__, url, full=full))
    else:
        print(f"web ui is available on: {url}  (ctrl+c to stop)")
    # The last few requests, kept under the address and rewritten in
    # place: proof that the browser is reaching this server, in a
    # terminal that stays the height it started at. It owns the terminal
    # while it runs — Ctrl+C is answered here, so the tty must not also
    # echo `^C` into the middle of the answer.
    with ticker.Ticker() as tail:

        def stopping() -> None:
            """The first Ctrl+C, in words — the last line of the log,
            said in the log's own voice because that is what the reader
            is already reading. Shown BEFORE the tail stops, which is the
            only order that works: a stopped tail draws nothing, and a
            line drawn as a row is one a later redraw keeps rather than
            takes back. Then the tail stops, and with it the terminal
            gets its own behaviour back — the NEXT press is the fatal one
            and would otherwise leave it without. The sentence is the
            truth: a reply already in flight is finished, not cut."""
            tail.show("Shutting down…")
            tail.stop()

        serve(
            session,
            config,
            session.custom_web_dir,
            show=tail.show,
            stopping=stopping,
        )
    if full:
        # The shell prompt starts against a blank rather than against the
        # last request. A chat taking its session back needs none from
        # here: the blank before its next prompt is its ledger's, and one
        # printed here as well would be two.
        print()


def settings(
    config: WebSettings, *, host: str | None = None, port: int | None = None
) -> WebSettings:
    """Where this frontend listens: the session's own `[web]` slice, with
    what outranks it laid over. The slice arrives from the session as the
    terminal's looks do — a frontend reads one slice and only its own,
    and neither reads the file for itself.

    Three answers, in the order they win. The FILE is the standing one, a
    decision made once and kept. `OTAKU_WEB_PORT` moves a development
    server off it so a real otaku can keep the port — unadvertised, and
    applied here rather than in `cli` because which port this frontend
    listens on is its own business wherever the answer comes from. An
    explicit `host` or `port` beats both: it was typed for this run, by
    somebody who is watching it."""
    wanted = os.environ.get(_PORT_VAR, "").strip()
    if wanted:
        if wanted.isdigit() and 1 <= int(wanted) <= 65535:
            config = replace(config, port=int(wanted))
        else:
            print(f"otaku: ignoring {_PORT_VAR}={wanted!r} — not a port number", file=sys.stderr)
    if host is not None:
        config = replace(config, host=host)
    if port is not None:
        config = replace(config, port=port)
    return config


def address(config: WebSettings) -> str:
    """The URL that address READS as — what the terminal prints and a
    reader pastes.

    A NAME, not a number: every loopback spelling reaches this server,
    and `localhost` is the one a person reads and a browser bar shows
    back. An address that names a real interface stays as it was
    configured; that one was a decision. Port 80 is what a bare `http://`
    already means, so printing it is printing the default twice, and
    there is no trailing slash: the root is where a bare host goes, and
    a slash is one more character between a reader and a working
    paste."""
    reachable = "localhost" if config.host in LOOPBACK else config.host
    return f"http://{reachable}" if config.port == 80 else f"http://{reachable}:{config.port}"


def serve(
    session: Session,
    config: WebSettings,
    custom_web_dir: Path,
    *,
    show: Callable[[str], None] | None = None,
    stopping: Callable[[], None] | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Serve one open session until interrupted — the composition root
    under `run`, the background worker started here for the same reason
    `chat.run` starts it. `config` is the configured address (`settings`
    above); `custom_web_dir` is the state dir's own web directory, where
    the reader's `custom.css` lives and nothing else is ever read from.
    Closing the session stays the caller's, like every other frontend's.

    Nothing here is printed. `show` is handed one line per request worth
    showing and `stopping` the moment the reader asks for the door —
    where either APPEARS is the caller's, because this package draws
    nothing in a terminal.

    `stop` is how a caller that is not a terminal ends the serving: set
    it and this returns, the same way Ctrl+C does. Ctrl+C itself is only
    wired when this runs on the main thread, because that is the only
    thread a signal handler can be installed from."""
    session.start_worker()
    runner = SessionRunner(session)
    # The session's one thread is this frontend's too. Between frames a
    # reply gives it back (the server's pump drains), and while a reply
    # is only being WAITED for — the long silence before the first token
    # above all — the backend hands it over here. Either way it spends
    # the time answering reads, which is why a screen opens mid-reply.
    session.set_on_idle(runner.drain)
    # What the background worker says while nobody asked it anything —
    # the idle extraction pass above all. The terminal pins its status
    # row and prints its sentences in the flow; the page has neither
    # until it asks, so the sentences wait in the mailbox and go out on
    # the heartbeat it is already making.
    sayings = _Sayings()
    session.set_on_notice(sayings.put)
    try:
        server = bind(
            config,
            runner,
            api.Pending(),
            custom_web_dir,
            Hooks(
                show=show or (lambda line: None),
                # A contained crash goes where every frontend's contained
                # crashes go. Called off the session's thread by design:
                # it appends to a day-file and never reaches the store,
                # and a handler that queued for the session's thread to
                # report a crash would wait behind the very job that
                # crashed.
                record=session.record_crash,
                working=session.status,
                sayings=sayings.drain,
                # A landed reply rings the terminal this server was
                # launched from — one user, one desk: the browser and
                # this shell sit in front of the same reader, and the
                # sound machinery is the one the chat already rings.
                ring=lambda: sound.ring(session.terminal.notification_sound),
            ),
        )
    except OSError as e:
        # The address is configuration, and configuration that cannot be
        # honoured is answered with a sentence, not a stack.
        raise ServeError(f"cannot serve at {config.host}:{config.port} — {e.strerror or e}") from e
    if stop is not None:
        server.stopping = stop
    # Serving moves to a thread so that THIS one — the thread that opened
    # the session, and the only one its sqlite connection will answer —
    # stays free to run the work the handlers hand it.
    # The signal handler is installed BEFORE the serving thread and
    # inside the try, so no signal can land in a window where shutdown
    # would be skipped. Only the main thread may install one at all; a
    # caller serving from another has `stop` instead.
    on_main = threading.current_thread() is threading.main_thread()
    was = (
        signal.signal(signal.SIGINT, _interrupting(server.stopping, stopping)) if on_main else None
    )
    try:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        runner.loop(server.stopping)
    except KeyboardInterrupt:
        pass  # the second one: asked twice, so stop now
    finally:
        if was is not None:
            signal.signal(signal.SIGINT, was)
        server.shutdown()
        server.server_close()
        # Whoever was waiting on the session's thread is told there is no
        # answer coming, rather than waiting for one forever.
        runner.abandon()


class _Sayings:
    """The background worker's sentences, held for the beat: `put` is
    called from the WORKER's thread the moment a pass has something to
    say, `drain` from a handler's when the page next asks — so the two
    never meet inside the list."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def put(self, sentence: str) -> None:
        with self._lock:
            self._lines.append(sentence)

    def drain(self) -> list[str]:
        with self._lock:
            said, self._lines[:] = list(self._lines), []
        return said


def _interrupting(stop: threading.Event, said: Callable[[], None] | None) -> Callable[..., None]:
    """The first Ctrl+C, and what it says. The handler gives the signal
    back to Python before setting the flag, so a reader who presses it
    again is answered at once rather than waiting on a stream that may
    not yield for minutes. `said` is the caller's — this package has no
    terminal — and a hook may not be what stops a shutdown."""

    def interrupt(*_: Any) -> None:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        stop.set()
        if said is not None:
            with contextlib.suppress(Exception):
                said()

    return interrupt
