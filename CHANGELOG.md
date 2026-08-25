# Changelog

All notable changes to otaku are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and otaku follows
[Semantic Versioning](https://semver.org/) — while pre-1.0, minor releases may include breaking
changes.

## [0.4.0] - [planned]

**TL;DR**

- otaku is restructured around a frontend-agnostic core: same app, same commands, same data — but
  the story machinery no longer belongs to the terminal.
- `otaku web` opens the same session in a browser: the second frontend, over the same stories, the
  same lore and the same commands.

**Full version:**

### Added
- `otaku web` — a web interface for the otaku on this machine. It serves one open session at the
  address `configs/config.toml`'s new `[web]` section names (loopback and port 9600 by default, so
  reaching it from another machine is an edit somebody made on purpose), and everything the
  terminal does is there: the story plays in a transcript, replies stream, and every command is
  both a button in the rail and a line you can type. The browsers — stories and their messages,
  lore and cast, the model picker with its providers, the settings knobs — are the same screens in
  a page's medium, and the reports keep their shapes: the context window as a diagram, usage as a
  table, the session as a definition list. The command line is asked for and answered by the same
  shared table both frontends read, so a command exists once.

  It is a single-reader, local page by design: nothing it is made of is cached and nothing is a
  build step, so a file that changes on disk changes what the browser has — the page replaces
  itself when one does, and a stylesheet is swapped without losing your place. The reader's own
  `web/custom.css` in the state dir is loaded last, against a token contract documented in
  `docs/web_tokens.md`. While a
  reply is streaming the page stays answerable — screens open, lists load — because reads are
  served in the gaps of the reply rather than queued behind it.

  It listens on loopback and answers only requests addressed to this machine, and a write must
  come from otaku's own page: a page on another site cannot drive your otaku from the browser you
  left it open in.
- `/set notification on|off` — off by default — plays a sound when a reply lands, for when you look
  away mid-generation. Which sound is `configs/config.toml`'s `notification_sound`: `"default"` is
  the platform's own (macOS's Glass, the freedesktop theme's on Linux), or name a file of your own.
  A machine with no player, or a path that isn't there, rings the terminal bell instead — and what
  a bell means is your terminal's business, which is where a notification belongs.

### Changed
- The codebase is restructured around a frontend-agnostic core. Everything that is not the
  terminal — the session, the story and lore operations, the import and export formats, the
  command surface — lives in a backend package that a frontend calls, and the terminal owns only
  the medium: what a message looks like, what a key does, what the screen holds. The layout is
  held by a test, so an import that would cross a layer fails the suite rather than the review.
  Nothing about running otaku changes: the same commands, the same state dir, the same database.
- `/balance` names each provider the way the model picker does — "OpenRouter", not the `openrouter`
  section key. A section you named yourself keeps your name, with the engine in brackets, because
  two sections of one kind are two accounts and a balance report has to tell them apart.
- Long story titles are cut at 50 characters instead of 40 — in the banner and in the line that
  names the story when it lands — with a fork's number kept whole, as before.
- Launching with a remembered model whose provider is no longer configured says so before the
  picker opens, instead of opening it without a word.
- The api key's sealing key tightens `configs/` to owner-only when it is created, as the database's
  key already did.
- One dependency fewer to install: the model picker's RAM gauge reads the machine's own numbers —
  sysconf, `/proc/meminfo` on Linux, `vm_stat` on macOS — where it used to read psutil. On macOS it
  now agrees with Activity Monitor instead of reading gigabytes rosier: app memory that has gone
  cold still counts as used, because reclaiming it means compressing or swapping it first. The
  Linux figure is unchanged — the kernel's `MemAvailable` already drew the line there.
- Requests to OpenRouter now name otaku as the app that sent them.
- `/new` takes an optional TITLE — `/new The Long Road` names the story as it starts — and creates
  the story at once, so it is in `/stories` with its name before its first turn, where before it
  appeared only once you had played one.
- `/help` fits the screen: two columns on a wide terminal, one on a narrow one, and a description
  that wraps in its own column instead of running off the edge. The command column is spelled
  shorter here than the reference is — `/set verbose` rather than `/set verbose on|off`, `/model
  [SPEC]` with PROVIDER/MODEL moved into the description — and what a command takes is still shown
  in full by the menu as you type it.
- `/export NAME` adds `.md` when the name carries no extension of its own, since the document is
  Markdown — `/export glade` writes `glade.md`. A name with an extension keeps it.
- Enter on a menu row that takes a parameter completes the command and waits, whether the
  parameter is required or optional — before, a command whose parameter was optional ran on the
  spot, and there was no way to pick `/fork` from the menu and then name the fork. Enter sends it
  bare from there, so a command that takes nothing still runs in one press.
- The banner reads in the order a session is thought about: the story first, then the model, then
  the engine and its context window. The mark, the version and the description are unchanged, and
  `otaku web` opens with the same banner — its three lines being the address, how to open it, and
  how to stop serving.
- The mascot beside the banner is redrawn. Without colour it is now the same picture rather than a
  different one: the sprite is cut into ink and paper instead of falling back to an ASCII face, so
  a piped or `NO_COLOR` session gets the mark at the same size, in the same place.

### Fixed
- A sealing key that cannot be read no longer ends the launch with a traceback: the provider it
  belongs to runs without its key and the launch says which one.
- The prompt warm-up after a scene closes now runs for local engines only. It exists to prefill a
  local server's cache so the next reply starts fast; on a cloud provider the same request has no
  cache to warm and was billed as a full context window for one token.

## [0.3.0] - 2026-08-17

**TL;DR**

- New feature: character card import with the `/card` command.
- Commands `/me` and `/you` suggest and autocorrect cast names.
- New commands available mid-prompt only: `/ooc` and `/cue`, both hinting the LLM — `/ooc`
  introduces a standing note, `/cue` a one-time steer that the LLM won't see later.
- The browsers (`/stories`, `/lore`, `/model`) follow the terminal theme.
- Commands get highlighted.

**Full version:**

### Added
- `/card FILE [NAME]` — import a character card (SillyTavern formats, PNG or JSON) into the
  current story. The card becomes a prompt: its fields compose through the `card_framing`
  template into one out-of-character block that rides every request verbatim — never summarized,
  never evicted — and the character speaks the card's own greeting. The cast row archives the
  card's fields as TOML, editable in `/lore`, and the wire follows the archive: the block
  composes from it at request time, so a correction reaches every later request. The archive
  rides `/export` too, so a re-imported story keeps the living card. `{{char}}` and
  `{{user}}` are recorded at import (the import asks who you play, and the story remembers the
  answer) and bind at wire time; a card's lorebook is not supported and is dropped with a note.
- The database migrates itself between schema versions: a backup is taken first, each step is
  transactional (a failure leaves the database unharmed at its version, the backup untouched),
  and a database written by a newer otaku is refused with directions instead of being guessed at.
- `/set autocorrect on|off` — whether a typed character name in `/me` and `/you` commands is
  settled to the cast's spelling.
- Two inline commands, typed inside a line rather than opening one: `/ooc` for an aside out of
  character, and `/cue` to steer just the next reply — a cue goes out with the turn it rode in on
  and is not kept in context afterwards.
- `/you NAME: HINT` — an optional hint after the name, a standing direction for how to play them,
  sent as its own `((OOC: …))` aside beside the play-as instruction whenever the turn goes out;
  `/cue` stays the one-shot form. A `you_framing` template carrying a `{body}` slot takes the hint
  into its own wording instead.
- The menu offers the story's cast where a command takes a character — each row with the
  character's description: `/me` completes `Name:` and waits for the prompt, `/you` completes the
  bare name, and `/merge` completes both sides of `A into B`.
- Commands are colored wherever they appear: while you type one, in the played block once it is
  sent, and in the story browser's rows and preview. Only real commands light up, so a slash in
  ordinary prose (`and/or`, a URL) stays prose. The completion menu marks the selected row in the
  same color, so a row reads as what it will become once inserted.

### Changed
- The extraction writes a journal for every character present in a scene — speaking, acting, or
  silently there — and entries name arrivals and departures as they happen: a journal row is now
  the story's record of presence. The refreshed template reaches existing installs too: a
  `prompts.toml` template still holding a previous release's exact text follows the new built-in,
  while an edited one is never touched.
- The lore browser's cast lists in order of appearance — the story's own order — instead of
  alphabetically.
- The system log records the app's administrative moments — the schema migration, the daily
  database backup, `otaku update` runs — besides the lore worker's actions.
- The browsers (`/stories`, `/lore`, `/model`) follow the terminal instead of painting over it:
  the pane, its text and its headings are your own colors, secondary text is dimmed rather than
  greyed, and only what has to be painted is — the selected row and a dialog floating over the
  list. They also come in a dark set now, where before every browser was light whatever the
  terminal looked like.
- Failures print in red: a provider that refused, a file that would not open, a command that
  raised. What the app merely declines to do ("Unknown command", "Nothing to regenerate") stays
  plain — an ordinary typo should not read as a fault.
- An export document declaring a newer format version than this app reads is refused with
  directions — the way a database written by a newer otaku is — instead of being parsed by
  guesswork; every older format still imports.

### Fixed
- A long `/system` premise no longer fails: deciding whether the argument named a file asked the
  filesystem a question it refuses over 255 characters, so any premise worth writing crashed the
  command instead of being stored. `/card` and `/export` asked the same question the same way.
- A command can open a multiline block — `/system """` and the lines that follow, closed with
  `"""` — where before the delimiters were stored as part of the text.
- Rewinding past a closed scene's end — a deep undo, or resuming a story from an earlier
  message — no longer kills every later extraction with a constraint failure: the abandoned
  scene stays in the tree, and the new branch closes its own scene starting at the same message.
  When a pass does crash, the failure line now names the real cause instead of blaming the
  model's reply.
- A provider edit that could not be written to `providers.toml` — a hand-broken file, a
  disk error — now says so in the panel instead of confirming a change the next launch would
  silently forget; a key that could not be forgotten on disk stays in the session too, so the
  mark never lies.
- Typed `/undo` and `/regen` erase the whole exchange again: the cursor-position query was
  triggering the blank line that separates a command's output from its typed line, quietly moving
  the cursor one row down right before the erase measured from it — so the first line of what
  should vanish stayed on screen. The shortcuts, which erase the typed line first, never armed
  that blank, which is why they were immune (#6).
- The story browser's delete now answers the key macOS captions "delete" (backspace) as well as
  the PC Del / forward-delete key it always listened for. While a filter is open, backspace still
  edits the filter.
- A line opening with `- ` reads as dash-convention dialogue — colored, the hyphen kept — where it
  used to become a `•` list bullet, which rewrote the spoken line's own mark and left it uncolored.
  Lists keep `*` and `+`.

## [0.2.2] - 2026-08-08

**TL;DR**

- New providers: OpenRouter and NanoGPT (cloud), llama.cpp and LM Studio (local); the prompt for
  cloud providers is `$` instead of `>`.
- Numerous UI improvements, including:
  - dialogue coloring;
  - undo erases the taken-back exchange from the screen;
  - regenerate erases the old reply and streams the new one in its place;
  - a rule drawn across the screen wherever the played story breaks;
  - providers configurable directly in the model picker (`/model` or Ctrl+O);
  - `/system` accepting a file in addition to text input.
- New commands: `/clear`, `/last`, `/balance`; command `/rename` renamed to `/title`.
- New CLI command: `otaku update`.

**Full version:**

Cloud arrives, and the model picker becomes the provider control center: OpenRouter and NanoGPT
next to the five local engines, API keys entered in the picker and stored sealed, providers in
their own config file — plus quality-of-life across the REPL.

### Added
- Cloud providers: OpenRouter and NanoGPT — their catalogs listed with context windows (fetched
  asynchronously, so the picker opens without waiting on the internet), the cloud prompt `$`
  instead of `>` while playing against one, and `/balance` for the account balance.
- New local backends: llama.cpp (`llama-server`) and LM Studio (load/unload included), joining
  Ollama, oMLX, and KoboldCpp; every backend now reports each model's context window, shown as a
  column in the picker.
- The picker's provider panel: every backend with its `URL:` and `API key:` fields, editable in
  place (paste works, the key never displayed), a tick for providers that answered, and models
  re-listed the moment a setting changes. Editing an unconfigured backend writes its section —
  that is how a cloud provider is added.
- `configs/providers.toml`: provider sections live in their own file now, one `[name]` section
  each — moved out of config.toml automatically, API keys sealed on the way (AES-256-GCM, the
  sealing key in the OS keychain; independent of the story encryption).
- Config migrations: one idempotent, convergent mechanism that reruns at every launch — dated
  pre-edit backups in `configs/backups/`, and a plain API key (hand-typed included) is sealed at
  the next launch.
- `otaku update`: detects how otaku was installed and runs that installer's own upgrade.
- `/undo` and `/regen` erase the taken-back turns from the screen when it is provably safe;
  `/last [N]` re-echoes the last turns for a clean view; `/clear` wipes the screen.
- A break rule wherever the played sequence on screen stops continuing: over an `/undo` report
  or a `/regen` marker that could not erase in place, and where `/new`, `/stories`, `/import`,
  or `/last` swaps or repeats the scene. It is the one thing an erase never takes, so a report
  replacing a marker slides in under the standing rule instead of stacking a second one.
- Dialogue coloring: spoken lines («quotes» and dash lines) render in blue, shaded to the
  detected terminal background (`[ui] dialogue_color`, `dialogue_bold`); the echoed prompt's band
  follows the background the same way.
- `/system` accepts an existing file's path and reads the prompt from it.
- Path autocompletion behind `@` in file arguments: the menu pops as typed and filters.
- Live smokes for all seven providers (`scenarios/live/`, `scripts/live-providers.sh`).

### Changed
- The picker lists bare model names grouped under provider captions, sizes and context flushed
  right; `/usage` prints purpose, provider, and model as columns; the banner shows the bare model
  name; `/info` reads its rows from the provider listing.
- `/regen` re-runs the last prompt when no reply stands — a failed request leaves the prompt
  unanswered, and regenerating sends it again.
- `/import` lands as deep in the scene as every other way into a story, and `/last` names what
  it put on screen.

### Fixed
- Forking carries the story's memory. A story shorter than `settle_messages` (20 by default) —
  the shipped sample among them — forked with no scenes and no journals at all.

## [0.2.1] - 2026-08-01

Packaging only — no functional changes.

### Changed
- The required Python version is now 3.11, down from 3.14.
- Dependency bounds updated.

## [0.2.0] - 2026-08-01

0.2 is a ground-up rewrite as a **roleplay terminal client**: chats are stories that can be
branched from any message, a background pass extracts lore from played messages — scenes,
characters, journals — and the context sent to the model keeps the opening and the recent tail
verbatim with scene summaries in between.

What carries over from 0.1: local models, one terminal, encrypted storage. The 0.1 chat and fleet
features (one-shot/pipe mode, `otaku list`/`otaku stop`, cross-provider RAM management,
`/remember` defaults) are gone. The database schema is new.

### Added
- Stories: branch from any message, fork with its memory, resume where you left off; a
  full-screen story browser with message-level resume and in-place editing.
- The lore engine: idle-debounced background extraction closes scenes over played messages, keeps
  per-character journals with rolled-up histories, and feeds the story back to the model as a
  recap; `/lore` browses and edits the memory in place.
- Roleplay commands: `/me`, `/you`, `/ooc` — framing joined at wire time, bodies stored verbatim.
- Import and export: a lossless Markdown story document, SillyTavern `.jsonl` chats, and
  plain-text dismantling — the format detected from the file.
- A sample story seeded into a fresh database, so a first launch lands mid-story — with or
  without a reachable model.
- Day-rotated request, system, and error logs (`otaku logs`).

## [0.1.1] - 2026-07-06

Initial public release. (`0.1.0` was a premature PyPI upload from a pre-release tree — it was
never tagged and is superseded by `0.1.1`.)

### Added
- Multi-backend client for Ollama, LM Studio, oMLX, and any OpenAI-compatible server — from one
  terminal command.
- Zero-config first run: the initial `~/.otaku/config.toml` auto-detects each built-in engine's
  port (and omlx's API key) from your environment (`OLLAMA_HOST`) or the engine's own settings
  file, falling back to the standard default. Runs once, at that first write; edit the sections
  freely afterwards.
- Cross-provider model management: `otaku list` (with `--running` to show only loaded models),
  load and unload from the picker, `otaku stop --all`, with a live RAM gauge. Provider queries run
  concurrently with a short (0.5s) probe timeout, so one configured-but-down provider no longer
  slows every command; when nothing is reachable, otaku names each provider, whether it answered,
  and points at `~/.otaku/config.toml` to fix.
- Chat REPL: streaming responses, thinking-effort control, tok/s stats (`/set verbose`, off by
  default), triple-quoted multiline input, in-chat model switching (`/model`), `/new` (fresh
  conversation) vs `/clear` (reset context in place), and slash commands.
- Streaming markdown rendering: headers, lists, blockquotes, rules, and fenced code blocks
  (syntax-highlighted via Pygments) on top of inline emphasis/code.
- omlx output smoothing (`[providers.omlx].smooth`, default on): de-jitters omlx's bursty token
  delivery into steady typing, without affecting tok/s.
- Persistent session defaults: a `[defaults]` config section (system, think, parameters,
  no_record) plus per-model overrides keyed by bare model name; `/remember` saves the current
  settings as the model's defaults.
- One-shot / pipe mode: `otaku <model> "prompt"` and `… | otaku <model>` print a plain reply and
  exit (prompt + stdin combined instruction-first), so otaku works as a Unix filter.
- Encrypted conversation history (AES-256-GCM), searchable across all conversations by full
  message content, with background LLM-generated summaries (idle-debounced so they never block
  exit or reload a cold model; `[defaults].create_summaries` / `summary_idle_seconds`), user-set
  titles (`/title`, shown in the `/history` picker), and resume-from-any-turn.
- Get answers out: `/copy` (last reply or whole chat → clipboard, via the native tool or an OSC
  52 fallback) and `/save <file>` (conversation → Markdown).
- Install via `uv tool install` or Homebrew (`brew install enclavum/tap/otaku`).
- Runs on macOS, Linux, and Windows. On Windows the streaming-time Ctrl+R (cancel + regenerate)
  shortcut is disabled — it needs a POSIX terminal — but everything else works; WSL gives full
  parity.
