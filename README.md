# otaku — a roleplay terminal client

[![PyPI](https://img.shields.io/pypi/v/otaku.svg)](https://pypi.org/project/otaku/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/enclavum/otaku/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://github.com/enclavum/otaku/blob/main/pyproject.toml)
[![Platforms](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/enclavum/otaku#requirements)

Stories that branch and grow their own lore — on your machine, with optional at-rest encryption.

![otaku demo](https://otaku.sh/demo.gif)

## What it is

Otaku is an LLM roleplay client (similar to SillyTavern, Janitor AI, etc.).

It's free, works on your machine and has a terminal interface. LLMs can be local (via llama.cpp,
KoboldCpp, Ollama and others) or accessed via an API service (OpenRouter, NanoGPT). Otaku needs no
infrastructure — no Docker, no database server — installs in one command and requires minimal
configuration.

Key features:

- **consistent prose**: the first 20 and the last 150 messages are always sent to the LLM as
  they are, to make it maintain the style;
- **context control**: as the number of messages grows, intermediate messages are split into
  scenes and are automatically replaced by scene summaries;
- **character recognition**: characters you introduce in your story are extracted automatically;
  each character maintains its own journal of what they've seen and experienced;
- **no fixed persona**: you are free to play any character during the story and hint the LLM who
  is playing who (the `/me` and `/you` commands);
- **helper commands** that hint the LLM on what to do next (the `/ooc` and `/cue` commands);
- **transparent context**: you can see what'll be sent to the LLM with the `/context` command.

Import your content:

- **character cards** — into a story you've already started (the `/card` command);
- **SillyTavern chats** — this creates a new story that you can continue (the `/import` command);
- **a text file** — will be split into turns and you can play with characters in it (also the
  `/import` command);
- **lorebooks or world info** have no equivalent in otaku, but they can be imported from a file
  into the system message (the `/system` command).

## Requirements

1. Platform: macOS, Linux, or Windows through WSL.
1. Local LLM provider(s) **or** an API key for cloud provider(s).

Backends and providers supported: llama.cpp, KoboldCpp, Ollama, oMLX, LM Studio; OpenRouter and
NanoGPT.

## Installation

The script first installs the `uv` package manager — if you don't have it yet — and then
installs otaku with it.

```bash
curl -LsSf https://otaku.sh/install.sh | sh
```

Other ways to install:

```bash
# directly with uv
uv tool install otaku

# alternatively, via Homebrew
brew trust enclavum/tap
brew install enclavum/tap/otaku
```

### Updating

```bash
otaku update
```

The command detects how otaku was installed (uv, brew, etc.) and runs that installer's own
upgrade.

## User guide

### Launching for the first time

```bash
otaku
```

On first start, you choose a provider and a model: otaku automatically detects local LLM
backends and lets you pick from their models. Cloud providers (OpenRouter, NanoGPT) are also in
the picker — enter an API key and their catalogs appear. After you've chosen (or cancelled with
Esc), you land at the prompt. The models picker is available later with the `/model` (Ctrl+O)
command.

To give you an idea of the features and what play looks like, on first start a sample story is
imported, and you land right in the middle of it. You can explore it with the `/lore`, `/cast`,
and `/context` commands.

The commands cheatsheet is available at `/help`.

### Starting a story

From there, you can start your own story with the `/new` command. You can also import a
SillyTavern chat with `/import`. Note that importing takes time, because it doesn't only import
the messages — it also extracts characters and scenes from them (more on that below), though you
can cancel the extraction. You can also import a plain text file the same way; it will be split
into messages.

### Playing

You send messages as usual, as your persona; the LLM infers which character to play from the
dialogue. There are helper commands — `/you`, `/me`, and `/ooc` — which only frame your prompt
with minimal injections like "you play as …" (you can see and configure these templates in
`~/.otaku/configs/prompts.toml`).

Mid-prompt, there are also two helper commands: `/ooc` and `/cue`. Both wrap the text after
them in an OOC block; the difference is that the `/ooc` block persists — right for a standing
note to the LLM — while the `/cue` block is sent only once — right for one-time story steering.

A few example prompts:

- `I follow the keeper deeper into the vault.` — plain play
- `/ooc Keep replies under three paragraphs.` — out of character, a standing note
- `"Who goes there?" I whisper. /ooc the keeper does not know me yet` — play with an aside
- `"Come away with me," I tell the keeper. /cue she refuses` — play with a one-time steer
- `/me Keeper: You are late again.` — hint the LLM you are playing as Keeper now
- `/you Keeper` — tell the LLM to play as Keeper
- `/you Keeper: she is furious` — the same but with a direction

During play, you can `/undo` (Ctrl+U) the last exchange and `/regen` (Ctrl+R) the last reply.

### Importing character cards

You can import character cards into the story you are playing with the `/card` command, where
you specify a card file to load (either PNG or JSON). The command automatically creates a
character in the lore (see below), and the character greets you. The card is treated as a normal
prompt — it's just that you are sending the card content as your message. The imported card can
later be edited in the `/cast` browser, and the context will change accordingly.

### Managing and forking stories

You can browse the stories you've played with the `/stories` (Ctrl+T) command. From the stories
picker, you can choose a story to continue from any message, or fork from there to another
story. You can also fork a new version of the story you are playing with the `/fork` command.
Forking copies all scenes, characters, journals, etc. to the new branch. Note that you can edit
messages in the stories picker with the `e` key.

### Extracting summaries and lore

After you've sent around 50 messages, a summary pass starts automatically in the background once
you've been idle for 5 minutes, so it doesn't disturb your roleplay. You can also run it on
demand with `/extract`. You'll see a notification and its progress in the status bar, and you
can keep playing meanwhile — replies will just be slower while it runs.

Once the extraction completes, you can browse and edit the extracted summaries and characters
with the `/lore` and `/cast` commands. Summaries are editable, so you can correct them however
you like.

### Understanding the context

The summaries only kick in once you have more than around 200 messages in the chat. The first 20
and the last 150 messages (both configurable) are always sent as-is, to preserve maximum detail
of recent story development and your prose style; everything in between is replaced with scene
summaries. Even though summaries may exist up to the latest message, only the older ones are
actually used. Nothing is included in the context by a condition or a trigger word.

You can use the `/context` command to see what exactly will be sent to the LLM.

## Configuration and environments

Everything lives in the state dir, `~/.otaku` by default:

- `configs/config.toml` — context shape, extraction thresholds, encryption, backups.
- `configs/providers.toml` — one section per provider (url, api key). The model picker edits it
  for you, and api keys are stored sealed.
- `configs/prompts.toml` — every template otaku ever sends, editable.
- `configs/state.toml`, `configs/models.toml` — the app's own memory of your session and
  per-model settings.

The config files are written on first run and after that edited only surgically — line by line,
never rewritten as a whole: version migrations at launch and the picker's provider edits, each
keeping the pre-edit file in `configs/backups/`. `prompts.toml` migrates the same way: a
template you left unedited follows a new release's built-in, and one you've edited is never
touched.

Set `OTAKU_CONFIG_DIR` to run a completely separate environment:
`OTAKU_CONFIG_DIR=~/.otaku-alt otaku`.

## Storage and privacy

Stories live in a local SQLite database; the database is snapshotted daily into the state dir,
the last seven kept (configurable).

Encryption at rest is disabled by default but is one config switch away (AES-256-GCM, sealed
client-side): the key can live in your OS keychain, come from a command of your choice (a
password manager, a hardware token), derive from a passphrase, or sit on disk. The request log
is sealed with the same cipher.

Provider API keys are always stored sealed, their key in the OS keychain.

Details in [SECURITY.md](https://github.com/enclavum/otaku/blob/main/SECURITY.md).

## Contributing

See [CONTRIBUTING.md](https://github.com/enclavum/otaku/blob/main/CONTRIBUTING.md) — a small,
focused project; contributions that keep it sharp are very welcome.

## License

[MIT](https://github.com/enclavum/otaku/blob/main/LICENSE).
