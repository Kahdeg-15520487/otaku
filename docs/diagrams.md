# otaku in pictures

Two drawings of the same program at two scales: the packages and how
they depend on each other, and the inside of `web`, where one thread and
three secrets need a picture more than the rest of the code does.

The RULES live in CLAUDE.md — the import table above all, which
`tests/test_architecture.py` holds. What is here is only the shape of
them.

## The packages

This mirrors the import table in CLAUDE.md, Architecture — the layers.
It carries both graphs at once, dependency and control flow, because
they point the same way everywhere: no upward import, and no import that
is not exercised by a call in its own direction. If the two ever
disagree, the table is right and this drawing is stale.

Legend: a solid arrow between packages = imports AND calls; arrows from
the margin = stimuli (user, browser, idle), not imports; the captions
under the graph state the edges ASCII cannot draw cleanly.

    cli ─┬─► terminal ─────────┐        cli also: ─► logging (viewing) · ─► update
         └─► web (◄─ browser) ─┤                  ─► backend (launch + unlock
             both ─► console   ▼                     for the sealed request log)
            ┌─────────────────────┐    schedules    ┌──────────────────────┐
            │       backend       │ ──────────────► │        worker        │ ◄── idle deadline
            │  Session · transfer │                 │ extraction · warm-up │
            └──┬──┬──┬──┬──┬──┬───┘                 └──┬────┬────┬────┬────┘
               │  │  │  │  │  │                        │    │    │    │
               │  │  │  │  │  └► settings              │    │    │    │
               │  │  │  │  └───► encryption (unlock)   │    │    │    │
               │  │  │  └──────► logging ◄─────────────┘    │    │    │
               │  │  └─────────► providers ◄────────────────┘    │    │
               │  └────────────► context ◄───────────────────────┘    │
               │                   │ reads                            │
               └────────────────► store ◄─────────────────────────────┘

    sealing: store · logging ─► encryption — the DATA plane (one session cipher
             for the database and the request log, BY DESIGN); backend ─► encryption
             covers both planes (data unlock + the api-key plane); keys are wired
             only in backend.launch
    formatting: stdlib-like leaf — anyone above may use it (its arrows are not drawn);
             providers ─► settings (ProviderConfig and the sections live there)
    dashed, injected at composition (no import): worker status ─► frontend repaint ·
             ask_secret ─► frontend
    web ─► settings: the [web] slice alone — where a frontend LISTENS is the
             medium, like a key binding, and it is needed before a session exists
    console: what a frontend draws in the terminal it was LAUNCHED from — the
             banner both open with, the tail under the web's. Below both
             frontends because neither may own what the other prints, and a
             leaf because it is HANDED what it draws

## Inside `web`

Four modules and three secrets: `thread` (WHEN work runs), `api` (WHAT
may be asked, as data), `server` (HOW it arrives) — with `run` above all
three, owning the frontend's life and the terminal it prints into.

                        cli ──► web/__init__ ──► run          (re-exports: run, serve,
                                                               settings, address, ServeError)

      user's terminal                                          browser
            │                                                     │
            │ banner · tail · ctrl+c                              │ HTTP
            ▼                                                     ▼
      ┌───────────────────┐   binds, hands Hooks   ┌──────────────────────────────┐
      │       run         │ ─────────────────────► │           server             │
      │ the frontend's    │                        │  bind · _Server · _Handler   │
      │ life; the ONLY    │ ◄───────────────────── │  routes, guards, framing     │
      │ module that       │   Hooks: show · record │                              │
      │ prints            │   working · sayings    └───┬──────────────────────┬───┘
      └────┬─────────┬────┘   ring (injected, no       │ run(work,            │ ROUTES/FLOWS
           │         │        import — see below)      │ reading=…)           │ Ask · Created
           │         │                                 │ drain()              │ play · event
           │         └─────────────────────────────────┤                      │
           │  SessionRunner(session)                   ▼                      ▼
           │  .loop(stopping) · .abandon()   ┌──────────────────┐   ┌──────────────────┐
           └────────────────────────────────►│      thread      │   │       api        │
                                             │ ONE thread owns  │   │ what the page    │
           api.Pending() ────────────────────┼─ the session;    │   │ may ask, as data │
           (built in run, held by server,    │ two queues       │   │                  │
            handed to FLOWS)                 └────────┬─────────┘   └────────┬─────────┘
                                                      │ hands the session    │
                                                      ▼ to the work          ▼
                                                ┌───────────────────────────────┐
                                                │           backend             │
                                                └───────────────────────────────┘

      run also ─► console (banner, sound, ticker) · settings.config · backend.paths
      api  ─► backend.api.* only — no HTTP, no threads, nothing above it

Three edges are calls WITHOUT imports, which is why the cycle cannot be
seen from the import list alone:

- **`Hooks`** — `run.serve` builds five lambdas (`show`, `record`,
  `working`, `sayings`, `ring`) and hands them to `bind`. The server
  calls them and never imports `run`.
- **`session.set_on_idle(runner.drain)`** — the SESSION calls the thread
  back while a reply is only being waited for. Neither knows the other's
  module.
- **`runner.run(produce)`** where `produce` closes over `api.*` — the
  api runs inside the thread's loop without either importing the other.

And the import chain that settles whether `thread` could be folded into
`run`: `run → server → thread`, plus `run → thread` directly. Fold it and
`server → thread` becomes `server → run`, while `run → server` already
exists — a cycle. It is not accidental: the thread that owns the session
sits BELOW HTTP because HTTP hands work down to it, and the frontend's
life sits ABOVE because it binds the server and prints about it.

### When the thread is called

Five moments, and the middle three are the whole reason the page stays
answerable while the model is talking.

1. **It becomes the main thread, once.** `run.serve` builds it, then
   gives the main thread to `SessionRunner.loop` and puts HTTP on a
   daemon thread beside it. The signal handler goes there too — it is
   the only thread that can take one.
2. **Every API request, from a handler thread.** `server._answer` calls
   `runner.run(produce, reading=<method is GET>)` and blocks until the
   loop picks the job up. `reading` chooses which of the two queues it
   joins, and that is the whole of the lane rule.
3. **Every play, as one long job.** `server._play` runs the entire
   streaming reply — headers, every frame, the final ring — inside one
   job on the session's thread.
4. **Draining, from three directions, all on the session's own thread.**
   The loop between jobs; `server._pump` after every frame; and
   `session.set_on_idle` during the wait for a first token. Reads are
   answered in each of those gaps, which is why no lock appears anywhere
   in `thread.py`.
5. **Shutdown.** `runner.abandon()` answers every job still queued, and
   every one still to come, with `StoppingError` — including the handler
   of a keep-alive connection that outlives the serving.
